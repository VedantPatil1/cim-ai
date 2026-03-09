# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CIM-AI is a dissertation project implementing agentic AI for cloud infrastructure management using GitOps. It is primarily infrastructure configuration and documentation — there is no application source code yet.

## Commands

### Documentation Site

```bash
make docs          # install deps + serve with live reload (opens browser)
make docs-build    # build static site to docs/site/
make clean         # remove docs/site/
```

### Control Plane Bootstrap

```bash
# Bootstrap the local control plane (kind cluster + Gitea + ArgoCD)
idpbuilder create \
  --use-path-routing \
  -c gitea:./control-system-infrastructure/cnoe-stack/gitea-config/override.yaml
```

## Architecture

### Two Infrastructure Layers

The project separates two distinct infrastructure concerns:

**1. Control System Infrastructure** (management plane) — bootstrapped via `idpbuilder`, not managed by Terraform:
- **Gitea** — in-cluster Git server (source of truth)
- **Gitea Actions** — CI runner
- **ArgoCD** — GitOps operator
- **idpbuilder/kind** — bootstraps and packages the above locally

**2. Target Infrastructure & Deployment** (application plane) — managed exclusively via Terraform + GitOps:
- AWS EKS / local kind cluster
- AWS ECR / local Gitea OCI registry
- Kyverno (policy enforcement) — not yet implemented
- Terraform for AWS provisioning — not yet implemented

### The GitOps Rule

Every change flows through Git — no out-of-band mutations. The Git history is the audit trail:

| Concern | Mechanism |
|---|---|
| Cloud infrastructure | Terraform |
| Application deployments | Kubernetes manifests + ArgoCD |
| CI/CD pipelines | Gitea Actions workflows |
| Policy enforcement | Kyverno (Policy as Code) |

Local development (idpbuilder/kind) mirrors production exactly; only endpoints differ (kind vs. EKS, local registry vs. ECR).

### Priority Model

All design decisions follow: **Security > Reliability > Capability**

- **Security** is a hard constraint enforced at the tooling level (tool scoping, A2A auth, HITL gates, GitOps as enforcement layer) — not via prompts or instructions.
- **Reliability** is the operational constraint (Task Success Rate, MTTR).
- **Capability** (supported use cases) is only expanded once existing cases are secure and reliable.

### Agentic System (future phase — deferred until GitOps is stable)

- **MCP servers** — one per concern, scoped to principle of least privilege
- **LangGraph** — production workflow implementation (code-first, lives in Git)
- **Langflow** — prototyping only; workflows are re-implemented in LangGraph before evaluation
- **LLM backend** — Anthropic Claude API
- **Knowledge graph** — extracted from docs/manifests/IaC on every relevant commit via Gitea Actions; agents query it via a read-only MCP server rather than reading raw markdown

### Documentation Structure

Docs live in `docs/content/` and are built with MkDocs Material theme. Key files:
- `methodology.md` — priority model, GitOps rule, two-layer infrastructure design
- `knowledge-graph.md` — knowledge graph schema and extraction pipeline design
- `platform-engineering/` — idpbuilder/CNOE setup and CI/CD workflow design
