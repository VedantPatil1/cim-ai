# Secret Scanning: Platform-Enforced Pattern

## The Problem

Gitea has no built-in secret scanning. Without enforcement, developers (or AI agents writing code) can accidentally commit API keys, tokens, or passwords. A single leaked credential committed to a GitOps repo can compromise infrastructure that the repo controls.

The naive mitigation — "just don't commit secrets" — fails for two reasons:

1. It is a soft instruction, not a hard constraint. Agents cannot be reliably instructed to behave securely; controls must make unsafe behaviour mechanically difficult.
2. In a GitOps system, secrets committed to the repo immediately become visible to ArgoCD, CI runners, and anyone with repo read access.

---

## Design

### Tool: gitleaks

[gitleaks](https://github.com/gitleaks/gitleaks) scans git history and staged changes for known secret patterns (AWS keys, GitHub tokens, private keys, 150+ patterns). It returns exit code 1 if secrets are found, failing the workflow.

It runs as a Docker container inside the CI job — no installation required on the runner.

### Enforcement Model

The workflow (`secret-scan.yaml`) is **platform-enforced**: it is installed into every Gitea repository automatically by the `platform-workflows` CronJob. Repos cannot permanently remove it — the CronJob reinstalls it every 15 minutes.

```
platform-workflows CronJob (every 15 min)
        │
        ▼
Gitea API: list all repos
        │
        ▼
For each repo:
  ├── .gitea/workflows/secret-scan.yaml exists? → check if outdated → update if needed
  └── missing? → install from ConfigMap
```

This mirrors the GitHub org-level "required workflows" pattern, reimplemented for Gitea using the Gitea Contents API.

### Workflow Trigger

The workflow fires on every `push` (any branch) and every `pull_request` (open/synchronize/reopen):

```yaml
on:
  push:
    branches: ['**']
  pull_request:
    types: [opened, synchronize, reopened]
```

A failed secret scan blocks the CI status check. Combined with branch protection rules requiring status checks to pass before merging, this creates a hard gate: PRs with detected secrets cannot be merged.

---

## What Gets Scanned

gitleaks scans the **full git history** (`fetch-depth: 0`) from the point of the push, not just the diff. This catches secrets that were committed previously and not yet cleaned up.

The `--redact` flag replaces the detected secret value with `REDACTED` in the report output, so the SARIF report can be stored as a CI artifact without re-exposing the credential.

```
git history
    │
    ▼
gitleaks detect --source /repo
    │ matches against 150+ provider patterns
    │ (AWS, GitHub, Gitea, JWT, SSH, GCP, Azure, ...)
    ▼
exit 0 → workflow passes
exit 1 → workflow fails, PR blocked
```

---

## Operational Model

### Platform package

The `platform-workflows` CNOE package manages:

| Resource | Purpose |
|---|---|
| `CronJob: platform-workflow-sync` | Syncs workflow files to all repos every 15 min |
| `ConfigMap: platform-workflow-definitions` | Contains the workflow YAML files |
| `ConfigMap: platform-workflow-sync-script` | Shell script executed by the CronJob |
| RBAC (cross-namespace) | Allows reading `gitea-credential` Secret from `gitea` namespace |

### Triggering an immediate sync

```bash
kubectl create job -n platform-workflows \
  --from=cronjob/platform-workflow-sync \
  manual-sync-$(date +%s)
```

### Verifying installation in a repo

```bash
GITEA_PASS=$(kubectl get secret -n gitea gitea-credential -o jsonpath='{.data.password}' | base64 -d)
curl -sk -u "giteaAdmin:${GITEA_PASS}" \
  "https://cnoe.localtest.me:8443/gitea/api/v1/repos/giteaAdmin/sample-backend-gitops/contents/.gitea/workflows/secret-scan.yaml" \
  | grep '"name"'
```

---

## Limitations

**False positives.** gitleaks may flag test fixtures or mock credentials. Repos can add a `.gitleaks.toml` allowlist to suppress known false positives without disabling the scan entirely.

**Docker image availability.** The scan step pulls `zricethezav/gitleaks:latest` from Docker Hub. In an air-gapped environment, mirror this image to the local Gitea OCI registry and update the workflow image reference.

**History rewrite.** If a secret is detected in historical commits (not the current push), the workflow fails but the secret is already in git history. The correct fix is `git filter-repo` to rewrite history and immediate credential rotation — the scan alone cannot remediate a leaked secret, only detect it.

---

## Relationship to the Security Model

This control maps to **R5 (Secret Protection)** in the [security requirements](../security/index.md):

| Requirement | Implementation |
|---|---|
| R5 — prevent credentials committed to repo | gitleaks on push/PR — hard gate (blocks merge) |
| R4 — audit trail | Every gitleaks run is recorded in Gitea Actions history with commit SHA |
| R6 — supply chain | gitleaks image is pinned to a specific version in production (see note on `latest` tag) |

The platform-enforced installation model ensures this control applies even to repos that were created before the platform was set up, and to repos created in the future — without requiring per-repo configuration.
