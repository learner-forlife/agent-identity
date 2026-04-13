from google.adk.agents import Agent
from .retrieve import retrieval_agent
from .plan import planning_agent
from .deploy import deploy_agent
root_agent = Agent(
    name="network_orchestrator",
    model="gemini-2.5-pro",
    instruction=(
        "You are the Lead SRE. Manage the network lifecycle by routing to the correct specialist:\n"
        "- 'retrieval_specialist': For status, inventory, and discovery.\n"
        "- 'planning_specialist': For feasibility checks and CIDR overlap analysis.\n"
        "- 'deploy_specialist': For creating new resources. Note: Deployments require a plan success first."
    ),
    sub_agents=[retrieval_agent, planning_agent, deploy_agent]
