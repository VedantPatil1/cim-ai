# CD Workflow Design

## Context

**Goal:** Simple Continuous Deployment workflow for `sample-backend-api-app` (FastAPI) using the local CNOE idpbuilder stack (Gitea + ArgoCD).

**Future state:** Same workflow but targeting AWS ECR (container registry) + EKS (Kubernetes). The local setup is designed so the AWS migration is a config swap, not a redesign.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     Gitea                           │
│                                                     │
│  sample-backend-api-app/    sample-backend-gitops/  │
│  (app code + CI workflow)   (K8s manifests)         │
└──────────────┬──────────────────────┬───────────────┘
               │ push triggers        │ ArgoCD watches
               ▼                      │
    ┌─────────────────────┐           │
    │   Gitea Actions     │           │
    │   (CI runner)       │           │
    │                     │           │
    │  1. build image     │           │
    │  2. push to registry│           │
    │  3. update image tag├───────────┘
    │     in gitops repo  │  commit image tag update
    └─────────────────────┘
               │
               ▼
    ┌─────────────────────┐
    │   Container Registry│
    │   (local: kind-     │
    │    registry:5000)   │
    └─────────────────────┘
               │ ArgoCD pulls manifest
               ▼
    ┌─────────────────────┐
    │       ArgoCD        │
    │                     │
    │  detects image tag  │
    │  change in gitops   │
    │  repo → syncs       │
    └─────────────────────┘
               │
               ▼
    ┌─────────────────────┐
    │   Kubernetes        │
    │   (kind cluster)    │
    │                     │
    │  rolling update of  │
    │  sample-backend-api │
    └─────────────────────┘
```

---

## Components

### 1. Two Gitea Repositories

| Repo | Contents | Who writes |
|------|----------|------------|
| `sample-backend-api-app` | FastAPI source code, Dockerfile, Gitea Actions workflow | Developer |
| `sample-backend-gitops` | Kubernetes manifests (Deployment, Service) | CI (automated) + human |

**Why separate repos?**
- Separation of concerns: app code changes vs deployment config changes
- ArgoCD watches the gitops repo only — no noise from code commits
- Mirrors real-world GitOps practice
- Easy to add environment overlays (dev/staging/prod) later via Kustomize

### 2. Container Registry

**Local:** `kind-registry` — a `registry:2` Docker container on the host, connected to the kind Docker network.

| Access point | Address |
|---|---|
| From host (push) | `localhost:5000` |
| From inside cluster (pull) | `kind-registry:5000` |

**Future AWS swap:**

| | Local | AWS |
|---|---|---|
| Registry | `kind-registry:5000` | `<account>.dkr.ecr.<region>.amazonaws.com` |
| Auth | none | IRSA / IAM role |
| Push from CI | `docker push localhost:5000/...` | `docker push <ecr-url>/...` |

### 3. Gitea Actions Runner

A `act_runner` instance registered with Gitea. Executes `.gitea/workflows/*.yaml` files.

**Local:** Run as a Docker container on the host machine.
- Has Docker socket access → can build and push images
- Reaches `localhost:5000` to push to kind-registry
- Reaches Gitea at `https://cnoe.localtest.me:8443/gitea`

### 4. CI Workflow (`.gitea/workflows/ci.yaml`)

Trigger: push to `main` branch of `sample-backend-api-app`

Steps:
1. Checkout code
2. Build Docker image → tag as `kind-registry:5000/sample-backend-api:<git-sha>`
3. Push image to registry
4. Clone `sample-backend-gitops` repo
5. Update `image:` field in `manifests/deployment.yaml` with new tag
6. Commit and push back to `sample-backend-gitops`

**Image tagging:** Git SHA (`sha-abc1234`) — immutable, ArgoCD always detects the diff.
Do NOT use `latest` — ArgoCD will not detect a change if the tag doesn't change.

### 5. GitOps Repo Structure

```
sample-backend-gitops/
  manifests/
    deployment.yaml       ← image tag updated by CI
    service.yaml
    kustomization.yaml
  argocd-app.yaml         ← ArgoCD Application manifest (optional, or apply manually)
```

### 6. ArgoCD Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: sample-backend-api
  namespace: argocd
spec:
  destination:
    namespace: sample-backend-api
    server: https://kubernetes.default.svc
  source:
    repoURL: http://my-gitea-http.gitea.svc.cluster.local:3000/giteaAdmin/sample-backend-gitops.git
    targetRevision: HEAD
    path: manifests
  syncPolicy:
    automated:
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

---

## What needs to be set up

In order of dependency:

1. **Enable Gitea Actions** — currently `ENABLED = false` in app.ini
2. **Local container registry** — `kind-registry:5000` does not exist yet
3. **Gitea Actions runner** — no runner registered
4. **`sample-backend-gitops` repo** — does not exist in Gitea yet
5. **Kubernetes manifests** — Deployment + Service for the app
6. **CI workflow** — `.gitea/workflows/ci.yaml` in app repo
7. **ArgoCD Application** — pointing at gitops repo

---

## Manual vs Stack approach

### Manual (current phase)
Do each step by hand through UIs and CLI. Purpose: understand the operations, validate the workflow, document the exact steps.

### As an idpbuilder stack (target)
Package all of the above into `cim-ai/cnoe-infra/` and express the cluster creation as a single reproducible command:

```bash
idpbuilder create \
  -c gitea:./cnoe-infra/gitea-config/override.yaml \   # enables Actions
  -p ./cnoe-infra/local-registry \                     # registry:2 + containerd config
  -p ./cnoe-infra/gitea-runner \                       # act_runner deployment
  -p ./cnoe-infra/sample-app-gitops                    # gitops repo + ArgoCD app
```

This single command recreates the entire setup from scratch. That is the reproducibility goal.

---

## Notes

- Gitea Actions is GitHub Actions-compatible — workflows use the same YAML syntax
- ArgoCD poll interval is set to 60s by idpbuilder (reduced from default 3min)
- The gitops repo must be accessible at the internal Gitea cluster URL for ArgoCD to sync
- CoreDNS rewrites `cnoe.localtest.me` → ingress-nginx inside the cluster
