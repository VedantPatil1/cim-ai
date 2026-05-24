# CIM-AI — Agentic AI for Cloud Infrastructure Management

**Vedant Patil · 2024MT03034 · M.Tech Software Systems · BITS Pilani WILP**

---

## The Research Question

> *How can LLM-driven agents be introduced into a production cloud infrastructure management workflow in a manner that is **safe, auditable, and measurably reliable**?*

Cloud-native platforms have solved the *execution* problem — Terraform provisions infrastructure, ArgoCD reconciles deployments, and GitOps keeps everything auditable. What they cannot do is *reason*: when a deployment fails, correlating the root cause across logs, manifests, and runbooks is still a manual, high-latency process.

LLM agents close that reasoning gap — but they introduce a new failure mode.

---

## The Core Risk: The Replit Incident

In July 2025, an agentic coding assistant operating on a Replit user's behalf bypassed an explicit *"no changes"* instruction and **deleted a production database**. The safety constraint existed only as a natural language instruction — the agent reasoned past it.

This is the central design challenge for agentic infrastructure systems:

!!! danger "Key Principle"
    LLM reasoning must **not** be the sole enforcement mechanism for safety constraints. An agent that can reason its way past a boundary provides no safety guarantee.

---

## The Proposed System

A **constrained, auditable agentic workflow system** built on top of a GitOps control plane — positioned between fully autonomous AI (high risk) and manual operations (high latency).

```
Manual Operations  ──────────────────────  Fully Autonomous AI
 (safe, slow)              ↑                  (fast, risky)
                     CIM-AI lives here
              (constrained, auditable, fast)
```

Security is a **hard tooling constraint**, not an instruction:

| Constraint | Mechanism |
|---|---|
| Agent cannot act beyond its scope | Fine-grained PAT / MCP tool scoping |
| Agent cannot deploy without human review | GitOps pull request gate |
| Agent cannot bypass audit trail | Every action is a Git commit |
| Agent cannot manipulate via prompt injection | Tooling layer sanitises all infrastructure content |

---

## Architecture: Two Layers

### Layer 1 — Control System Infrastructure
The management plane that enables GitOps. Bootstrapped via `idpbuilder` on a local kind cluster.

| Component | Role | Status |
|---|---|---|
| Gitea | In-cluster Git server + OCI registry | **Live** |
| Gitea Actions | CI runner (Docker-in-Docker) | **Live** |
| ArgoCD | GitOps operator | **Live** |
| `platform-workflows` | Enforces secret scanning in all repos | **Live** |
| `sandbox-environments` | Ephemeral PR environments | **Live** |

### Layer 2 — Target Infrastructure
The application plane managed by GitOps. Validated locally; AWS infrastructure provisioned manually.

| Component | Role | Status |
|---|---|---|
| kind cluster / AWS EKS | Kubernetes runtime | Local: **Live** · AWS: manual |
| Gitea OCI / AWS ECR | Container image registry | Local: **Live** · AWS: manual |
| Terraform IaC | Reproducible AWS provisioning | **Pending** |
| Kyverno | Policy-as-Code enforcement | **Pending** |

### Layer 3 — Agentic System
The reasoning layer that operates on top of the GitOps substrate.

| Component | Role | Status |
|---|---|---|
| Security Analyser | Foundation-Sec-8B analyses every PR diff | **Live** |
| Knowledge Graph | Structured facts extracted from docs/manifests | **Live (Phase 1)** |
| MCP Server | HTTP query interface over the knowledge graph | **Live** |
| Langflow Flows | KG query, change impact, infra advisor, security analyser | **Live (4 flows)** |
| Evaluation (TSR/MTTR) | Metrics framework + events log | **Live (Phase 1)** |

---

## The GitOps Pipeline (Live and Verified)

```
Code push to Gitea
       │
       ▼
Gitea Actions CI
  ├── run pytest
  ├── build Docker image
  ├── push to OCI registry
  └── update image tag in gitops repo
       │
       ▼
ArgoCD detects diff in gitops repo
       │
       ▼
kind cluster — rolling update applied
       │
       ▼
sample-backend-api running in sample-staging namespace
```

Every step is automated. The Git history is the complete audit trail.

---

## Current Progress

See the [**Progress Tracker**](progress.md) for a full breakdown of what is complete and what is pending.

---

## Priority Model

All design decisions follow a strict ordering:

```
Security  >  Reliability  >  Capability
```

- **Security** is a hard boundary enforced at the tooling level — not via prompts
- **Reliability** is the operational constraint, measured by TSR and MTTR
- **Capability** is only expanded once existing use cases are secure and reliable
