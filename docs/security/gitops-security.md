# GitOps Security Model

This page covers the security controls applied to the GitOps repositories (`sample-backend-app` and `sample-backend-gitops`). It documents who can do what, how the merge gate is enforced, and demonstrates why each control is necessary through a concrete attack scenario.

---

## Users and Roles

Two distinct identities operate against the repositories. They map directly to the agentic system's trust model: one identity that acts, one that authorises.

| User | Role | Gitea permission | What they represent |
|---|---|---|---|
| `dev-agent` | AI agent / developer | `write` | Any automated or human actor proposing changes |
| `admin-human` | Platform reviewer | `admin` | The human-in-the-loop gate — must approve before anything merges |
| `giteaAdmin` | System / CI bot | owner | CI pipeline automation (image tag pushes, platform-workflows CronJob) |

### What each identity can do

=== "`dev-agent`"

    | Action | Allowed |
    |---|---|
    | Push a feature branch | Yes |
    | Open a pull request | Yes |
    | Approve own PR | **No** — Gitea blocks self-approval |
    | Merge without `admin-human` approval | **No** — approvals whitelist enforced |
    | Merge with `admin-human` approval but CI failing | **No** — required status checks enforced |
    | Push directly to `main` | **No** — branch protection blocks all non-whitelisted pushes |
    | Merge PR touching `.gitea/workflows/` | **No** — `protected_file_patterns` blocks merge |

=== "`admin-human`"

    | Action | Allowed |
    |---|---|
    | Approve any PR | Yes — approval recorded as `official: True` |
    | Reject a PR | Yes — hard-blocks merge until dismissed |
    | Merge an approved PR | Yes |
    | Push directly to `main` | Yes — whitelisted for emergency operations |
    | Modify branch protection settings | Yes — admin repo access |

=== "`giteaAdmin` (CI bot)"

    | Action | Allowed |
    |---|---|
    | Push image tag updates to `sample-backend-gitops` main | Yes — whitelisted for automated CI writes |
    | Push directly to `sample-backend-app` main | **No** — no whitelist on app repo |
    | Approve own PRs | **No** — self-approval blocked system-wide |

---

## Branch Protection

Both repos share the same policy on `main`:

| Control | Value |
|---|---|
| Direct push | Blocked — `giteaAdmin` whitelisted on gitops repo only |
| Required approvals | 1 |
| Approvals whitelist | `admin-human` only — no other approval counts |
| Dismiss stale approvals | Enabled — new commits void existing approval |
| Block on rejected review | Enabled — `admin-human` rejection hard-blocks merge |
| Block on outdated branch | Enabled — branch must be up to date before merge |
| Required status checks | `Secret Scanning / Detect secrets with gitleaks` |
| Protected file patterns | `.gitea/workflows/*` |
| CODEOWNERS | `/.gitea/workflows/ @giteaAdmin` |

### Merge requirements

A PR can only merge when all four conditions are simultaneously true:

```
1. admin-human has given an official APPROVED review
2. No subsequent commits have invalidated that approval
3. Secret Scanning / gitleaks check has passed on the PR head
4. PR does not touch .gitea/workflows/*
```

---

## Verified Behaviour

Every scenario below was tested and confirmed against the live Gitea instance:

| Scenario | Outcome |
|---|---|
| `dev-agent` pushes directly to `main` | Blocked — `pre-receive hook declined` |
| `dev-agent` self-approves own PR | Blocked — `approve your own pull is not allowed` |
| `dev-agent` merges without any approval | Blocked — `Not enough approvals` |
| `dev-agent` opens PR modifying `.gitea/workflows/` | CI runs tampered workflow and **passes**, merge blocked by `protected_file_patterns` |
| `admin-human` approves PR | Approval recorded as `official: True` |
| `dev-agent` merges after `admin-human` approves + CI passes | **Permitted** — all gates satisfied |
| New route added via PR → merged → ArgoCD synced | New endpoint live within 60s, zero manual steps |

---

## Attack Scenario: Disabling the Secret Scan

This section demonstrates why `protected_file_patterns` and the approvals whitelist are necessary, not optional.

### The attack

An agent wants to commit a hardcoded secret (API key) to `main` without the gitleaks check blocking it.

