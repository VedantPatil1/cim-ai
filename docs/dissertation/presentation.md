# Presentation: Secure Cloud Infrastructure Management with Agentic AI

---

## Slide 1 — Title

**Secure Cloud Infrastructure Management with Agentic AI**
*A GitOps-enforced architecture for autonomous operations*

Vedant Patil · 2024MT03034 · BITS Pilani M.Tech Dissertation · April 2026

---

## Slide 2 — The Problem

**Manual cloud operations are fragile and unauditable**

- Infrastructure changes made outside version control leave no audit trail
- Human error in CI/CD pipelines causes cascading failures
- AI agents given direct API access have unbounded blast radius
- *Real incident: Replit 2024 — infrastructure misconfiguration cascaded to data exposure*

**Core tension:** AI needs operational capability. Security needs hard constraints.

---

## Slide 3 — Research Question

> *How do we give AI agents the ability to operate cloud infrastructure autonomously — while guaranteeing they cannot bypass human oversight or tamper with their own controls?*

**Answer:** Make Git the enforcement layer, not a guideline.

---

## Slide 4 — Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                LAYER 1 — CONTROL SYSTEM                  │
│         (bootstrapped, not managed by Terraform)         │
│                                                          │
│   Gitea          Gitea Actions       ArgoCD              │
│   (Git + OCI)    (CI Runner)         (GitOps Operator)   │
│                                                          │
│              runs on kind (local) / EKS (prod)           │
└──────────────────────────┬──────────────────────────────┘
                           │  Every change flows through Git
┌──────────────────────────▼──────────────────────────────┐
│                LAYER 2 — TARGET INFRASTRUCTURE           │
│                                                          │
│   App Code        K8s Manifests       AWS / kind         │
│   (Gitea repo)    (GitOps repo)       (ArgoCD syncs)     │
│                                                          │
│         AI agents operate here — never in Layer 1        │
└─────────────────────────────────────────────────────────┘
```

---

## Slide 5 — The GitOps Rule

**Every change must flow through Git. No exceptions.**

```
Developer / AI Agent
        │
        │  git push (branch only, never main)
        ▼
    Gitea PR
        │
        ├──► CI Checks (tests, gitleaks, security analysis)
        │
        ├──► admin-human approval required
        │
        └──► Merge to main
                  │
                  ▼
             ArgoCD detects diff
                  │
                  ▼
             Cluster updated
