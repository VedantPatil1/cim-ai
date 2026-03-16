# AI Sandbox Environments

## Purpose

AI agents proposing infrastructure or deployment changes need a place to test those changes before they affect any real environment. Without this, the only test path is production — which violates the security model (agents must not reach production without human review).

A sandbox environment is an ephemeral, isolated Kubernetes namespace that:
- Contains the exact state of a PR branch's manifests
- Is created automatically when a PR is opened
- Is torn down automatically when the PR closes
- Is scoped to only what the `sandbox` AppProject allows

This gives AI agents (and human reviewers) a live deployment to inspect, test, and validate before approving a merge.

---

## Design

### Opt-in: `.cim/sandbox.yaml`

Sandbox environments are **opt-in per repo**. A gitops repo signals its intent by adding a `.cim/sandbox.yaml` file:

```yaml
# .cim/sandbox.yaml
version: v1
sandbox:
  manifests_path: manifests   # ArgoCD path to deploy from (default: manifests)
  ai_testing: true            # signal to AI agents: this sandbox accepts agent validation
```

This file is the single control point. Remove it and the sandbox ApplicationSet is not created (existing sandboxes are not affected until the ApplicationSet is explicitly deleted).

### Components

```
┌───────────────────────────────────────────────────────────────┐
│  sandbox-environments (ArgoCD-managed CNOE package)           │
│                                                               │
│  AppProject: sandbox      ← scopes apps to sandbox-* ns only  │
│  Secret: gitea-admin-token ← Gitea API token for PR polling   │
│  Job: argocd-sandbox-setup ← configures sandbox-agent user    │
└───────────────────────────────────────────────────────────────┘
        │ creates (via argocd-cm patch)
        ▼
  ArgoCD local user: sandbox-agent
  RBAC: role:sandbox-manager (manage ApplicationSets only)

        │ used by
        ▼
┌───────────────────────────────────────────────────────────────┐
│  sandbox-lifecycle.yaml (Gitea Actions workflow)              │
│  Installed by platform-workflows CronJob into every repo      │
│                                                               │
│  on: push to main, paths: [.cim/sandbox.yaml]                 │
│  → calls ArgoCD API → creates ApplicationSet for this repo    │
└───────────────────────────────────────────────────────────────┘
        │ ApplicationSet created
        ▼
┌───────────────────────────────────────────────────────────────┐
│  ArgoCD ApplicationSet: sandbox-<repo>                        │
│                                                               │
│  Generator: pullRequest (Gitea PR generator)                  │
│  → polls Gitea every 60s for open PRs                         │
│  → creates one Application per open PR                        │
│  → deletes Application when PR closes                         │
└───────────────────────────────────────────────────────────────┘
        │ per PR
        ▼
┌───────────────────────────────────────────────────────────────┐
│  ArgoCD Application: sandbox-<repo>-pr-<number>               │
│                                                               │
│  Source: PR branch HEAD, path: manifests                      │
│  Destination: namespace sandbox-<repo>-pr-<number>            │
│  SyncPolicy: automated, selfHeal: true, prune: true           │
└───────────────────────────────────────────────────────────────┘
```

### End-to-End Flow

```
1. Gitops repo adds .cim/sandbox.yaml → pushes to main
        │
2. sandbox-lifecycle.yaml workflow triggers
        │ calls ArgoCD API (ARGOCD_SANDBOX_TOKEN org secret)
        ▼
3. ApplicationSet "sandbox-<repo>" created in ArgoCD
        │ polls Gitea API (gitea-admin-token secret)
        ▼
4. Developer or AI agent opens a PR on the gitops repo
        │
5. ArgoCD PR generator detects the PR (within 60s)
        │
6. ArgoCD creates Application "sandbox-<repo>-pr-<N>"
   deploys PR branch manifests to namespace "sandbox-<repo>-pr-<N>"
        │
7. AI agent or test workflow inspects the live sandbox
   (e.g., runs smoke tests, compares behaviour to main branch)
        │
8. PR merged or closed
        │
9. ArgoCD prunes Application + namespace automatically
```

---

## Isolation Boundaries

The `sandbox` AppProject enforces:

| Constraint | Mechanism |
|---|---|
| Namespace isolation | Applications can only deploy to `sandbox-*` namespaces |
| No cluster-level resources | ClusterRoles, PersistentVolumes, and CRDs are blocked |
| Namespace auto-creation | `CreateNamespace=true` sync option; `Namespace` is whitelisted at cluster scope |
| Automatic pruning | `prune: true` removes resources when they disappear from the PR branch |

A sandbox application cannot escape its namespace, cannot affect other sandboxes, and cannot reach production namespaces.

**Future: Kyverno policies** will add a second enforcement layer — network policies restricting egress from `sandbox-*` namespaces, and resource quotas capping CPU/memory per sandbox. This is deferred until the Kyverno package is implemented.

---

## Security Model

The `sandbox-agent` ArgoCD user has **minimum required permissions**:

```
p, role:sandbox-manager, applicationsets, get,    */*, allow
p, role:sandbox-manager, applicationsets, create, */*, allow
p, role:sandbox-manager, applicationsets, update, */*, allow
p, role:sandbox-manager, applicationsets, delete, */*, allow
g, sandbox-agent, role:sandbox-manager
```

It cannot: sync applications, deploy workloads directly, override sync policies, or access production credentials. The ApplicationSet it creates is itself scoped to the `sandbox` project — the blast radius is further constrained at the project level.

The `ARGOCD_SANDBOX_TOKEN` is stored as a Gitea **org-level** secret (accessible to all repos). If this token is compromised, an attacker could create or delete sandbox ApplicationSets — but not reach production environments, because the `sandbox-agent` account has no permissions beyond ApplicationSet management, and ApplicationSets are constrained to the `sandbox` project.

---

## Bootstrap Requirements

Three manual steps are required after initial cluster creation. See [sandbox-environments/README.md](../../control-system-infrastructure/cnoe-stack/packages/sandbox-environments/README.md) for the full commands.

| Step | What | Why manual |
|---|---|---|
| 1 | Populate `gitea-admin-token` Secret | Token is generated by Gitea API at runtime |
| 2 | Generate `sandbox-agent` ArgoCD token | Requires ArgoCD CLI after the user is configured |
| 3 | Store token as Gitea org secret `ARGOCD_SANDBOX_TOKEN` | Requires Gitea API after token is known |

These cannot be fully automated without a chicken-and-egg problem (the bootstrap needs a credential to create a credential). This is a deliberate design decision: the first credential issuance is always a human action. This is consistent with the HITL principle from the [methodology](../methodology.md#1-priority-model-security--reliability--capability).

---

## Relationship to the Agentic Layer

When the agentic system is implemented (Phase 2), AI agents will interact with sandbox environments as their primary testing surface:

1. Agent proposes a change → opens a PR on the gitops repo
2. Sandbox environment automatically appears
3. Agent's test tool (via MCP server) validates the change against the sandbox
4. Agent updates the PR description with test results
5. Human reviewer sees both the diff and the live sandbox evidence before approving

The sandbox is the **trust-building mechanism**: it converts an agent's claim ("this change is safe") into observable evidence ("this is what the change does in a live environment").
