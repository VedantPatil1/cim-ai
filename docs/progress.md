# Progress Tracker

**Final Report Phase · May 2026**

---

## Summary

| Layer | What | Status |
|---|---|---|
| Control System Infrastructure | idpbuilder + Gitea + Actions + ArgoCD | **Complete** |
| Local GitOps Pipeline | End-to-end CI/CD on kind | **Complete** |
| AWS Infrastructure | EKS + ECR + VPC + ALB | **Complete (manual)** |
| Security Model | R1–R6 specification + enforcement | **Complete** |
| Security Analyser | Foundation-Sec-8B in Gitea Actions pipeline | **Complete** |
| Knowledge Graph | Extraction pipeline + seed graph + MCP server | **Complete (Phase 1)** |
| Agentic Layer | Langflow flows + MCP server + metrics | **Complete (Phase 1)** |
| Evaluation | TSR / MTTR framework + seed events | **Complete (Phase 1)** |
| Terraform IaC | Reproducible AWS provisioning as code | **Pending** |
| Kyverno | Policy-as-Code on cluster | **Pending** |

---

## Phase 1 — Control System Infrastructure

### Bootstrap

The full control plane is reproduced from a single command:

```bash
idpbuilder create \
  --use-path-routing \
  -c gitea:./control-system-infrastructure/cnoe-stack/gitea-config/override.yaml
```

This boots a local kind cluster with Gitea, Gitea Actions, and ArgoCD fully configured and wired together.

### What's Running

=== "Gitea"

    - In-cluster Git server at `cnoe.localtest.me:8443`
    - Built-in OCI-compliant container registry (no separate service required)
    - Gitea Actions enabled via config override
    - Repositories: `sample-backend-app` (app code), `sample-backend-gitops` (K8s manifests)

=== "Gitea Actions Runner"

    - `act_runner` deployed as a Kubernetes Deployment with Docker-in-Docker (dind)
    - 3-init-container setup: wait-for-dind → fetch-token → register-runner
    - Registration state persisted to PVC — survives pod restarts without re-registering
    - Labels: `ubuntu-latest`, `sandbox` — compatible with standard GitHub Actions syntax
    - Runner configured to trust local OCI registry and reach Gitea via internal cluster DNS

=== "ArgoCD"

    - GitOps operator reconciling cluster state from `sample-backend-gitops` repo
    - Poll interval: 60s
    - `sample-backend` Application: **Synced / Healthy**
    - Automated sync with self-heal enabled

=== "Platform Workflows"

    - CronJob running every 15 minutes
    - Synchronises two workflows into **every** Gitea repository via the Gitea Contents API:
        - `secret-scan.yaml` — runs gitleaks on every push and PR
        - `sandbox-lifecycle.yaml` — creates ArgoCD ApplicationSet for repos with `.cim/sandbox.yaml`
    - Mirrors GitHub's org-level "required workflows" (which Gitea lacks natively)
    - Repositories cannot permanently remove these workflows

=== "Sandbox Environments"

    - ArgoCD AppProject `sandbox` — restricts applications to `sandbox-*` namespaces
    - PostSync Job patches ArgoCD config to add `sandbox-agent` user with ApplicationSet-only RBAC
    - When a PR is opened in a GitOps repo: ApplicationSet PR generator creates a live environment in `sandbox-<repo>-pr-<N>`
    - Environment is pruned automatically when the PR is closed

---

## Phase 2 — GitOps Pipeline (Local, Verified End-to-End)

### CI Pipeline

Two jobs run on every push to `main`:

**`check` job** (runs on all pushes)

```
actions/checkout@v4
  → apt-get install python3-pip
  → pip3 install -r requirements.txt httpx pytest
  → python3 -m pytest tests/ -v
```

**`build-push` job** (runs on push to `main` only)

