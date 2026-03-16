# Control System Infrastructure

## What this is

The **management plane** for the CIM-AI project. This is the toolchain that runs GitOps — not the application being managed.

| Component | Role | Managed by |
|---|---|---|
| **idpbuilder** | Bootstraps the control plane (kind cluster + ArgoCD + Gitea) | CNOE CLI |
| **Gitea** | In-cluster Git server + built-in OCI container registry | ArgoCD |
| **Gitea Actions runner** | CI execution — in-cluster, Docker-in-Docker | ArgoCD (`gitea-runner` package) |
| **platform-workflows** | Propagates security workflows to all repos | ArgoCD (`platform-workflows` package) |
| **sandbox-environments** | ArgoCD infrastructure for PR-based sandbox envs | ArgoCD (`sandbox-environments` package) |
| **ArgoCD** | GitOps operator — syncs cluster state from Gitea | idpbuilder |

> **Not in this directory:** Target infrastructure (AWS EKS, ECR, VPC, IAM) is managed separately via Terraform. See `target-infrastructure/` when it exists.

---

## CNOE Stack Layout

```
cnoe-stack/
├── gitea-config/
│   └── override.yaml                    ← enables Gitea Actions (immutable after cluster create)
└── packages/
    ├── gitea-runner/                    ← in-cluster act_runner (DinD) — ArgoCD manages lifecycle
    │   ├── app.yaml                     ← ArgoCD Application (cnoe:// source)
    │   └── manifests/
    │       ├── namespace.yaml
    │       ├── serviceaccount.yaml
    │       ├── rbac.yaml                ← cross-ns RBAC to read gitea-credential
    │       ├── pvc.yaml                 ← persists runner registration across restarts
    │       └── deployment.yaml          ← act_runner + dind sidecar + auto-register init
    │
    ├── platform-workflows/              ← enforces security workflows in all Gitea repos
    │   ├── app.yaml
    │   └── manifests/
    │       ├── namespace.yaml
    │       ├── serviceaccount.yaml
    │       ├── rbac.yaml                ← cross-ns RBAC to read gitea-credential
    │       ├── configmap-workflows.yaml ← secret-scan.yaml + sandbox-lifecycle.yaml
    │       ├── configmap-script.yaml    ← sync shell script
    │       └── cronjob.yaml             ← runs every 15 min, installs workflows via Gitea API
    │
    └── sandbox-environments/            ← ArgoCD infra for ephemeral PR sandbox environments
        ├── app.yaml
        ├── README.md                    ← bootstrap steps for tokens (required after sync)
        └── manifests/
            ├── argocd-project.yaml      ← AppProject "sandbox" (scoped to sandbox-* namespaces)
            ├── argocd-setup-job.yaml    ← PostSync Job: configures sandbox-agent user + RBAC
            └── gitea-token-secret.yaml  ← placeholder Secret for ApplicationSet PR generator
```

---

## Bootstrap

### Prerequisites

- Docker Desktop running
- `idpbuilder` installed (`brew install cnoe-io/tap/idpbuilder` or from releases)
- `kubectl` installed

### Create the control plane

```bash
idpbuilder create \
  --use-path-routing \
  -c gitea:./control-system-infrastructure/cnoe-stack/gitea-config/override.yaml \
  -p ./control-system-infrastructure/cnoe-stack/packages/gitea-runner \
  -p ./control-system-infrastructure/cnoe-stack/packages/platform-workflows \
  -p ./control-system-infrastructure/cnoe-stack/packages/sandbox-environments
```

This single command:
1. Creates a kind cluster
2. Deploys ArgoCD, Gitea (with built-in OCI registry), and ingress-nginx
3. Enables Gitea Actions via the config override
4. Packages and pushes the three CNOE packages to Gitea repos
5. Creates ArgoCD Applications pointing at those repos
6. ArgoCD syncs: deploys the runner, the workflow enforcer, and the sandbox infrastructure

The **runner self-registers** with Gitea via an init container — no manual runner setup.

### Post-sync bootstrap (sandbox environments only)

After ArgoCD finishes syncing, run the steps in `cnoe-stack/packages/sandbox-environments/README.md` to:
1. Populate the `gitea-admin-token` Secret (Gitea API token for the ApplicationSet PR generator)
2. Generate the `sandbox-agent` ArgoCD API token
3. Store both as Gitea org secrets

### Get credentials

```bash
idpbuilder get secrets
```

---

## Service URLs (default idpbuilder)

| Service | URL |
|---|---|
| ArgoCD | https://cnoe.localtest.me:8443/argocd |
| Gitea | https://cnoe.localtest.me:8443/gitea |
| Container registry | `cnoe.localtest.me:8443` (OCI, via Gitea) |

---

## Teardown

```bash
kind delete cluster --name localdev
```

To force re-registration of the runner after a teardown (the PVC will be gone with the cluster):
No action needed — the kind cluster and all PVCs are deleted together. The runner will auto-register on the next `idpbuilder create`.
