# Security for AI Agent Repository Access

This section defines the security requirements for granting AI agents access to Git repositories, maps each requirement to available implementation approaches, and classifies how each approach is enforced.

The underlying principle is identical to the project's [priority model](../methodology.md#1-priority-model-security--reliability--capability): security constraints must be mechanically enforced, not instructed. An agent cannot be told to behave securely — the controls must make unsafe behaviour impossible or immediately visible.

---

## Requirements

Six distinct security requirements govern how AI agents interact with repositories. Each one has multiple implementation options, described in detail in the [implementation guide](implementation.md).

| # | Requirement | What it prevents |
|---|---|---|
| **R1** | Agent identity isolation | One compromised credential exposes all agent operations |
| **R2** | Least privilege access | Agent performs operations outside its designated scope |
| **R3** | Human-in-the-loop (HITL) gates | Agent merges or deploys without human review |
| **R4** | Audit trail | Agent actions cannot be traced or attributed after the fact |
| **R5** | Secret protection | Credentials committed to or leaked from the repository |
| **R6** | Supply chain integrity | Compromised CI dependencies execute arbitrary code |

---

## Enforcement Classification

Controls range from **hard** (the action is mechanically blocked) to **soft** (the action is recorded or alerted on after the fact). Hard controls are preferred; soft controls are supplementary.

| Control | Type | Hardness | Can it be bypassed? |
|---|---|---|---|
| Fine-grained PAT / GitHub App token scoping | R1, R2 | **Hard** | No — missing scope = denied |
| OIDC workload identity (no stored secret) | R1, R2 | **Hard** | No — token issued per-workflow |
| Repository Rulesets | R2, R3 | **Hard** | Only by explicitly named bypass actors |
| Branch protection (classic) | R3 | **Hard** | Admin bypass exists unless explicitly disabled |
| Environment protection rules | R3 | **Hard** | Only if environment is not misconfigured |
| Required status checks | R3, R6 | **Hard** | Must pass before merge is allowed |
| Push protection (secret scanning) | R5 | **Hard** | Can bypass with a stated reason — audited |
| CODEOWNERS required review | R2, R3 | **Medium** | Dismissible unless combined with branch protection |
| Signed commits (ruleset-enforced) | R4 | **Hard** | No — ruleset blocks unsigned commits |
| Commit message pattern (ruleset) | R4 | **Hard** | No — merge blocked if pattern not matched |
| GitHub audit log / streaming | R4 | **Soft** | Retrospective — records but does not block |
| Secret scanning alerts | R5 | **Soft** | Retrospective — alerts after push |
| Action SHA pinning | R6 | **Soft** | Convention only unless enforced by required workflow |
| OpenSSF Scorecard | R6 | **Soft** | Informational unless score gated in CI |

---

## Implementation Approaches by Requirement

### R1 — Agent Identity

Three approaches, ordered from simplest to most robust:

```
Fine-grained PAT  →  GitHub App  →  OIDC Workload Identity
   (simplest)         (preferred)      (no stored secret)
```

- **Fine-grained PATs** are scoped to specific repositories and permission types. They are long-lived (up to 1 year) and require disciplined rotation.
- **GitHub Apps** issue short-lived installation tokens (1 hour), rotate automatically, and appear as a named app identity in the audit log — not as a user. Preferred for any persistent agent.
- **OIDC federation** eliminates stored credentials entirely. The workflow requests a token from GitHub's OIDC provider; AWS/GCP/Azure exchange it for a scoped cloud credential. No secret is ever stored.

### R2 — Least Privilege

Three layers, applied together:

- **Token / App scoping** — resource-type and repository-level permissions on the credential itself (hard boundary)
- **Repository Rulesets** — define which actors can bypass which rules; everyone else is blocked
- **CODEOWNERS** — path-level human review requirement, regardless of who opened the PR

### R3 — HITL Gates

Two distinct gate points:

- **Merge gates** — Repository Rulesets or branch protection require a PR with an approved review before any branch can be merged. This is where agent-proposed code changes are reviewed.
- **Deployment gates** — Environment protection rules require a named human to manually approve a workflow job before it runs. Secrets for that environment are not injected until approval is given.

### R4 — Audit Trail

Three complementary layers:

- **GitHub / Gitea Audit Log** — organisation-level event stream (retrospective)
- **Signed commits** — cryptographically links a commit to a verified identity; enforceable via ruleset
- **Structured commit messages and PR descriptions** — agent identity, triggering event, and workflow run ID embedded in every agent action; enforceable via ruleset commit message pattern

### R5 — Secret Protection

Two layers:

- **Push protection** (hard) — blocks a push containing a detected secret; a bypass requires a stated reason and creates an audit event
- **Environment secrets over repository secrets** — secrets are scoped to a specific deployment environment and are only injected after the environment's protection rules (including HITL approval) are satisfied

### R6 — Supply Chain Integrity

Three layers, ordered by enforcement hardness:

- **Required workflows** (org-level, GitHub Teams/Enterprise) — enforces that a security scanning workflow runs on every PR, regardless of repo-level configuration; cannot be bypassed by repo admins
- **Dependency Review action** — blocks PRs that introduce dependencies with known CVEs
- **Action SHA pinning** — pins third-party GitHub Actions to an immutable commit SHA, not a mutable tag; automated by tools like Renovate or Dependabot

---

## Decision: GitHub Apps vs Fine-Grained PATs

For this project, the choice between GitHub Apps and fine-grained PATs has the following trade-offs:

| Factor | Fine-grained PAT | GitHub App |
|---|---|---|
| Token lifetime | Up to 1 year (long-lived) | 1 hour (auto-rotated) |
| Setup complexity | Low — generate in UI | Higher — register app, handle installation |
| Audit visibility | Shows as a user | Shows as `app-name[bot]` — clearly machine identity |
| Per-repo scoping | Yes | Yes (installation-level selection) |
| Multi-repo agent | Separate PAT per repo or one broad PAT | Single app, installation per repo |
| Revocation | Per-token | Per-installation or per-app |

**Recommendation for this project:** Use fine-grained PATs for Phase 1 (low complexity, limited agents). Switch to GitHub Apps when the agentic layer is implemented and multiple agents operate across multiple repositories.

---

## Decision: Repository Rulesets vs Branch Protection Rules

GitHub now offers two mechanisms for protecting branches:

| Factor | Branch Protection Rules | Repository Rulesets |
|---|---|---|
| Scope | Per-branch, per-repo | Org-level or repo-level, multiple patterns |
| Bypass control | "Allow bypass for admins" checkbox | Named bypass actors (users, apps, roles) |
| Enforcement | Per-repo configuration | Can be applied across all repos from org level |
| File path restrictions | Not available | Available — block commits touching specific paths |
| Commit message enforcement | Not available | Available via regex pattern |
| Availability | All plans | All plans (org-level requires Teams/Enterprise) |

**Recommendation:** Use Repository Rulesets. They provide more precise bypass actor control (critical when agents have admin-equivalent credentials) and can enforce commit message format, which supports the audit trail requirement.

---

## Detailed Implementation

See [Implementation Guide](implementation.md) for step-by-step configuration of each control.
