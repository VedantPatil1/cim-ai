# Implementation Guide

Step-by-step configuration for each security control described in the [requirements overview](index.md).

---

## R1 — Agent Identity

### Option A: Fine-Grained PAT (Phase 1)

1. Create a dedicated GitHub machine account for each agent role (e.g., `cim-ci-agent`).
2. Log in as that account → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
3. Set:
   - **Resource owner**: the organisation or user owning the repos
   - **Repository access**: select specific repositories only
   - **Permissions**: grant only what the agent role requires (see table below)
   - **Expiration**: 90 days maximum

Minimum scopes per agent role:

| Agent Role | Repository Access | Permissions |
|---|---|---|
| Knowledge graph extractor | app-code repo (read only) | `contents:read`, `metadata:read` |
| CI pipeline agent | app-code repo | `contents:read`, `actions:write` |
| Deployment agent | gitops-manifests repo only | `contents:write`, `pull_requests:write` |
| Infrastructure agent | terraform repo only | `contents:write`, `pull_requests:write` |

Store the token as a repository or environment secret — never in code or workflow YAML.

---

### Option B: GitHub App (Phase 2, recommended when agentic layer is live)

1. Go to **Organisation Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Set:
   - **Webhook**: disable (not needed for agent access)
   - **Permissions**: grant only the permissions matching the agent's role (same set as PAT above, but selected from the app's permission page)
   - **Where can this GitHub App be installed?**: Only on this account
3. Install the app on the organisation and select only the specific repositories it needs.
4. In the agent's workflow or runtime, exchange the app's private key for a short-lived installation token:

```python
import jwt, time, requests

def get_installation_token(app_id: str, private_key: str, installation_id: str) -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": app_id}
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
        },
    )
    return resp.json()["token"]  # valid for 1 hour
```

Store only the private key and installation ID as secrets — never the token itself (it expires automatically).

---

### Option C: OIDC Workload Identity (for AWS/GCP/Azure operations)

For agents that need to call cloud APIs (e.g., running Terraform against AWS), eliminate stored cloud credentials entirely.

**AWS setup:**

1. In AWS IAM, create an OIDC identity provider:
   - Provider URL: `https://token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`

2. Create an IAM role with a trust policy scoped to your specific repository and branch:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:YOUR_ORG/YOUR_REPO:ref:refs/heads/main"
      }
    }
  }]
}
```

3. In the GitHub Actions workflow, request the OIDC token and assume the role:

```yaml
permissions:
  id-token: write   # required to request OIDC token
  contents: read

jobs:
  terraform:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@b47578312673ae6fa5b5096b330d9fbac3d116df
        with:
          role-to-assume: arn:aws:iam::ACCOUNT_ID:role/cim-terraform-agent
          aws-region: ap-south-1
