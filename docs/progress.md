# Progress Tracker

**Mid-Semester Status · April 2026**

---

## Summary

| Layer | What | Status |
|---|---|---|
| Control System Infrastructure | idpbuilder + Gitea + Actions + ArgoCD | **Complete** |
| Local GitOps Pipeline | End-to-end CI/CD on kind | **Complete** |
| AWS Infrastructure | EKS + ECR + VPC + ALB | **Complete (manual)** |
| Security Model | R1–R6 specification + partial enforcement | **Complete** |
| Terraform IaC | Reproducible AWS provisioning as code | **Pending** |
| Kyverno | Policy-as-Code on cluster | **Pending** |
| Agentic Layer | MCP servers + LangGraph workflows | **Pending** |
| Knowledge Graph | Extraction pipeline + agent query interface | **Pending** |
| Evaluation | TSR / MTTR / efficiency metrics | **Pending** |

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

## Remaining Work

### Terraform IaC
All AWS resources (EKS, ECR, VPC, IAM, ALB Controller) were provisioned manually for validation. Terraform modules are required to make the infrastructure reproducible and to satisfy the GitOps invariant — infrastructure that isn't expressed as code isn't auditable.

### Kyverno
Policy-as-Code enforcement on the cluster: no privileged containers, registry restrictions, resource quotas, sandbox namespace egress restrictions. This is the second enforcement layer for the sandbox security model.

### Agentic Layer (Phase 3 — primary research contribution)

| Component | Description |
|---|---|
| MCP servers | One per concern: state reader (read-only), ArgoCD operator, Gitea code agent |
| LangGraph workflows | Code-first Python: deployment promotion, incident triage, issue investigation |
| HITL interrupt points | Defined state transitions that escalate to human approval before proceeding |
| Prompt injection defence | Tooling layer sanitises all infrastructure content before LLM context |
| Blast radius assessment | Pre-execution check; escalates if threshold exceeded |

### Knowledge Graph Extraction Pipeline

```
Push to docs/** or **.tf or **/deployment.yaml
         │
         ▼
Gitea Actions workflow
         │
         ▼
Claude API (structured JSON output schema)
   { nodes: [...], edges: [...] }
         │
         ▼
Merge with existing graph.json
         │
         ▼
Commit updated graph back to repo
```

Phase 1: JSON in Git (`knowledge-graph/graph.json`) — no external services, fully auditable  
Phase 2: Kuzu embedded DB built from `graph.json` for Cypher-style queries

### Evaluation

| Metric | Description | Baseline |
|---|---|---|
| Task Success Rate (TSR) | % of operational tasks completed correctly end-to-end | Manual operations + unrestricted Claude API |
| Mean Time to Resolution (MTTR) | Time from task initiation to confirmed resolution | Manual operations baseline |
| System Efficiency & Cost | Token count, tool calls, API cost per task | Unrestricted Claude API |

---

## Timeline

| Phase | Period | Status |
|---|---|---|
| Literature Review + System Design | Jan–Feb 2026 | **Done** |
| Control Plane Implementation | Feb–Mar 2026 | **Done** |
| AWS Infrastructure + Security Model | Mar 2026 | **Done** |
| Terraform IaC + Kyverno | Mar–Apr 2026 | **In progress** |
| Agentic Layer Implementation | Apr 2026 | **Upcoming** |
| Evaluation and Metric Collection | Apr–May 2026 | **Upcoming** |
| Final Report | May 2026 | **Upcoming** |
