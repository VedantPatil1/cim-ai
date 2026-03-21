# Methodology

## 1. Priority Model: Security > Reliability > Capability

The project operates under a strict priority ordering that governs every design decision.

```
Security      ── hard boundary — defines what the system is allowed to do at all
Reliability   ── success rate — how consistently it does what is allowed
Capability    ── use cases   — the range of things it can do reliably and safely
```

**Security is not a guideline — it is a constraint.** It is the absolute boundary between what an agentic system may and may not do, enforced at the tooling level, not at the prompt level. An agent cannot reason its way past a security boundary. This distinction is the direct lesson of the July 2025 Replit "Day 9" incident, where an agent bypassed a "no-change" directive and deleted a production database because the constraint existed only as an instruction, not as an enforced limit.

Security boundaries are implemented via:

- **Tool scoping** — agents receive only the MCP tools required for their specific task (Principle of Least Privilege)
- **A2A authentication** — agent-to-agent and agent-to-tool communication is authenticated, not assumed trusted
- **Human-in-the-loop (HITL) gates** — state-mutating actions (infrastructure changes, deployments, deletions) require explicit human approval
- **GitOps as an enforcement layer** — all mutations flow through pull requests with policy checks; no direct writes are permitted

**Reliability is the operational constraint.** Given a permitted operation, the system must complete it successfully at a measurable rate. Evaluation metrics:

- **Task Success Rate (TSR)** — percentage of tasks completed correctly end-to-end
- **Mean Time to Resolution (MTTR)** — time from issue detection to resolved state
- Measured against a baseline of manual operations and generalized AI systems

**Capability is last.** Use cases are only added once existing ones are secure and reliable. This deliberately trades breadth for trustworthiness.

---

## 2. Target Use Case

The dissertation focuses on a single, well-scoped scenario: **a simple backend application fully managed through GitOps**, where every operational concern — infrastructure, deployment, CI/CD, and policy — is maintained as code in Git.

The target application is a FastAPI backend service. It is not the subject of research. It is a concrete, controllable artifact that exercises all the infrastructure concerns under study.

### The GitOps Rule

Any change to infrastructure, deployment, pipeline, or policy is a change to a Git repository. There are no out-of-band mutations. The Git history is the audit trail.

| Concern | Mechanism |
|---|---|
| Cloud infrastructure provisioning | Terraform (IaC) |
| Application deployment state | Kubernetes manifests + ArgoCD |
| CI/CD pipeline definition | Gitea Actions workflows |
| Cluster policy enforcement | Policy as Code (Kyverno) |

### Operational Knowledge

Agents need structured, queryable context about the system — not raw documentation. Operational docs (runbooks, architecture notes, service ownership) are stored in Git, but they are not fed directly to agents as text. Instead, a Gitea Actions pipeline extracts entities and relationships from changed files on every commit and maintains a **knowledge graph**. Agents query the graph via a read-only MCP server rather than reading markdown.

This replaces the "docs as code" framing entirely. The graph is the operational knowledge layer. See [Operational Knowledge Graph](knowledge-graph.md) for the full design.

---

## 3. Infrastructure: Two Distinct Layers

This is a critical distinction. There are two separate infrastructure concerns that must not be conflated.

### Control System Infrastructure

The **management plane** — the toolchain that builds, deploys, and monitors the target system. This is what enables GitOps to function.

```
┌─────────────────────────────────────────────────┐
│           Control System Infrastructure          │
│                                                  │
│  Gitea          ← Git server (source of truth)   │
│  Gitea Actions  ← CI runner                      │
│  ArgoCD         ← GitOps operator                │
│  idpbuilder     ← bootstraps the above           │
│  CNOE stacks    ← packages the above             │
└─────────────────────────────────────────────────┘
```

This layer is bootstrapped locally using idpbuilder (kind cluster). It is the same layer used in production — only the backing infrastructure changes. The control system itself is not managed by Terraform. It is managed by CNOE/idpbuilder.

### Target Infrastructure and Deployment

The **application plane** — the cloud resources that the application runs on, and the application itself. This is what GitOps manages.

```
┌─────────────────────────────────────────────────┐
│         Target Infrastructure & Deployment       │
│                                                  │
│  AWS EKS       ← Kubernetes runtime              │
│  AWS ECR       ← Container image registry        │
│  VPC / IAM     ← Networking and access control   │
│  Kyverno       ← Policy enforcement on cluster   │
│                                                  │
│  All provisioned and defined via Terraform       │
└─────────────────────────────────────────────────┘
```

Terraform is mandatory here. It is what makes "cloud infrastructure management" substantive — without it, the system manages Kubernetes workloads but not the cloud infrastructure beneath them.

### How They Connect: The GitOps Bridge

```
Developer pushes code
        │
        ▼
   Gitea (control system)
        │ triggers
        ▼
   Gitea Actions CI (control system)
        │ builds image, pushes to ECR
        ▼
   AWS ECR (target infra)
        │ image tag update committed to gitops repo
        ▼
   ArgoCD (control system) detects diff
        │ syncs manifests
        ▼
   AWS EKS (target infra)
        │ Kyverno validates manifests before apply
        ▼
   Running application
```

The local (idpbuilder/kind) setup mirrors this exactly, replacing AWS EKS → kind cluster and AWS ECR → local registry. The workflow is identical; only the endpoints differ. This is by design — local development validates the same GitOps logic that runs in production.

---

## 4. Tech Stack

### Control System Infrastructure

| Component | Role | Status |
|---|---|---|
| **idpbuilder** | Bootstraps control plane (kind + Gitea + ArgoCD) | Implemented |
| **Gitea** | In-cluster Git server | Implemented |
| **Gitea Actions runners** | CI execution | Implemented |
| **ArgoCD** | GitOps operator | Implemented |
| **CNOE stacks** | Packages the above as reproducible deployments | Implemented |

### Target Infrastructure and Deployment

| Component | Role | Status |
|---|---|---|
| **Terraform** | Provisions AWS EKS, ECR, VPC, IAM | To implement |
| **AWS EKS / kind** | Kubernetes runtime (cloud / local) | Local: implemented |
| **AWS ECR / local registry** | Container image storage | Local: implemented |
| **Kyverno** | Policy as Code — enforces cluster guardrails | To implement |

### Agentic System *(next phase — not the current focus)*

The agentic layer is deliberately deferred until the GitOps workflow is stable and measurable. The current phase establishes the substrate the agents will operate on.

| Component | Role | Notes |
|---|---|---|
| **CAIPE** | Multi-agent supervisor framework | Reference architecture |
| **MCP servers** | Scoped tool interface per agent | One MCP server per concern |
| **Langflow** | Workflow prototyping | Prototype phase only → |
| **LangGraph** | Code-first workflow implementation | Target for production workflows |
| **LLM backend** | Anthropic Claude via API | Reasoning engine |

**On Langflow → LangGraph:** Langflow is used for rapid prototyping of agentic pipelines. Workflows built in Langflow will be re-implemented in LangGraph (Python, code-first) before evaluation. LangGraph workflows live in Git as code, which satisfies the auditability requirement that Langflow cannot meet on its own.