```
actions/checkout@v4
  → install docker.io + iproute2
  → set DOCKER_HOST=tcp://172.17.0.1:2375  (dind bridge gateway)
  → docker build + tag
  → docker login cnoe.localtest.me:8443
  → docker push image
  → git clone sample-backend-gitops (internal Gitea URL)
  → sed update image tag in deployment.yaml
  → git commit "ci: deploy <SHA>" + push
```

### What ArgoCD Sees

```yaml
# ArgoCD watches sample-backend-gitops for changes to this field:
image: cnoe.localtest.me:8443/giteaadmin/sample-backend-app:<git-sha>
```

Every CI run produces a new SHA-tagged image. ArgoCD detects the diff and rolls out the update — no manual intervention.

### Sample Application

| Property | Value |
|---|---|
| App | FastAPI (`/health`, `/`) |
| Namespace | `sample-staging` |
| Registry | `cnoe.localtest.me:8443/giteaadmin/sample-backend-app` |
| ArgoCD App | `sample-backend` — Synced / Healthy |
| Tests | pytest (health endpoint, root endpoint) |

---

## Phase 2 — AWS Infrastructure (Manually Provisioned)

The AWS environment exists and is validated. It has not yet been expressed as Terraform code (see [Remaining Work](#remaining-work)).

| Resource | Details | Status |
|---|---|---|
| ECR (`sample-api-ecr`) | `us-east-1`, scan-on-push, 5-image lifecycle | **Running** |
| VPC (`sample-api-vpc`) | `10.0.0.0/16`, dual-AZ, public + private subnets | **Running** |
| EKS (`sample-api-cluster`) | Fargate-only, K8s 1.30, Fargate profiles for staging + prod | **Running** |
| ALB Controller | IRSA-authenticated, provisions ALBs from Ingress resources | **Running** |
| IAM role chain | `cli-user` → `terraform-executor-role` (least privilege) | **Running** |
| Sample app | Deployed to `staging` namespace, reachable via ALB | **Running** |

---

## Security Model

Six requirements govern agent-to-infrastructure interaction. Each is a **hard mechanical control**, not an instruction.

| Req | What it prevents | Control | Hardness | Status |
|---|---|---|---|---|
| R1 — Agent identity isolation | One compromised credential exposes all operations | `dev-agent` / `admin-human` separate identities | Hard | **Live** |
| R2 — Least privilege | Agent acts outside its designated scope | `dev-agent` write-only + CODEOWNERS on workflows | Hard | **Live** |
| R3 — HITL gates | Agent merges/deploys without human review | `admin-human` approvals whitelist + branch protection | Hard | **Live** |
| R4 — Audit trail | Agent actions cannot be traced | Gitea PR/merge event log with actor + SHA | Soft | **Live** |
| R5 — Secret protection | Credentials committed or leaked | gitleaks on every push (via platform-workflows) | Hard | **Live** |
| R6 — Supply chain | Compromised CI deps execute arbitrary code | `protected_file_patterns` blocks workflow tampering | Hard | **Live** |

See the [GitOps Security Model](security/gitops-security.md) for the full user permission breakdown and verified test results.

---

## Phase 2 — Agentic Security Analyser (Live)

An agentic security analysis step is embedded directly in the CI pipeline for `sample-backend-app`. It runs automatically on every PR.

### How It Works

```
PR opened / updated
        │
        ▼
Gitea Actions: security-analysis.yaml
        │
        ├─ git diff origin/main...HEAD → /tmp/pr.diff
        │
        └─ python3 .gitea/scripts/security_check.py <pr> /tmp/pr.diff
                │
                ├─ POST /api/chat → Foundation-Sec-8B (streaming)
                │   http://host.docker.internal:11434
                │
                └─ POST Gitea API → PR comment
```

### Model

[Foundation-Sec-8B](https://huggingface.co/FenkoHQ/Foundation-Sec-8B) — Cisco's security-focused 8B model, running locally via Ollama. Produces structured output: Risk Level, Summary, Findings, GitOps Impact.

### Verified Behaviour

| Input | Risk Level | Comment Posted |
|---|---|---|
| Hardcoded `AWS_ACCESS_KEY_ID` + `DB_PASSWORD` | CRITICAL | Yes — by `gitea-actions` |
| Clean code change | LOW / INFORMATIONAL | Yes |

---

## Phase 3 — Agentic Layer (Phase 1 Complete)

The primary research contribution. Phase 1 delivers a functional knowledge graph, queryable MCP server, and four Langflow agent flows. See [Agentic Layer](agentic/index.md) for full details.

### Knowledge Graph

| File | Purpose | Status |
|---|---|---|
| `knowledge-graph/schema.py` | Pydantic v2 node/edge models | **Done** |
| `knowledge-graph/graph.json` | Seed graph: 20+ nodes, 22 edges | **Done** |
| `knowledge-graph/extract.py` | Claude API extraction agent (incremental, `--all` or diff-based) | **Done** |
| `knowledge-graph/mcp_server.py` | HTTP MCP server, port 8765, 4 query tools | **Done** |
| `.gitea/workflows/knowledge-graph-extract.yaml` | Gitea Actions trigger on doc/yaml/tf push | **Done** |

### Langflow Flows (Langflow 1.5 format, importable)

| Flow | What it does | Status |
|---|---|---|
| `agentic/security-analyser/flow.json` | PR diff → Claude security analysis → structured report | **Done (rebuilt in 1.5 format)** |
| `agentic/knowledge-graph-query/flow.json` | Natural language Q&A against knowledge graph | **Done** |
| `agentic/change-impact-analyzer/flow.json` | Proposed change → blast radius analysis via graph BFS | **Done** |
| `agentic/infrastructure-advisor/flow.json` | Conversational infra advisor with KG context + security system prompt | **Done** |

### Evaluation Metrics

| File | Purpose | Status |
|---|---|---|
| `metrics/schema.py` | `TaskEvent` dataclass + `log_event()` helper | **Done** |
| `metrics/events.json` | 8 seed events: ci-pipeline, security-analysis, kg-extraction, kg-query, change-impact, gitops-sync | **Done** |
| `metrics/calculate.py` | `python metrics/calculate.py --by-type` → TSR + MTTR per task type | **Done** |

**Seed metrics (8 events):** TSR 87.5% · MTTR 77.5s overall · MTTR 8.2s for KG queries

---

## Remaining Work

### Terraform IaC
All AWS resources (EKS, ECR, VPC, IAM, ALB Controller) were provisioned manually for validation. Terraform modules are required to make the infrastructure reproducible and satisfy the GitOps invariant.

### Kyverno
Policy-as-Code enforcement on the cluster: no privileged containers, registry restrictions, resource quotas, sandbox namespace egress restrictions.

### Agentic Layer — Phase 2 (deferred)

| Item | Description |
|---|---|
| Langflow → security_check.py wiring | Replace direct Ollama call with `POST $LANGFLOW_URL/api/v1/run/$FLOW_ID` |
| LangGraph workflows | Re-implement Langflow flows as Python code (required for production / auditability) |
| Real evaluation data | Run the system end-to-end and record actual TSR/MTTR events |
| Kuzu embedded graph DB | Phase 2: build Kuzu DB from `graph.json` for Cypher-style agent queries |
| KG Gitea Actions | Add `ANTHROPIC_API_KEY` secret + push CIM-AI repo to Gitea to activate auto-extraction |

---

## Timeline

| Phase | Period | Status |
|---|---|---|
| Literature Review + System Design | Jan–Feb 2026 | **Done** |
| Control Plane Implementation | Feb–Mar 2026 | **Done** |
| AWS Infrastructure + Security Model | Mar 2026 | **Done** |
| Security Analyser Prototype | Apr 2026 | **Done** |
| Agentic Layer Phase 1 (KG + Flows + Metrics) | Apr–May 2026 | **Done** |
| Evaluation (real data collection) | May 2026 | **In progress** |
| Final Report | May 1–12 2026 | **In progress** |
| Terraform IaC + Kyverno | Post-submission | **Deferred** |
