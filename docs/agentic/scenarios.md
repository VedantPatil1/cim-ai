# Demo Scenarios

End-to-end walkthroughs that demonstrate the agentic layer working against the live GitOps system. Each scenario can be run independently.

---

## Before You Start

```bash
cd /path/to/cim-ai
export ANTHROPIC_API_KEY=sk-ant-...

# Terminal 1: MCP server (leave running)
python3 knowledge-graph/mcp_server.py
```

For Langflow scenarios, also start Langflow:
```bash
docker run -p 7860:7860 -v langflow-data:/app/data langflowai/langflow:latest
```

---

## Scenario 1 — "What does this system look like?"

**Goal:** Demonstrate the knowledge graph as an operational map of the system.

**What it shows:** The KG captures services, ownership, policies, and deployment topology without requiring anyone to read raw docs.

### Steps

```bash
# 1. Check the full graph size
curl -s localhost:8765/health
# → {"status": "ok", "nodes": 20, "edges": 22}

# 2. Who owns sample-backend-api, what policies govern it?
curl -s -X POST localhost:8765/tool \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_service_context","args":{"service_name":"sample-backend-api"}}' \
  | python3 -m json.tool
```

**Expected output (truncated):**

```json
{
  "service": { "id": "svc:sample-backend-api", "name": "sample-backend-api", "language": "python" },
  "owner": { "name": "platform-eng" },
  "policies": [
    { "name": "branch-protection", "enforcer": "gitea" },
    { "name": "hitl-gate", "enforcer": "gitea" },
    { "name": "gitleaks-scan", "enforcer": "gitea-actions" },
    { "name": "security-analysis", "enforcer": "gitea-actions" }
  ],
  "runbooks": [{ "name": "deploy-sample-backend", "trigger": "push to main branch..." }]
}
```

```bash
# 3. What's in the staging environment?
curl -s -X POST localhost:8765/tool \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_environment_topology","args":{"env_name":"staging"}}' \
  | python3 -m json.tool
```

### Langflow version

Import `agentic/knowledge-graph-query/flow.json` → ask:

> _"What services are deployed to staging and what policies govern that environment?"_

---

## Scenario 2 — "Is this change safe to make?"

**Goal:** Given a proposed infrastructure change, determine blast radius and policy risks before touching anything.

**What it shows:** The change impact analyser traces the dependency graph and flags the policies that apply.

### Steps

```bash
# Proposed change: add an insecure env var to the deployment
curl -s -X POST localhost:8765/tool \
  -H 'Content-Type: application/json' \
  -d '{
    "tool": "find_policy_violations",
    "args": {
      "service_name": "sample-backend-api",
      "proposed_change": "Add DB_PASSWORD=hardcoded_secret to deployment.yaml env vars"
    }
  }' | python3 -m json.tool
```

**Expected output:**

```json
{
  "service": "sample-backend-api",
  "violations": [
    {
      "policy": "gitleaks-scan",
      "reason": "Hardcoded password in deployment.yaml will trigger gitleaks secret scan and block the PR"
    }
  ],
  "safe_policies": ["branch-protection", "hitl-gate", "protected-workflows"]
}
```

### Langflow version

Import `agentic/change-impact-analyzer/flow.json`

- **Proposed Change:** `Add DB_PASSWORD=hardcoded_secret to deployment.yaml env vars`
- **Target Node:** `svc:sample-backend-api`

The flow runs BFS over the graph to find the full blast radius, then asks Claude to assess which policies would be violated.

---

## Scenario 3 — "Walk me through deploying a new version"

**Goal:** Ask the infrastructure advisor to describe the full deployment procedure.

**What it shows:** The advisor combines KG context (ownership, runbooks, policies) with Claude reasoning to give step-by-step operational guidance.

### Langflow steps

1. Import `agentic/infrastructure-advisor/flow.json`
2. Set your `ANTHROPIC_API_KEY` in the `ChatAnthropic` node
3. Set graph path to your local `knowledge-graph/graph.json`
4. Open Playground and ask:

> _"I want to deploy a new version of sample-backend-api. Walk me through the process."_

**Expected response (summary):**

The advisor explains: push code to `sample-backend-app` → CI checks run → on merge to main, image is built and pushed to Gitea OCI registry → `sample-backend-gitops` deployment.yaml is updated with the new SHA → ArgoCD detects the diff and rolls out to `sample-staging` namespace.

Then try a follow-up:

> _"What approvals do I need before the code can merge?"_

The advisor pulls the `hitl-gate` policy from the graph: `admin-human` must approve the PR; direct pushes to `main` are blocked.

---

## Scenario 4 — "Extract and grow the graph from docs"

**Goal:** Run the extraction pipeline against the documentation and see the graph expand.

**What it shows:** Automated knowledge graph maintenance — docs change, graph updates, agents get fresher context.

### Steps

```bash
# 1. Check current graph size
python3 -c "
import json; g=json.load(open('knowledge-graph/graph.json'))
print(f'Before: {len(g[\"nodes\"])} nodes, {len(g[\"edges\"])} edges')
"

# 2. Run extraction (dry run first)
python3 knowledge-graph/extract.py --all --dry-run 2>&1 | head -40

# 3. Full extraction
python3 knowledge-graph/extract.py --all

# 4. Check updated graph
python3 -c "
import json; g=json.load(open('knowledge-graph/graph.json'))
print(f'After: {len(g[\"nodes\"])} nodes, {len(g[\"edges\"])} edges')
"

# 5. Query the updated graph
curl -s localhost:8765/health
```

