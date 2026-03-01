# Manual Setup: Gitea Actions + Runner

> **Purpose:** Walk through the setup manually to understand the operations before implementing as an idpbuilder stack.
> Each step here maps to a future stack component.

---

## Step 1 — Enable Gitea Actions via Admin UI

Gitea Actions is disabled by default in the idpbuilder Gitea install (`ENABLED = false` in app.ini).

> **Note:** Gitea's admin panel can toggle Actions at runtime without requiring an app.ini restart in newer versions. Try the UI first. If it doesn't stick across restarts, the proper fix is a cluster rebuild with a `-c gitea:` override.

1. Open Gitea: https://cnoe.localtest.me:8443/gitea
2. Log in as admin (get credentials with `idpbuilder get secrets`)
3. Navigate to **Site Administration** → **Configuration** (top right avatar → Admin Panel → Configuration)
4. Search for **Actions** section
5. Toggle **Enable Actions**
6. Save

**What this maps to as a stack:**
```yaml
# cnoe-infra/gitea-config/override.yaml
# Overrides the baked Gitea ConfigMap to set ENABLED=true
# Applied via: idpbuilder create -c gitea:./cnoe-infra/gitea-config/override.yaml
```

---

## Step 2 — Create the GitOps Repo in Gitea

1. In Gitea, click **+** → **New Repository**
2. Owner: `giteaAdmin`
3. Name: `sample-backend-gitops`
4. Visibility: Public (ArgoCD needs to read it)
5. Initialize with README: yes
6. Click **Create Repository**

**What this maps to as a stack:**
The gitops repo contents will be pushed via `cnoe://` protocol when packaged as an idpbuilder stack. ArgoCD's Application manifest will reference the internal Gitea URL.

---

## Step 3 — Set up the Local Container Registry

These commands run on your Mac (the host), not inside the cluster.

```bash
# 1. Start registry container
docker run -d \
  -p 5000:5000 \
  --name kind-registry \
  --restart=always \
  registry:2

# 2. Connect it to the kind Docker network
#    This lets the kind node reach it as kind-registry:5000
docker network connect kind kind-registry

# 3. Configure containerd on the kind node to trust it
docker exec localdev-control-plane bash -c "
cat > /etc/containerd/certs.d/kind-registry:5000/hosts.toml << 'EOF'
[host.\"http://kind-registry:5000\"]
  capabilities = [\"pull\", \"resolve\"]
  skip_verify = true
EOF
"

# 4. Restart containerd on the kind node
docker exec localdev-control-plane systemctl restart containerd
```

**Verify:**
```bash
# Push a test image from host
docker pull alpine:3.18
docker tag alpine:3.18 localhost:5000/test:latest
docker push localhost:5000/test:latest

# Verify pull from inside cluster
kubectl run test-pull --image=kind-registry:5000/test:latest --restart=Never
kubectl get pod test-pull
kubectl delete pod test-pull
```

**What this maps to as a stack:**
The registry container and containerd config become a package. The containerd config is a DaemonSet or init Job that patches the kind node. This is the trickiest part to automate.

---

## Step 4 — Get a Gitea Runner Registration Token

The runner needs a token to register itself with Gitea.

1. In Gitea, go to **Site Administration** → **Actions** → **Runners**
2. Click **Create new Runner**
3. Copy the registration token shown

Or via API:
```bash
GITEA_PASS=$(kubectl get secret -n gitea gitea-credential -o jsonpath='{.data.password}' | base64 -d)
curl -sk -u "giteaAdmin:${GITEA_PASS}" \
  https://cnoe.localtest.me:8443/gitea/api/v1/admin/runners/registration-token \
  | jq -r '.token'
```

---

## Step 5 — Run the Gitea Actions Runner

Run `act_runner` as a Docker container on your Mac.

```bash
# Pull the runner image
docker pull gitea/act_runner:latest

# Create a config directory
mkdir -p ~/.gitea-runner

# Register the runner (one-time step, saves config to ~/.gitea-runner/config.yaml)
docker run --rm \
  -v ~/.gitea-runner:/data \
  -e GITEA_INSTANCE_URL=https://cnoe.localtest.me:8443/gitea \
  -e GITEA_RUNNER_REGISTRATION_TOKEN=<TOKEN_FROM_STEP_4> \
  -e GITEA_RUNNER_NAME=local-runner \
  gitea/act_runner:latest \
  act_runner register \
    --no-interactive \
    --instance https://cnoe.localtest.me:8443/gitea \
    --token <TOKEN_FROM_STEP_4> \
    --name local-runner \
    --labels ubuntu-latest:docker://node:16-bullseye

# Start the runner (persistent)
docker run -d \
  --name gitea-runner \
  --restart=always \
  -v ~/.gitea-runner:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e GITEA_INSTANCE_URL=https://cnoe.localtest.me:8443/gitea \
  --network host \
  gitea/act_runner:latest
```

