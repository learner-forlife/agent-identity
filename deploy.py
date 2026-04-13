import vertexai
from vertexai.preview import reasoning_engines
from sre_pkg.agent import root_agent

# --- CONFIG ---
PROJECT_ID = "put the project id "
LOCATION = "us-central1"
STAGING_BUCKET = f"gs://{PROJECT_ID}-vcm"

# 1. Initialize global context
vertexai.init(project=PROJECT_ID, location=LOCATION, staging_bucket=STAGING_BUCKET)

# 2. Use the Beta Client for Agent Identity support
client = vertexai.Client(
    project=PROJECT_ID,
    location=LOCATION,
    http_options=dict(api_version="v1beta1")
)

# 3. Wrap the agent (Keeps the logic clean)
app = reasoning_engines.AdkApp(agent=root_agent)

print(f"🚀 Deploying Secure Orchestrator to {STAGING_BUCKET}...")

# 4. THE FIX: Pass extra_packages INSIDE the config dictionary
remote_app = client.agent_engines.create(
    agent=app,
    config={
        "identity_type": "AGENT_IDENTITY", 
        "staging_bucket": STAGING_BUCKET,
        "extra_packages": ["sre_pkg"],     # <--- This folder has all my files 
        "display_name": "NetworkAgent-with-agent-identity",
        "requirements": [
            "google-cloud-aiplatform[adk,agent_engines]",
            "google-cloud-compute",
            "pydantic>=2.0.0",
            "cloudpickle>=3.0.0",
        ],
    },
)

print("\n✅ DEPLOYMENT SUCCESSFUL!")
agent_id = remote_app.resource_name.split('/')[-1]
print(f"Agent ID: {agent_id}")
