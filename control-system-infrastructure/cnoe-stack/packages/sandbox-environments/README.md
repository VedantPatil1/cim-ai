# Sandbox Environments Package

This package deploys the ArgoCD infrastructure for ephemeral AI sandbox environments.

## What it creates

| Resource | Namespace | Purpose |
|---|---|---|
| `AppProject: sandbox` | `argocd` | Constrains sandbox apps to `sandbox-*` namespaces |
| `Secret: gitea-admin-token` | `argocd` | Gitea API token for ApplicationSet PR generator (placeholder) |
| `Job: argocd-sandbox-setup` | `argocd` | PostSync — patches `argocd-cm` + `argocd-rbac-cm` to add `sandbox-agent` user |

## Bootstrap Steps (run after first cluster sync)

These steps must be done once after `idpbuilder create` and after ArgoCD has synced this package.

### Step 1 — Populate the Gitea token Secret

The ApplicationSet PR generator polls Gitea for open PRs. It authenticates with a Gitea API token.

```bash
# Get Gitea admin password
GITEA_PASS=$(kubectl get secret -n gitea gitea-credential \
  -o jsonpath='{.data.password}' | base64 -d)

# Create a Gitea token with read access to repos and issues
TOKEN=$(curl -sk \
  -u "giteaAdmin:${GITEA_PASS}" \
  -X POST "https://cnoe.localtest.me:8443/gitea/api/v1/users/giteaAdmin/tokens" \
  -H "Content-Type: application/json" \
  -d '{"name":"argocd-pr-reader","scopes":["read:repository","read:issue"]}' \
  | grep -o '"sha1":"[^"]*"' | cut -d'"' -f4)

# Overwrite the placeholder Secret
kubectl create secret generic gitea-admin-token -n argocd \
  --from-literal=token="$TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Gitea token stored in argocd/gitea-admin-token"
```

### Step 2 — Generate the ArgoCD sandbox-agent API token

The `sandbox-lifecycle.yaml` workflow calls the ArgoCD API to create ApplicationSets.
It authenticates using a token for the `sandbox-agent` local account.

```bash
# Get ArgoCD admin password
ARGOCD_PASS=$(kubectl get secret -n argocd argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d)

# Log in to ArgoCD CLI (or use the UI)
argocd login cnoe.localtest.me:8443 \
  --username admin \
  --password "${ARGOCD_PASS}" \
  --grpc-web \
  --insecure

# Generate an API token for sandbox-agent (no expiry for local dev)
SANDBOX_TOKEN=$(argocd account generate-token --account sandbox-agent)
echo "ArgoCD sandbox-agent token: ${SANDBOX_TOKEN}"
```

### Step 3 — Store the tokens as Gitea org secrets

The `sandbox-lifecycle.yaml` workflow reads `ARGOCD_SANDBOX_TOKEN` from Gitea.

```bash
GITEA_PASS=$(kubectl get secret -n gitea gitea-credential \
  -o jsonpath='{.data.password}' | base64 -d)

# Create org-level secret so all repos can use it
curl -sk \
  -u "giteaAdmin:${GITEA_PASS}" \
  -X PUT "https://cnoe.localtest.me:8443/gitea/api/v1/orgs/giteaAdmin/actions/secrets/ARGOCD_SANDBOX_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"data\":\"${SANDBOX_TOKEN}\"}"

echo "ARGOCD_SANDBOX_TOKEN stored as Gitea org secret"
```

---

## How the sandbox flow works end-to-end

```
1. Repo opts in by adding .cim/sandbox.yaml to its gitops repo
2. Push to main triggers sandbox-lifecycle.yaml (installed by platform-workflows)
3. Workflow calls ArgoCD API → creates ApplicationSet for this repo
4. Developer (or AI agent) opens a PR
5. ArgoCD ApplicationSet PR generator detects the PR via Gitea API
6. ArgoCD creates Application: sandbox-<repo>-pr-<number>
7. Application deploys PR branch manifests to namespace: sandbox-<repo>-pr-<number>
8. AI agent or test workflow validates changes in the sandbox
9. PR is merged or closed → ArgoCD prunes the Application and namespace
```

## Opt-in: .cim/sandbox.yaml

Create this file in the root of a gitops repo to activate sandbox environments:

```yaml
# .cim/sandbox.yaml
version: v1
sandbox:
  manifests_path: manifests    # path within the repo that ArgoCD should deploy
  ai_testing: true             # signal to AI agents that this sandbox is available
```

The sandbox-lifecycle workflow checks for the presence of this file. If absent, all sandbox steps are skipped (no-op).

## Security constraints

- Sandbox apps deploy **only** to namespaces matching `sandbox-*` (enforced by the `sandbox` AppProject)
- Cluster-scoped resources (except Namespace creation) are blocked
- The `sandbox-agent` ArgoCD user can only manage ApplicationSets — it cannot deploy, sync, or override other ArgoCD applications
- Sandbox namespaces are automatically pruned when PRs close (no manual cleanup needed)

## Troubleshooting

**ApplicationSet not creating sandbox apps:**
- Check that the `gitea-admin-token` Secret has a valid token (not `REPLACE_ME`)
- Verify `requeueAfterSeconds: 60` — the generator polls every 60s, not instantly

**sandbox-lifecycle workflow fails with 401:**
- The `ARGOCD_SANDBOX_TOKEN` org secret may be expired or missing
- Regenerate with: `argocd account generate-token --account sandbox-agent`

**Namespace not cleaned up after PR close:**
- Verify `syncPolicy.automated.prune: true` is set in the ApplicationSet template
- ArgoCD will clean up on the next reconciliation cycle
