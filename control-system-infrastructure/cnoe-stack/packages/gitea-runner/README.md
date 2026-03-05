# Gitea Actions Runner

The runner executes CI workflows (`.gitea/workflows/*.yaml`) defined in application repos.

It runs as a **host Docker container** rather than an in-cluster deployment. This gives it:
- Direct access to the Docker socket (needed for image builds)
- Native access to `localhost:5000` (the kind-registry) for image pushes
- No Docker-in-Docker complexity

The runner is not managed by ArgoCD. It is a one-time setup per developer environment.

For the full step-by-step setup, see:
[`docs/content/platform-engineering/03-manual-setup-gitea-actions.md`](../../../../docs/content/platform-engineering/03-manual-setup-gitea-actions.md) — Steps 4 and 5.

---

## Quick Reference

### 1. Get a registration token

```bash
GITEA_PASS=$(kubectl get secret -n gitea gitea-credential -o jsonpath='{.data.password}' | base64 -d)
curl -sk -u "giteaAdmin:${GITEA_PASS}" \
  https://cnoe.localtest.me:8443/gitea/api/v1/admin/runners/registration-token \
  | jq -r '.token'
```

### 2. Register the runner (one-time)

```bash
mkdir -p ~/.gitea-runner

docker run --rm \
  -v ~/.gitea-runner:/data \
  gitea/act_runner:latest \
  act_runner register \
    --no-interactive \
    --instance https://cnoe.localtest.me:8443/gitea \
    --token <TOKEN> \
    --name local-runner \
    --labels ubuntu-latest:docker://node:16-bullseye
```

### 3. Start the runner (persistent)

```bash
docker run -d \
  --name gitea-runner \
  --restart=always \
  -v ~/.gitea-runner:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e GITEA_INSTANCE_URL=https://cnoe.localtest.me:8443/gitea \
  --network host \
  gitea/act_runner:latest
```

### 4. Verify

Gitea → Site Administration → Actions → Runners — the runner should appear as **Online**.
