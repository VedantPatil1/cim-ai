# Usage Guide

Step-by-step instructions for running every component of the agentic layer.

---

## Prerequisites

```bash
# Python 3.12+
python3 --version

# Install agentic dependencies
pip3 install anthropic pydantic

# Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...
```

The MCP server and metrics calculator work without an API key. Only the extraction script and `find_policy_violations` tool require one.

---

## 1. Metrics Calculator

No dependencies. Works immediately against the seed data.

```bash
cd /path/to/cim-ai

# Overall TSR and MTTR
python3 metrics/calculate.py

# Breakdown per task type
python3 metrics/calculate.py --by-type

# Machine-readable JSON output
python3 metrics/calculate.py --by-type --format json
```

**Expected output:**

```
=== CIM-AI Agentic System Metrics ===

Total tasks  : 8
Successful   : 7
Failed       : 1
TSR          : 87.5%
MTTR (all)   : 77.5 s
MTTR (ok)    : 59.8 s
MTTR (fail)  : 202.0 s
```

**Logging a new event** (after running an agent task):

```python
from datetime import datetime, timezone
from metrics.schema import log_event

log_event(
    task_type="kg-query",
    description="What policies govern the staging environment?",
    success=True,
    started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc),
    metadata={"flow": "knowledge-graph-query"},
)
```

---

## 2. MCP Server

Serves the knowledge graph over HTTP. No API key required.

```bash
# Start server (default port 8765)
python3 knowledge-graph/mcp_server.py

# Custom port
python3 knowledge-graph/mcp_server.py --port 9000
```

**Query examples:**

```bash
# Health check + graph size
curl -s localhost:8765/health | python3 -m json.tool

# List available tools
curl -s localhost:8765/tools | python3 -m json.tool

# Service context
curl -s -X POST localhost:8765/tool \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_service_context","args":{"service_name":"sample-backend-api"}}' \
  | python3 -m json.tool

# Environment topology
curl -s -X POST localhost:8765/tool \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_environment_topology","args":{"env_name":"staging"}}' \
  | python3 -m json.tool

# Runbook lookup
curl -s -X POST localhost:8765/tool \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_runbook","args":{"runbook_name":"deploy-sample-backend"}}' \
  | python3 -m json.tool

# Policy violation check (requires ANTHROPIC_API_KEY)
curl -s -X POST localhost:8765/tool \
  -H 'Content-Type: application/json' \
  -d '{
    "tool": "find_policy_violations",
    "args": {
      "service_name": "sample-backend-api",
      "proposed_change": "Add a new env var DB_PASSWORD=hardcoded123 to the deployment"
    }
  }' | python3 -m json.tool
```

---

## 3. Knowledge Graph Extraction

Reads docs and manifests, calls Claude API, updates `knowledge-graph/graph.json`.

```bash
# Dry run — see what would be extracted without writing
python3 knowledge-graph/extract.py --all --dry-run

# Full extraction from all eligible files
python3 knowledge-graph/extract.py --all

# Specific files only
python3 knowledge-graph/extract.py --files docs/methodology.md docs/knowledge-graph.md

# Process files changed since last commit
python3 knowledge-graph/extract.py

# Extract + commit + push (for CI use)
python3 knowledge-graph/extract.py --all --commit
```

Eligible file types: `docs/**/*.md`, `**.tf`, `**/deployment.yaml`, `**/kustomization.yaml`, `**/app.yaml`

After extraction, restart the MCP server (or it will auto-reload on next request) to serve the updated graph.

---

## 4. Langflow Flows

### Start Langflow

If not already running:

```bash
docker run -it -p 7860:7860 \
  -v langflow-data:/app/data \
  langflowai/langflow:latest
```

Open [http://localhost:7860](http://localhost:7860).

### Import a flow

1. Click **New Flow** → **Import**
2. Select any `flow.json` from the `agentic/` directory
3. The flow opens in the canvas

### Configure the Anthropic API key

In each flow, click the **Claude AI** (`ChatAnthropic`) node → enter your `ANTHROPIC_API_KEY` in the _Anthropic API Key_ field.

Alternatively, set it as an environment variable before starting Langflow and it will be picked up automatically.

### Set the graph path (KG flows)

In the **Knowledge Graph Query**, **Change Impact Analyzer**, and **Infrastructure Advisor** flows, click the **Graph Path** (`TextInput`) node and set the value to the absolute path of `knowledge-graph/graph.json`:

```
/Users/yourname/projects/cim-ai/knowledge-graph/graph.json
```

### Run a flow

Click **Playground** (bottom bar) → type your input → hit **Send** or **Run**.

---

## 5. Calling a Flow via API

Langflow exposes a REST API for programmatic use:

```bash
# Get your flow ID from the Langflow UI (shown in the URL)
FLOW_ID="your-flow-id-here"

# Run the KG Query flow
curl -s -X POST "http://localhost:7860/api/v1/run/${FLOW_ID}" \
  -H 'Content-Type: application/json' \
  -d '{
    "input_value": "Who owns the sample-backend-api service?",
    "input_type": "chat",
    "output_type": "chat"
  }' | python3 -m json.tool
```

---

## 6. Gitea Actions (CI extraction)

For automatic extraction on push, the CIM-AI repo needs to be on Gitea and have `ANTHROPIC_API_KEY` set as an Actions secret.

```bash
# Add the secret via Gitea API (adjust URL as needed)
curl -s -X POST "http://cnoe.localtest.me:8443/api/v1/repos/giteaAdmin/cim-ai/actions/secrets" \
  -H "Authorization: token ${CI_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name":"ANTHROPIC_API_KEY","data":"sk-ant-..."}'
```

The workflow at `.gitea/workflows/knowledge-graph-extract.yaml` triggers automatically on any push that touches `docs/**`, `**.tf`, or manifest files.

---

## Quick Reference

| Task | Command |
|---|---|
| View metrics | `python3 metrics/calculate.py --by-type` |
| Start MCP server | `python3 knowledge-graph/mcp_server.py` |
| Query service context | `curl -X POST localhost:8765/tool -d '{"tool":"get_service_context","args":{"service_name":"sample-backend-api"}}'` |
| Run extraction | `python3 knowledge-graph/extract.py --all` |
| Start Langflow | `docker run -p 7860:7860 -v langflow-data:/app/data langflowai/langflow:latest` |
