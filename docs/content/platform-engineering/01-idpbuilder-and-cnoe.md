# idpbuilder and the CNOE Ecosystem

## What is idpbuilder?

idpbuilder is a CLI tool by CNOE (Cloud Native Operational Excellence) that bootstraps a complete Internal Developer Platform (IDP) locally with Docker as the only dependency.

**It solves the bootstrapping problem:** setting up a GitOps-based IDP normally requires manually wiring together a Kubernetes cluster, a Git server, a GitOps controller, ingress, TLS, and DNS. idpbuilder does all of this in a single command.

```bash
idpbuilder create
```

### What gets deployed

| Component     | Purpose                            | Namespace     |
|---------------|------------------------------------|---------------|
| kind cluster  | Local Kubernetes                   | —             |
| ingress-nginx | Route external traffic in          | ingress-nginx |
| ArgoCD        | GitOps deployment engine           | argocd        |
| Gitea         | In-cluster Git server              | gitea         |

### How it works internally

1. **Cluster creation** — kind cluster is created. TLS cert generated for the host (default: `cnoe.localtest.me`). Port 8443 on host → port 443 on kind node → ingress-nginx.

2. **Bootstrap** — manifests for ArgoCD, Gitea, and ingress-nginx are baked into the idpbuilder binary. They are applied directly to the cluster.

3. **GitOps handoff** — idpbuilder pushes those same manifests into Gitea repos via `go-git`, then creates ArgoCD Applications pointing at those repos. From this point, ArgoCD owns the lifecycle of everything.

4. **Custom package processing** — idpbuilder scans your custom packages for `cnoe://` URLs, pushes those local directories into new Gitea repos, rewrites the `repoURL` to the real internal Gitea URL, and ArgoCD syncs from there.

### The `cnoe://` protocol

This is the key concept. In an ArgoCD Application manifest:

```yaml
source:
  repoURL: cnoe://manifests   # relative path from the app.yaml location
  targetRevision: HEAD
  path: "."
```

idpbuilder resolves this to `./manifests/` on disk, pushes it to a new Gitea repo, and rewrites `repoURL` to the actual Gitea URL. ArgoCD then syncs from Gitea normally.

---

## Package and Stack Structure

A **package** is a directory containing:
- One or more ArgoCD `Application` or `ApplicationSet` YAML files
- Subdirectories with Kubernetes manifests

A **stack** is a collection of packages.

```
my-stack/
  app.yaml              ← ArgoCD Application (uses cnoe:// or remote URL)
  manifests/
    deployment.yaml
    service.yaml
```

### Adding packages to idpbuilder

```bash
# At cluster creation — local directory
idpbuilder create -p ./my-package

# At cluster creation — remote git URL
idpbuilder create -p https://github.com/cnoe-io/stacks//ref-implementation

# Multiple packages
idpbuilder create \
  -p ./cnoe-infra/local-registry \
  -p ./cnoe-infra/gitea-runner \
  -p ./cnoe-infra/sample-app-gitops
```

> **Note:** `cnoe://` URL rewriting only happens at `idpbuilder create` time.
> Post-creation packages applied via `kubectl apply` must point to already-populated Gitea repos or remote sources.

### Overriding core packages

Core packages (ArgoCD, Gitea, nginx) can only be customized at cluster creation time using `-c`:

```bash
idpbuilder create -c gitea:./my-gitea-override.yaml
```

The override YAML replaces matching Kubernetes resources (matched by `kind` + `name`) in the baked manifests. This is how you enable Gitea Actions, change resource limits, etc.

**This is immutable after cluster creation.** Changing it requires recreating the cluster.

---

## CAIPE (Community AI Platform Engineering)

CAIPE is the AI agent layer that sits on top of idpbuilder. It is a Multi-Agent System (MAS) designed for platform engineering operations.

- Pronounced "cape"
- Championed by the CNOE forum
- Lives at `github.com/cnoe-io/ai-platform-engineering`
- Available as an idpbuilder stack at `cnoe-io/stacks//caipe/`

### Architecture

```
User / Backstage UI
        ↓
  Supervisor Agent        ← orchestrates sub-agents
        ↓
  ┌─────┬─────┬──────┬────────┬───────┐
  ArgoCD GitHub Jira  Slack   AWS    Backstage
  Agent  Agent Agent  Agent   Agent  Agent
        ↓ (MCP protocol)
  Platform APIs (ArgoCD, GitHub, Jira, etc.)
```

- **MCP (Model Context Protocol)** — each sub-agent connects to platform APIs via MCP servers (tools layer)
- **A2A (Agent-to-Agent)** — agents communicate across environments via Google's A2A protocol
- **Agentgateway** — enterprise transport layer for routing A2A traffic with OAuth identity
- **LLM backends** — supports OpenAI, Anthropic Claude, Azure OpenAI

### Deployment variants

| Variant                    | Description                              |
|----------------------------|------------------------------------------|
| `caipe/base`               | Minimal — core supervisor + ArgoCD agent |
| `caipe/complete`           | All agents enabled                       |
| `caipe/complete-slim`      | Lightweight version                      |
| `caipe/workshop`           | Educational setup (ArgoCD + Backstage + GitHub) |
| `caipe/caipe-complete-agentgateway` | Full stack with AgentGateway    |

### Relation to cim-ai

CAIPE is the reference implementation. `cim-ai` (this project) extends or builds upon this pattern for cloud infrastructure management automation. CAIPE is the upstream to understand; `cim-ai` is the custom dissertation layer on top.

---

## Key URLs (default idpbuilder setup)

| Service      | URL                                              |
|--------------|--------------------------------------------------|
| ArgoCD       | https://cnoe.localtest.me:8443/argocd            |
| Gitea        | https://cnoe.localtest.me:8443/gitea             |
| Backstage    | https://cnoe.localtest.me:8443                   |
| Argo Workflows | https://cnoe.localtest.me:8443/argo-workflows  |
| Keycloak     | https://cnoe.localtest.me:8443/keycloak          |

Credentials: `idpbuilder get secrets`
