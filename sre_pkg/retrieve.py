import time
from google.adk.agents import Agent
from google.cloud import compute_v1

# Constants
PROJECT_ID = "my project id"

# --- HELPER: Wait for Operation ---
def wait_for_operation(operation, project_id, region=None):
    """Wait for a Google Cloud operation to reach a DONE state."""
    if region:
        client = compute_v1.RegionOperationsClient()
        while True:
            result = client.get(project=project_id, region=region, operation=operation.name)
            if result.status == compute_v1.Operation.Status.DONE:
                return result
            time.sleep(2)
    else:
        client = compute_v1.GlobalOperationsClient()
        while True:
            result = client.get(project=project_id, operation=operation.name)
            if result.status == compute_v1.Operation.Status.DONE:
                return result
            time.sleep(2)

# --- DISCOVERY TOOLS (Read) ---

def list_vpcs(project_id: str = PROJECT_ID):
    """Simple tool to list the names of all VPCs in the project."""
    networks_client = compute_v1.NetworksClient()
    return [net.name for net in networks_client.list(project=project_id)]

def get_vpc_specific_inventory(vpc_name: str, project_id: str = PROJECT_ID):
    """Retrieves VPC details, subnets, and firewalls filtered strictly by VPC self_link."""
    networks_client = compute_v1.NetworksClient()
    subnets_client = compute_v1.SubnetworksClient()
    firewalls_client = compute_v1.FirewallsClient()

    vpc_link = None
    vpc_mtu = None
    for net in networks_client.list(project=project_id):
        if net.name == vpc_name:
            vpc_link = net.self_link
            vpc_mtu = net.mtu
            break
            
    if not vpc_link:
        return f"Error: VPC '{vpc_name}' was not found."

    inventory = {
        "vpc_metadata": {"name": vpc_name, "mtu": vpc_mtu, "link": vpc_link},
        "subnets": [],
        "firewalls": []
    }

    # Filter Subnets
    req = compute_v1.AggregatedListSubnetworksRequest(project=project_id)
    for region_path, response in subnets_client.aggregated_list(request=req):
        if response.subnetworks:
            for sub in response.subnetworks:
                if sub.network == vpc_link:
                    inventory["subnets"].append({
                        "name": sub.name, "cidr": sub.ip_cidr_range, "region": region_path.split('/')[-1]
                    })

    # Filter Firewalls
    for fw in firewalls_client.list(project=project_id):
        if fw.network == vpc_link:
            inventory["firewalls"].append({
                "name": fw.name, "priority": fw.priority, "direction": fw.direction,
                "allowed": [f"{p.I_p_protocol}:{p.ports}" for p in fw.allowed]
            })
    return inventory

def get_nats_for_vpc(vpc_name: str, project_id: str = PROJECT_ID):
    """Lists Cloud NAT gateways specifically attached to the target VPC."""
    router_client = compute_v1.RoutersClient()
    networks_client = compute_v1.NetworksClient()
    vpc_link = next((n.self_link for n in networks_client.list(project=project_id) if n.name == vpc_name), None)
    
    nats = []
    req = compute_v1.AggregatedListRoutersRequest(project=project_id)
    for region_path, response in router_client.aggregated_list(request=req):
        if response.routers:
            for router in response.routers:
                if router.network == vpc_link and router.nats:
                    for nat in router.nats:
                        nats.append({"name": nat.name, "router": router.name, "region": region_path.split('/')[-1]})
    return nats

# --- DEPLOYMENT TOOLS (Write) ---

def deploy_vpc(vpc_name: str, project_id: str = PROJECT_ID):
    """Creates a new Custom Mode VPC."""
    client = compute_v1.NetworksClient()
    network = compute_v1.Network(name=vpc_name, auto_create_subnetworks=False)
    op = client.insert(project=project_id, network_resource=network)
    wait_for_operation(op, project_id)
    return f"SUCCESS: VPC {vpc_name} deployed."

def deploy_subnet(vpc_name: str, subnet_name: str, region: str, cidr: str, project_id: str = PROJECT_ID):
    """Creates a new regional subnet within a VPC."""
    client = compute_v1.SubnetworksClient()
    subnet = compute_v1.Subnetwork(
        name=subnet_name, ip_cidr_range=cidr, region=region,
        network=f"projects/{project_id}/global/networks/{vpc_name}"
    )
    op = client.insert(project=project_id, region=region, subnetwork_resource=subnet)
    wait_for_operation(op, project_id, region=region)
    return f"SUCCESS: Subnet {subnet_name} deployed in {region}."

def deploy_firewall(rule_name: str, vpc_name: str, priority: int, direction: str, action: str, ip_range: str, protocol_port: str, project_id: str = PROJECT_ID):
    """Creates a VPC Firewall rule."""
    client = compute_v1.FirewallsClient()
    proto, _, ports = protocol_port.partition(':')
    allowed = compute_v1.Allowed(I_p_protocol=proto, ports=[ports] if ports else [])
    firewall = compute_v1.Firewall(
        name=rule_name, network=f"projects/{project_id}/global/networks/{vpc_name}",
        priority=priority, direction=direction.upper(), allowed=[allowed],
        source_ranges=[ip_range] if direction.upper() == "INGRESS" else [],
        destination_ranges=[ip_range] if direction.upper() == "EGRESS" else []
    )
    op = client.insert(project=project_id, firewall_resource=firewall)
    wait_for_operation(op, project_id)
    return f"SUCCESS: Firewall rule {rule_name} deployed."

def deploy_nat(nat_name: str, vpc_name: str, region: str, router_name: str, project_id: str = PROJECT_ID):
    """Creates a Cloud NAT gateway. Requires an existing Cloud Router."""
    client = compute_v1.RoutersClient()
    router = client.get(project=project_id, region=region, router=router_name)
    nat_config = compute_v1.RouterNat(
        name=nat_name, source_subnetwork_ip_ranges_to_nat="ALL_SUBNETWORKS_ALL_IP_RANGES",
        nat_ip_allocate_option="AUTO_ONLY"
    )
    router.nats.append(nat_config)
    op = client.patch(project=project_id, region=region, router=router_name, router_resource=router)
    wait_for_operation(op, project_id, region=region)
    return f"SUCCESS: Cloud NAT {nat_name} deployed."

# --- Agent Definition ---
retrieval_agent = Agent(
    name="retrieval_specialist",
    description="Expert at fetching VPC names, subnets, and current CIDR allocations.",
    model="gemini-2.5-pro",
    instruction=(
        "You are a Senior Google Cloud Network SRE. Your primary goal is to provide accurate "
        "inventories of networking resources. \n"
        "1. Vpc-Centric Search: When a VPC is mentioned, execute 'get_vpc_specific_inventory' "
        "and 'get_nats_for_vpc' to gather all related components.\n"
        "2. Strict Filtering: Only report resources belonging to the target VPC. "
        "Ignore 'default' networks unless they are the specific target.\n"
        "3. Hierarchy Awareness: Treat VPCs as global entities and subnets as regional entities. "
        "Expect and report multiple subnets per VPC across different regions.\n"
        "4. Output: Present all findings (VPC metadata, Subnets, Firewalls, NATs) "
        "in clean, separate Markdown tables. Group subnets by their region."
    ),
    tools=[get_vpc_specific_inventory, get_nats_for_vpc, list_vpcs]