```

No `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` secrets are stored anywhere.

---

## R2 — Least Privilege Access

### Repository Rulesets

1. Go to **Repository Settings → Rules → Rulesets → New ruleset → New branch ruleset**.
2. Set:
   - **Target branches**: `main`, `release/*`
   - **Bypass actors**: add only the specific users or apps that legitimately need to bypass (e.g., the release automation app); do not add admins
3. Enable rules:
   - Restrict creations
   - Restrict deletions
   - Require linear history (optional, keeps audit trail clean)
   - Restrict commit metadata (commit message pattern — see R4)
   - File path restriction (block direct commits to sensitive paths)

**File path restriction example** — prevent any direct commit (including from agents) to workflow definitions:

```
/.github/workflows/**
/.gitea/workflows/**
/terraform/**
```

Only changes via PR (which require review) can touch these paths.

### CODEOWNERS

Create `.github/CODEOWNERS` (or `.gitea/CODEOWNERS`):

```
# Default: all paths require platform team review
*                      @your-org/platform-team

# Terraform — additionally require infra team
/terraform/            @your-org/infra-team

# Workflow definitions — any CI change reviewed by platform team
/.github/workflows/    @your-org/platform-team
/.gitea/workflows/     @your-org/platform-team

# Kubernetes manifests
/manifests/            @your-org/platform-team

# Security policies (Kyverno)
/policies/             @your-org/security-team
```

CODEOWNERS only takes effect when **Require review from code owners** is enabled in the branch protection rule or ruleset.

---

## R3 — Human-in-the-Loop Gates

### Merge Gate: Repository Ruleset

Apply to all protected branches. In the ruleset, enable:

```
✅ Require a pull request before merging
   └─ Required approvals: 1
   └─ Dismiss stale pull request approvals when new commits are pushed
   └─ Require review from code owners
   └─ Require approval of the most recent reviewable push

✅ Require status checks to pass
   └─ Add the required CI check names (e.g., "build", "test", "lint")
   └─ Require branches to be up to date before merging

✅ Block force pushes
```

Key: in **Bypass actors**, do **not** add the AI agent identities. They can open PRs but cannot merge them.

### Deployment Gate: Environment Protection Rules

1. Go to **Repository Settings → Environments → New environment** → create `staging` and `production`.
2. For `production`:
   - Enable **Required reviewers** → add the human(s) who must approve deployments
   - Set **Wait timer** if desired (e.g., 5 minutes after PR merge before deploy runs)
   - Restrict deployments to the `main` branch only

3. In the workflow:

```yaml
jobs:
  deploy:
    environment: production   # job pauses here until a reviewer approves
    steps:
      - name: Apply Terraform
        env:
          AWS_ROLE: ${{ secrets.TERRAFORM_ROLE_ARN }}  # only injected after approval
```

The job will show as "waiting" in the GitHub Actions UI until a named reviewer clicks Approve.

---

## R4 — Audit Trail

### Signed Commits (Ruleset)

1. In the Repository Ruleset, enable **Require signed commits**.
2. Each agent's machine account must have a GPG or SSH signing key configured.

For a GitHub Actions workflow running as an agent:

```yaml
- name: Configure git signing
  run: |
    git config --global user.email "cim-deploy-agent@your-org.com"
    git config --global user.name "cim-deploy-agent"
    git config --global commit.gpgsign true
    echo "${{ secrets.AGENT_GPG_PRIVATE_KEY }}" | gpg --import
    git config --global user.signingkey ${{ secrets.AGENT_GPG_KEY_ID }}
```

### Commit Message Pattern (Ruleset)

In the Repository Ruleset, enable **Restrict commit metadata** with a required pattern:

```
^(feat|fix|chore|docs|ci|infra)\(.+\): .+\n\nAgent: .+\nTriggered-by: .+
```

This blocks any commit — from agents or humans — that does not include the agent identity and trigger fields. Adjust the regex to match your project's convention.

### Structured Agent Commit Format

Enforce this format in agent workflows:

```
chore(gitops): update api-service image to sha256:a1b2c3d4

Agent: cim-ci-agent[bot]
Triggered-by: Gitea Actions run #142 (commit abc1234)
Workflow: .gitea/workflows/build-and-update.yaml
```

For agent-created PRs, use a PR template (`.github/PULL_REQUEST_TEMPLATE/agent.md`):

```markdown
## Agent-Created Pull Request

- **Agent**: <!-- e.g., cim-deploy-agent -->
- **Triggered by**: <!-- workflow run URL -->
- **Change summary**: <!-- what changed and why -->
- **Affected paths**: <!-- list of modified files -->

---
> This PR was created automatically. Review all changes before merging.
```

Apply the `agent-created` label automatically in the workflow:

```yaml
- name: Create PR
  run: |
    gh pr create \
      --title "$PR_TITLE" \
      --body-file .github/PULL_REQUEST_TEMPLATE/agent.md \
      --label "agent-created" \
      --reviewer "@your-org/platform-team"
  env:
    GH_TOKEN: ${{ secrets.DEPLOY_AGENT_TOKEN }}
```

---

## R5 — Secret Protection

### Enable Push Protection

In **Repository Settings → Code security → Secret scanning**:

- Enable **Secret scanning**
- Enable **Push protection**

Push protection blocks a `git push` that contains a pattern matching a known secret (700+ provider patterns). The pusher must provide a reason to bypass — this bypass is recorded in the audit log.

### Environment Secrets

Avoid repository-level secrets for credentials that are environment-specific. Instead:

1. Go to **Repository Settings → Environments → [environment name] → Environment secrets**.
2. Add secrets there instead of under **Repository secrets**.
3. Combine with environment protection rules (see R3) so secrets are only injected after human approval.

| Secret type | Scope | When to use |
|---|---|---|
| Repository secret | All workflows in the repo | Non-environment-specific credentials (e.g., read-only API keys) |
| Environment secret | Workflows targeting that environment only | Cloud credentials, deployment keys |
| Organisation secret | All repos in the org (with allowlist) | Shared tooling credentials |

### Custom Secret Patterns

For project-specific secrets not covered by GitHub's built-in patterns:

1. Go to **Organisation/Repository Settings → Code security → Secret scanning → Custom patterns → New pattern**.
2. Define a regex matching your secret format, e.g.:

```
CIM_[A-Z0-9]{32}
```

---

## R6 — Supply Chain Integrity

### Action SHA Pinning

Replace mutable tags with commit SHAs in all workflow files:

```yaml
# Before (unsafe — tag can be moved)
- uses: actions/checkout@v4

# After (safe — SHA is immutable)
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
```

To automate SHA updates, add a Dependabot configuration:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    commit-message:
      prefix: "ci"
```

Dependabot will open PRs to update pinned SHAs when new versions are released.

### Dependency Review Action

Add to PRs that modify `package.json`, `go.mod`, `requirements.txt`, or `uv.lock`:

```yaml
name: Dependency Review
on: [pull_request]

permissions:
  contents: read
  pull-requests: write

jobs:
  dependency-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
      - uses: actions/dependency-review-action@67d4f4bf7a7bfc3d8f88a0e6eff9f9e9f8f8a1b2
        with:
          fail-on-severity: moderate
```

This blocks merging a PR that introduces a dependency with a CVE of moderate severity or above.

### Required Workflows (Org-level, GitHub Teams/Enterprise)

If operating at org scale, enforce a security scanning workflow across all repositories:

1. Create a `.github` repository in the organisation.
2. Add a workflow file to it.
3. In **Organisation Settings → Code and automation → Actions → Required workflows**, add the workflow.

This workflow will run on every PR in every repo in the organisation and cannot be disabled by repo admins. Useful for enforcing the dependency review or container image signing checks uniformly.
