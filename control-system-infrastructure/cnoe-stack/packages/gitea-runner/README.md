# Gitea Actions Runner (in-cluster)

The runner is deployed as an **ArgoCD-managed in-cluster Deployment** — no manual setup required after `idpbuilder create`.

## Architecture

```
Pod: gitea-runner
├── init: get-gitea-creds    ← kubectl reads gitea-credential Secret → writes to emptyDir
├── init: register-runner    ← act_runner register (skips if PVC has config.yaml)
├── container: runner        ← act_runner daemon, waits for dind TLS certs
└── container: dind          ← Docker-in-Docker daemon (privileged), generates TLS certs
```

**Why DinD?** CI workflows need to build and push Docker images. The runner is inside a Kubernetes pod, so it uses Docker-in-Docker (a Docker daemon running inside the pod) rather than the host Docker socket. This keeps the runner fully in-cluster and ArgoCD-managed.

**Why a PVC?** `act_runner register` writes a `config.yaml` to `/data`. Without persistence, every pod restart triggers a new registration — eventually cluttering Gitea's runner list. The PVC persists the config across restarts so re-registration only happens after a full cluster teardown.

## Registered Labels

The runner registers with two labels:

| Label | Use |
|---|---|
| `ubuntu-latest` | Standard CI workflows (`runs-on: ubuntu-latest`) |
| `sandbox` | Reserved for sandbox management workflows |

## How Registration Works

1. `get-gitea-creds` init container: calls `kubectl get secret -n gitea gitea-credential` using the SA's cross-namespace RBAC grant. Writes the decoded password to a shared emptyDir.
2. `register-runner` init container: calls the Gitea API to obtain a registration token, then runs `act_runner register`. If `/data/config.yaml` already exists (PVC has prior registration), this step is skipped.
3. `runner` main container: waits for the dind sidecar to finish generating TLS certs, then starts `act_runner daemon`.

## Troubleshooting

**Runner appears Offline in Gitea:**
```bash
# Check runner pod status
kubectl get pods -n gitea-runner

# Check registration logs
kubectl logs -n gitea-runner <pod> -c register-runner

# Check runner daemon logs
kubectl logs -n gitea-runner <pod> -c runner
```

**Duplicate runners in Gitea after cluster rebuild:**
This is expected — old registration entries remain in Gitea after the cluster is deleted. They can be cleaned up from the Gitea admin panel: Site Administration → Actions → Runners.

**Force re-registration on a running cluster:**
```bash
# Delete the PVC — the next pod restart will trigger re-registration
kubectl delete pvc gitea-runner-data -n gitea-runner
kubectl rollout restart deployment/gitea-runner -n gitea-runner
```

## RBAC

The `gitea-runner` ServiceAccount has two RBAC grants:

1. **Role in `gitea` namespace** — read-only access to the `gitea-credential` Secret (password only)
2. **ClusterRole** — manage ArgoCD `ApplicationSet` resources (for sandbox-lifecycle workflows that create per-repo sandbox environments via the ArgoCD API)
