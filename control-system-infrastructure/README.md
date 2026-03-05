# Control System Infrastructure

## What this is

The **management plane** for the CIM-AI project. This is the toolchain that runs GitOps — not the application being managed.

| Component | Role | Managed by |
|---|---|---|
| **idpbuilder** | Bootstraps the control plane (kind cluster + ArgoCD + Gitea) | CNOE CLI |
| **Gitea** | In-cluster Git server + built-in OCI container registry | ArgoCD |
| **Gitea Actions** | CI runner — builds images, updates GitOps repos | ArgoCD (runner registration is manual) |
| **ArgoCD** | GitOps operator — syncs cluster state from Gitea | idpbuilder |

> **Not in this directory:** Target infrastructure (AWS EKS, ECR, VPC, IAM) is managed separately via Terraform. See `target-infrastructure/` when it exists.

### On the container registry

idpbuilder's Gitea instance includes a built-in OCI-compliant container registry. idpbuilder also configures containerd on the kind node to trust it — no separate registry container or containerd patching needed.

Images are pushed to and pulled from:
```
cnoe.localtest.me:8443/giteaadmin/<image>:<tag>
```

---

## CNOE Stack Layout

```
cnoe-stack/
├── gitea-config/
│   └── override.yaml          ← enables Gitea Actions; overrides Secret my-gitea-inline-config via -c flag
└── packages/
    └── gitea-runner/          ← host Docker setup (not an ArgoCD-managed package)
```

---

## Bootstrap

### Create the control plane

```bash
idpbuilder create \
  --use-path-routing \
  -c gitea:./control-system-infrastructure/cnoe-stack/gitea-config/override.yaml
```

This single command:
1. Creates a kind cluster
2. Deploys ArgoCD, Gitea (with built-in OCI registry), and ingress-nginx
3. Configures containerd to trust the Gitea registry
4. Enables Gitea Actions via the config override

### Set up the Gitea Actions runner

The runner runs as a host Docker container. Follow the setup guide:
[`cnoe-stack/packages/gitea-runner/README.md`](cnoe-stack/packages/gitea-runner/README.md)

---

## Service URLs (default idpbuilder)

| Service | URL |
|---|---|
| ArgoCD | https://cnoe.localtest.me:8443/argocd |
| Gitea | https://cnoe.localtest.me:8443/gitea |
| Container registry | `cnoe.localtest.me:8443` (OCI, via Gitea) |

Credentials: `idpbuilder get secrets`

---

## Teardown

```bash
kind delete cluster --name localdev
```
