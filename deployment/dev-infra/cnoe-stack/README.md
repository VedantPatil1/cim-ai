# CNOE dev-infra stack

Minimal local control plane, bootstrapped with [idpbuilder](https://cnoe.io/docs/idpbuilder):
Gitea (git server + OCI registry) + ArgoCD (GitOps) + nginx ingress, plus a
Gitea Actions runner (act_runner + Docker-in-Docker sidecar) as a custom
idpbuilder package.

## Prerequisites

- `idpbuilder` (wraps `kind` + `docker` internally) — `curl -fsSL https://raw.githubusercontent.com/cnoe-io/idpbuilder/main/hack/install.sh | bash`
- `docker`
- `kubectl` (only needed for checking pod status/logs, not for cluster lifecycle)

## Bootstrap

```bash
task dev-infra:up
```

which runs:

```bash
idpbuilder create \
  --recreate \
  --use-path-routing \
  -c gitea:./deployment/dev-infra/cnoe-stack/gitea-config/override.yaml \
  -p deployment/dev-infra/cnoe-stack/packages/gitea-runner
```

URLs after bootstrap:
- ArgoCD: https://cnoe.localtest.me:8443/argocd
- Gitea:  https://cnoe.localtest.me:8443/gitea

Get the Gitea admin credentials (regenerated on every `--recreate`):

```bash
task dev-infra:creds   # idpbuilder get secrets -p gitea
```

Tear down the cluster:

```bash
task dev-infra:down    # idpbuilder delete --name localdev
```

The `gitea-runner` package self-registers against Gitea on first boot (init
containers fetch the admin password, pull a registration token, and run
`act_runner register`). Check it came up:

```bash
kubectl -n gitea-runner logs deploy/gitea-runner -c register-runner
kubectl -n gitea-runner get pods
```

## Known tradeoffs

- The `dind` sidecar runs `privileged: true` — required for Docker-in-Docker,
  but it means any workflow step can escape to host root on the kind node.
  Acceptable for local dev; do not reuse this manifest for a shared cluster
  without swapping to a rootless builder (Kaniko/buildkit-rootless/sysbox).
- Gitea config (`gitea-config/override.yaml`) is immutable after cluster
  creation — idpbuilder's `-c` flag replaces the whole resource. To change it,
  rebuild: `task dev-infra:down && task dev-infra:up`.
- Crossplane and the MCP server from the `v1` branch are deliberately left out
  of this minimal stack — add them back as their own `packages/<name>/`
  directory only once there's a concrete use for them.