> The `-v /var/run/docker.sock:/var/run/docker.sock` mount gives the runner Docker access so it can build and push images.
> `--network host` lets it reach `localhost:5000` (kind-registry) for pushes.

**Verify the runner is registered:**
Gitea → Site Administration → Actions → Runners — the runner should appear as Online.

**What this maps to as a stack:**
The runner becomes a Kubernetes Deployment inside the cluster (using Docker-in-Docker or Kaniko), registered via an init container that calls the Gitea API. The registration token is stored as a Kubernetes Secret.

---

## Step 6 — Push the App Repo to Gitea

The `sample-backend-api-app` currently lives locally. Push it to your Gitea instance.

```bash
cd /Users/vedantpatil/projects/bits/4-sem-dissertation/sample-backend-api-app

# Add Gitea as remote (get password from idpbuilder get secrets)
git remote add gitea https://cnoe.localtest.me:8443/gitea/giteaAdmin/sample-backend-api-app.git

# Create the repo in Gitea first (UI or API), then push
git push gitea main
```

Or create the repo via API:
```bash
GITEA_PASS=$(kubectl get secret -n gitea gitea-credential -o jsonpath='{.data.password}' | base64 -d)
curl -sk -u "giteaAdmin:${GITEA_PASS}" \
  -X POST https://cnoe.localtest.me:8443/gitea/api/v1/user/repos \
  -H 'Content-Type: application/json' \
  -d '{"name":"sample-backend-api-app","private":false,"auto_init":false}'
```

---

## Step 7 — Add CI Workflow to App Repo

Create `.gitea/workflows/ci.yaml` in the app repo.

```yaml
# .gitea/workflows/ci.yaml
name: Build and Deploy

on:
  push:
    branches: [main]

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Build image
        run: |
          IMAGE=kind-registry:5000/sample-backend-api:${{ github.sha }}
          docker build -f Dockerfile.python -t $IMAGE .
          docker push $IMAGE

      - name: Update gitops repo
        env:
          GITEA_TOKEN: ${{ secrets.GITEA_TOKEN }}
        run: |
          IMAGE_TAG=${{ github.sha }}
          git clone https://giteaAdmin:${GITEA_TOKEN}@cnoe.localtest.me:8443/gitea/giteaAdmin/sample-backend-gitops.git
          cd sample-backend-gitops
          # Update image tag in deployment.yaml
          sed -i "s|image: kind-registry:5000/sample-backend-api:.*|image: kind-registry:5000/sample-backend-api:${IMAGE_TAG}|" manifests/deployment.yaml
          git config user.email "ci@idp.local"
          git config user.name "CI Runner"
          git add manifests/deployment.yaml
          git commit -m "ci: update image to ${IMAGE_TAG}"
          git push
```

**Add GITEA_TOKEN secret:**
Gitea → User Settings → Applications → Generate token → copy
Then in the `sample-backend-api-app` repo: Settings → Secrets → Add secret → `GITEA_TOKEN`

---

## Step 8 — Create ArgoCD Application

Apply this to the cluster:

```bash
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: sample-backend-api
  namespace: argocd
spec:
  destination:
    namespace: sample-backend-api
    server: https://kubernetes.default.svc
  project: default
  source:
    repoURL: http://my-gitea-http.gitea.svc.cluster.local:3000/giteaAdmin/sample-backend-gitops.git
    targetRevision: HEAD
    path: manifests
  syncPolicy:
    automated:
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
EOF
```

Verify in ArgoCD UI: https://cnoe.localtest.me:8443/argocd

---

## Mapping to idpbuilder Stack (Summary)

| Manual step | Stack component |
|---|---|
| Enable Gitea Actions (admin UI) | `-c gitea:cnoe-infra/gitea-config/override.yaml` |
| Create gitops repo | `cnoe://manifests` in package, idpbuilder creates Gitea repo |
| Start kind-registry | `cnoe-infra/local-registry/` package (Job + containerd patch) |
| Register + run act_runner | `cnoe-infra/gitea-runner/` package (Deployment + init container) |
| Push app repo to Gitea | Developer workflow (not automated by platform) |
| Add CI workflow | Part of app repo — developer owned |
| Create ArgoCD Application | `cnoe-infra/sample-app-gitops/app.yaml` package |