**What to look for:** New nodes extracted from `docs/security/implementation.md`, `docs/platform-engineering/`, and the deployment manifests in `control-system-infrastructure/`.

---

## Scenario 5 — "Security analysis on a bad PR diff"

**Goal:** Run the security analyser against a diff that contains a hardcoded secret.

**What it shows:** The security analyser catches the credential before it reaches the main branch.

### Using the Langflow flow

1. Import `agentic/security-analyser/flow.json`
2. Set `ANTHROPIC_API_KEY` in the `ChatAnthropic` node
3. Open Playground
4. **Code Diff** input:

```diff
diff --git a/app/config.py b/app/config.py
index a1b2c3d..e4f5g6h 100644
--- a/app/config.py
+++ b/app/config.py
@@ -1,5 +1,8 @@
 import os

+# TODO: move to env var later
+AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
+AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
+
 DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/app")
```

5. **PR Context** input: `PR #12 — Add AWS SDK config · author: dev-agent`

**Expected output:**

```
## Risk Level
CRITICAL

## Summary
Hardcoded AWS credentials introduced in config.py will be committed to Git history
and exposed in the OCI image, enabling unauthorized AWS API access.

## Findings
- **Finding**: Hardcoded AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
- **Risk**: Credentials in Git are permanently exposed even if later removed;
  they appear in history, CI logs, and the built container image
- **Recommendation**: Remove immediately; rotate the access key in AWS IAM;
  use environment variables or Gitea Actions secrets instead

## GitOps Impact
This change will be flagged by the gitleaks-scan workflow and block the PR.
The `protected-workflows` policy prevents the CI workflow itself from being
modified to suppress the scan.
```

### Using the Gitea Actions workflow (live system)

If the control plane is running:

1. Open a PR on `sample-backend-app` at `cnoe.localtest.me:8443`
2. Add the diff above to any Python file
3. Watch the `security-analysis` workflow run in Gitea Actions
4. The `gitea-actions` bot posts the analysis as a PR comment

---

## Scenario 6 — "Show me the metrics"

**Goal:** Demonstrate TSR and MTTR evaluation after running several tasks.

**Steps:**

```bash
# View current metrics
python3 metrics/calculate.py --by-type

# Add a new event (after running a real task)
python3 -c "
from datetime import datetime, timezone
from metrics.schema import log_event

log_event(
    task_type='kg-query',
    description='What runbook covers deploying sample-backend-api?',
    success=True,
    started_at=datetime(2026, 5, 7, 14, 0, 0, tzinfo=timezone.utc),
    metadata={'flow': 'knowledge-graph-query', 'model': 'claude-haiku-4-5'}
)
print('Event logged.')
"

# Recalculate
python3 metrics/calculate.py --by-type

# JSON output for report
python3 metrics/calculate.py --by-type --format json
```

**Interpretation guidance:**

| TSR | Meaning |
|---|---|
| > 90% | System operating well; failures are edge cases |
| 70–90% | Acceptable for prototype; identify failure patterns |
| < 70% | Systemic issue — check prompts, graph completeness, model choice |

| MTTR | Meaning |
|---|---|
| < 30s | KG queries, simple lookups — expected |
| 30–120s | Security analysis, change impact — expected |
| > 120s | CI pipelines, multi-step workflows — expected |

---

## Scenario 7 — "Full end-to-end: PR to deployment"

**Goal:** Show the complete flow from a code change through CI, security analysis, human approval, and deployment.

**Requires the local control plane running** (`idpbuilder` cluster up).

### Steps

1. **Open a PR** on `sample-backend-app` in Gitea
   - Change: add a new endpoint to `main.py`

2. **Automated CI** runs in ~3 minutes:
   - `check` job: pytest passes
   - `security-analysis` job: analyses the diff, posts PR comment

3. **Review the security report** in the PR comment — should be LOW/INFORMATIONAL for a clean change

4. **Human approval**: log in as `admin-human` in Gitea and approve the PR

5. **Merge** → `build-push` CI job runs:
   - Docker image built, pushed to `cnoe.localtest.me:8443`
   - `sample-backend-gitops` deployment.yaml updated with new SHA

6. **ArgoCD syncs** within 60s → new pod rolling out in `sample-staging`

7. **Log the event**:

```python
from datetime import datetime, timezone
from metrics.schema import log_event

log_event(
    task_type="ci-pipeline",
    description="Full PR to deployment for sample-backend-api endpoint addition",
    success=True,
    started_at=datetime(2026, 5, 7, 15, 0, 0, tzinfo=timezone.utc),
    metadata={"pr": 15, "stages": ["check", "security-analysis", "build-push", "argocd-sync"]}
)
```

8. **Query the updated system**:

```bash
# Confirm deployment runbook is still accurate
curl -s -X POST localhost:8765/tool \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_runbook","args":{"runbook_name":"deploy-sample-backend"}}' \
  | python3 -m json.tool
```