```

**Why this matters for AI:** The agent cannot deploy anything the human hasn't reviewed. The pipeline is the contract.

---

## Slide 6 — Security Model: Six Hard Controls

| # | Requirement | Mechanism | What it prevents |
|---|---|---|---|
| R1 | Agent identity isolation | Separate PATs: `dev-agent` / `admin-human` | One compromise exposes everything |
| R2 | Least privilege | Write-only token + CODEOWNERS | Agent acts outside its scope |
| R3 | HITL gate | PR required + `admin-human` approval whitelist | Agent merges without human review |
| R4 | Audit trail | Every action is a signed Git commit | Actions untraceable |
| R5 | Secret protection | gitleaks on every push (platform-managed) | Credentials committed to Git |
| R6 | Supply chain | `protected_file_patterns` on `.gitea/workflows/*` | Agent modifies its own pipeline |

*These are mechanical controls enforced by tooling — not instructions to the AI.*

---

## Slide 7 — What Agents Can and Cannot Do

```
                    ┌─────────────────────┐
                    │     Git (Gitea)      │
                    │   THE TRUST BOUNDARY │
                    └──────────┬──────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
     CAN do                    │               CANNOT do
          │                    │                    │
  Open PRs on           All changes          Push to main
  feature branches      visible here         directly
          │                    │                    │
  Read repo state        Audit trail          Modify workflows
          │                    │                    │
  Post PR comments      Immutable log         Self-approve PRs
          │                    │                    │
  Trigger CI             Signed commits       Bypass gitleaks
```

---

## Slide 8 — Agentic Security Analyser (Live)

**The first agentic capability: automated PR security review**

```
PR opened on sample-backend-app
            │
            ▼
  Gitea Actions: security-analysis.yaml
            │
            ├─ git diff origin/main...HEAD
            │
            └─ security_check.py
                      │
                      │  POST /api/chat (streaming)
                      ▼
            Foundation-Sec-8B via Ollama
            (Cisco security-focused 8B model, local)
                      │
                      ▼
              Structured analysis:
              Risk Level / Summary /
              Findings / GitOps Impact
                      │
                      ▼
            PR comment posted by gitea-actions
```

---

## Slide 9 — Security Analyser: Example Output

**Input:** PR adding hardcoded AWS credentials to `main.py`

```python
+AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
+AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/..."
+DB_PASSWORD = "admin123"
```

**Output (Foundation-Sec-8B):**

> **Risk Level: CRITICAL**
>
> **Summary:** Hardcoded AWS credentials in source code, exposing sensitive information.
>
> **Findings:**
> - AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are hardcoded — violates security best practices
> - Static credentials can be extracted from the codebase and used maliciously
>
> **Recommendation:** Use AWS Secrets Manager or environment variables. Implement IAM roles instead of static credentials.

*This runs automatically. No human wrote this analysis.*

---

## Slide 10 — What's Built vs What's Next

```
DONE                          IN PROGRESS              PENDING
─────────────────────         ─────────────────         ──────────────────
✓ Control system infra        ~ Langflow integration    ○ MCP servers
  (Gitea, Actions, ArgoCD)      (wire security_check     (per-concern,
                                 to Langflow flow)         least privilege)
✓ End-to-end GitOps           ~ Terraform for AWS       ○ LangGraph workflows
  pipeline (local)                                        (deployment, triage)

✓ Security model R1–R6        ~ Kyverno policies        ○ Knowledge graph
  (all enforced)                                          (extraction pipeline)

✓ Security Analyser                                     ○ Evaluation
  (Foundation-Sec-8B in CI)                               (TSR, MTTR metrics)
```

---

## Slide 11 — Roadmap: Full Agentic Layer

```
                    ┌──────────────────────┐
                    │   Human Operator     │
                    │   (admin-human)      │
                    └──────────┬───────────┘
                               │ approves PRs
                    ┌──────────▼───────────┐
                    │   LangGraph Agent    │  ← next phase
                    │   (orchestrator)     │
                    └──┬──────┬────────┬───┘
                       │      │        │
              ┌────────▼┐  ┌──▼────┐  ┌▼──────────┐
              │   MCP    │  │  MCP  │  │    MCP    │
              │  State   │  │ArgoCD │  │  Gitea    │
              │ (read)   │  │(sync) │  │ (PR/code) │
              └─────────┘  └───────┘  └───────────┘
                       │      │        │
                    ┌──▼──────▼────────▼──┐
                    │   GitOps (Git)       │
                    │   THE HARD BOUNDARY  │
                    └─────────────────────┘
```

Each MCP server is scoped to least privilege. The agent cannot reach infrastructure directly — only through Git.

---

## Slide 12 — Priority Model

```
        SECURITY
           │
           │  Hard constraints enforced by tooling
           │  (branch protection, CODEOWNERS, gitleaks)
           │
           ▼
       RELIABILITY
           │
           │  Operational metrics: TSR, MTTR
           │  (measured in evaluation phase)
           │
           ▼
       CAPABILITY
           │
           │  Supported use cases expanded only after
           │  existing cases are secure and reliable
           │
           ▼
```

*Capability is the last priority, not the first. This is the core design decision.*

---

## Slide 13 — Summary

**Three things that make this different from "LLM + cloud API":**

1. **Git is the enforcement layer** — agents submit PRs, humans merge. The pipeline cannot be bypassed.

2. **Controls are mechanical, not instructional** — branch protection, CODEOWNERS, gitleaks fire regardless of what the agent was told to do.

3. **The agent is auditable by construction** — every action is a commit with an author, SHA, and timestamp. Nothing happens off-book.

**Current state:** Control plane live · GitOps pipeline verified · Security model enforced · Security analyser running in CI

---

## Diagram Notes

- **Slides 4, 7, 11** — box-and-arrow diagrams, works well in draw.io or PowerPoint SmartArt
- **Slide 6** — styled table with a status colour column (green = Live)
- **Slide 10** — three-column layout with icons (✓ / ~ / ○)
- **Slide 12** — vertical funnel or stacked pyramid shape
- Use a consistent accent colour for the **Git / GitOps boundary** across all architecture diagrams to reinforce the core theme
