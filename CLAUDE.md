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
# Full bootstrap: kind cluster + Gitea + ArgoCD + Keycloak + Langflow + Gitea Actions Runner
idpbuilder create \
  --recreate \
  --use-path-routing \
  -c gitea:./control-system-infrastructure/cnoe-stack/gitea-config/override.yaml \
  -p control-system-infrastructure/cnoe-stack/packages/gitea-runner \
  -p control-system-infrastructure/cnoe-stack/packages/langflow
```

```bash
# After bootstrap: set the Anthropic API key for Langflow
kubectl create secret generic langflow-api-keys \
  -n langflow \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --dry-run=client -o yaml | kubectl apply -f -
```

```bash
# After bootstrap: manually apply the Keycloak ArgoCD Application
# (idpbuilder doesn't know about keycloak — it's managed separately via its Gitea repo)
kubectl apply -f control-system-infrastructure/cnoe-stack/packages/keycloak/app.yaml
```

**IMPORTANT after each cluster rebuild:**
1. Get the new Gitea token:
   ```bash
   kubectl get secret -n gitea gitea-credential -o jsonpath='{.data.token}' | base64 -d
   ```
2. Update `hostAliases` IP in langflow + oauth2-proxy deployments if nginx ClusterIP changed:
   ```bash
   kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.spec.clusterIP}'
   ```
   Push the change to the `idpbuilder-localdev-langflow-manifests` Gitea repo.

URLs after bootstrap:
- ArgoCD:   https://cnoe.localtest.me:8443/argocd
- Gitea:    https://cnoe.localtest.me:8443/gitea
- Keycloak: https://cnoe.localtest.me:8443/keycloak  (admin / admin)
- Langflow: https://cnoe.localtest.me:8443/langflow   (SSO via Keycloak — user: platform / platform)

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

### Agentic System (Phase 1 implemented)

- **Langflow** — in-cluster at `/langflow`, protected by Keycloak SSO via oauth2-proxy
- **MCP server** — `knowledge-graph/mcp_server.py`, port 8765, 4 query tools over graph.json
- **Knowledge graph** — `knowledge-graph/graph.json`, extracted via `extract.py` (Claude API), auto-updated by Gitea Actions on doc/manifest changes
- **LLM backend** — Anthropic Claude API (`claude-haiku-4-5`), key in K8s Secret `langflow-api-keys`
- **Metrics** — `metrics/calculate.py` computes TSR / MTTR from `metrics/events.json`

### Documentation Structure

Docs live in `docs/content/` and are built with MkDocs Material theme. Key files:
- `methodology.md` — priority model, GitOps rule, two-layer infrastructure design
- `knowledge-graph.md` — knowledge graph schema and extraction pipeline design
- `platform-engineering/` — idpbuilder/CNOE setup and CI/CD workflow design