```
Step 1  Open a PR branch that:
          (a) replaces .gitea/workflows/secret-scan.yaml with exit 0
          (b) adds a file containing the actual secret

Step 2  Push branch → Gitea Actions triggers CI on the PR

Step 3  CI runs secret-scan.yaml from the PR branch
          → neutered workflow exits 0
          → "Secret Scanning" status check: ✅ passed

Step 4  All required status checks pass
          → without further controls, PR is mergeable

Step 5  Secret lands on main
          CronJob restores secret-scan.yaml 15 minutes later — too late
```

The neutered workflow:

```yaml
name: Secret Scanning
on:
  push:
  pull_request:
jobs:
  gitleaks:
    name: Detect secrets with gitleaks
    runs-on: ubuntu-latest
    steps:
      - run: echo "scan skipped"   # exits 0; gitleaks never runs
```

### Why the CronJob does not stop this

The `platform-workflows` CronJob restores `secret-scan.yaml` to `main` every 15 minutes. This is an **availability** control — it ensures the workflow exists on `main`. It is not an **integrity** control. Gitea Actions runs CI workflows from the **PR branch context**, not from `main`. The CronJob cannot intervene in what the PR branch runs.

```
T+0    Agent opens PR (tampered secret-scan.yaml + secret in file)
T+1    CI runs PR branch's secret-scan.yaml → exits 0 ✅
T+2    Status check passes
T+3    PR merges
T+15   CronJob restores secret-scan.yaml to main
         → credential already in git history
```

### Root cause

A safety constraint that exists only as a file in a system the agent can write to provides no safety guarantee against that agent. The gitleaks check is only as strong as the integrity of the workflow file that runs it.

This is the same failure mode as the Replit incident: the constraint existed only as data — the agent modified the data.

### How the current controls stop it

**`protected_file_patterns: .gitea/workflows/*`**
Any PR touching workflow files cannot be merged to `main` — even if all CI checks pass and approvals are in place. The merge push is rejected at the git level.

**`admin-human` approvals whitelist**
Only `admin-human`'s review counts as official. `dev-agent` cannot self-approve. A human reviewing the PR diff sees `echo "scan skipped"` replacing a gitleaks invocation and rejects it.

**Combined defence-in-depth:**

```
dev-agent opens tampered PR
        │
        ▼
CI runs neutered workflow → secret-scan: ✅ passed
        │ (attack has bypassed CI at this point)
        ▼
Merge attempt
  → .gitea/workflows/* in diff?
  → YES → protected_file_patterns blocks merge         ← Hard gate (D1)
        │
  Even if D1 were absent:
        ▼
  admin-human reviews diff
  → sees echo "scan skipped"
  → rejects PR → merge hard-blocked                    ← HITL gate (D2)
```

### Remaining gaps

| Defence | Status |
|---|---|
| `protected_file_patterns: .gitea/workflows/*` | **Live** |
| CODEOWNERS `/.gitea/workflows/ @giteaAdmin` | **Live** |
| `admin-human` approvals whitelist | **Live** |
| External webhook-based scanner (independent of repo workflows) | Pending |
| Workflow checksum verification in platform-workflows CronJob | Pending |

---

## Mapping to R1–R6

| Requirement | Control in this model |
|---|---|
| **R1 — Agent identity** | `dev-agent` and `admin-human` are separate credentials. A compromised `dev-agent` token cannot approve or merge its own changes. |
| **R2 — Least privilege** | `dev-agent` has `write` access only — cannot modify branch protection, manage collaborators, or push to protected branches. |
| **R3 — HITL gates** | `admin-human` approval is mechanically required via the approvals whitelist. Cannot be bypassed by the agent reasoning differently or retrying. |
| **R4 — Audit trail** | Every PR, approval, and merge is recorded in Gitea's event log with actor, timestamp, and commit SHA. |
| **R5 — Secret protection** | gitleaks runs on every push and PR. Tampered workflow is blocked from merging by `protected_file_patterns` before it can disable the scan. |
| **R6 — Supply chain** | CI workflow files are protected from modification by `protected_file_patterns` + CODEOWNERS. The pipeline definition is treated as policy — same review requirements as infrastructure changes. |
