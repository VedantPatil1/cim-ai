# Operational Knowledge Graph

## The Problem

Raw markdown documentation is suitable for humans but is a poor context source for agents. Two naive alternatives and why they fall short:

**RAG over docs (vector search):** Retrieves semantically similar chunks but cannot answer structural questions precisely. "What services does the payment service depend on?" should return an exact answer, not a ranked list of possibly relevant paragraphs.

**Feeding raw docs into context:** Expensive, noisy, and doesn't scale. Agents get irrelevant text alongside the few facts they need.

**The alternative:** Extract structured facts from documentation *once*, on commit, store them as a knowledge graph, and let agents query the graph directly. The graph is always current because it is rebuilt whenever its source changes.

---

## Design

### What the Graph Captures

The graph models the operational structure of the system — not application business logic, but the infrastructure and operational layer that agents need to reason about.

**Nodes**

| Type | Attributes | Example |
|---|---|---|
| `Service` | name, repo, owner, language | `sample-backend-api` |
| `Component` | type (db/queue/cache/registry), name | `kind-registry` |
| `Repository` | name, type (app/gitops/infra) | `sample-backend-gitops` |
| `Environment` | name, tier (local/cloud) | `production` |
| `Policy` | name, enforcer, scope | `no-privileged-containers` |
| `Runbook` | name, trigger, steps-summary | `restart-failing-deployment` |
| `Team` | name | `platform-eng` |

**Edges**

| Relationship | From → To | Meaning |
|---|---|---|
| `DEPENDS_ON` | Service → Service/Component | runtime dependency |
| `OWNS` | Team → Service/Repository | ownership |
| `DEPLOYS_TO` | Repository → Environment | gitops target |
| `GOVERNED_BY` | Service/Environment → Policy | policy applies |
| `DOCUMENTED_BY` | Service/Runbook → Runbook | operational procedure |
| `PROVISIONS` | Repository → Component | terraform manages |

### Sources of Truth

The graph is extracted from multiple source types — not just prose docs:

| Source | What it yields |
|---|---|
| `docs/**/*.md` | Runbooks, architecture descriptions, service ownership |
| `**.tf` (Terraform) | Infrastructure components, environment topology |
| `**/deployment.yaml` (K8s) | Services, dependencies, environment assignments |
| `**/kustomization.yaml` | Environment overlays, deployment targets |
| `app.yaml` (ArgoCD) | GitOps repo-to-environment bindings |

The extraction agent reads changed files on each push. It does not re-process the entire corpus on every run — only files in the diff.

---

## Extraction Pipeline

### Trigger

A Gitea Actions workflow fires on pushes that touch any source file:

```yaml
on:
  push:
    paths:
      - 'docs/**'
      - '**.tf'
      - '**/deployment.yaml'
      - '**/kustomization.yaml'
      - '**/app.yaml'
```

### Extraction Agent

The agent is a scoped Python process (not an interactive session):

```
Changed files from git diff
        │
        ▼
Claude API (structured output)
        │  schema: { nodes: [...], edges: [...] }
        ▼
Merge with existing graph
        │  add new nodes/edges, update changed, flag removals
        ▼
Write graph to graph store
        │
        ▼
Commit updated graph back to repo
```

The extraction uses Claude with a strict JSON output schema — entities and relationships are typed and validated before being written to the graph. The agent has no permissions beyond reading source files and writing to the graph output path.

### Output Format: Two Phases

**Phase 1 — JSON in Git**

The graph is stored as a JSON file (`knowledge-graph/graph.json`) committed to the repository. No external service required. Fully auditable — every graph change is a Git diff.

```json
{
  "nodes": [
    { "id": "svc:sample-backend-api", "type": "Service", "attrs": { "owner": "platform-eng", "repo": "sample-backend-api-app" } }
  ],
  "edges": [
    { "from": "svc:sample-backend-api", "to": "env:production", "rel": "DEPLOYS_TO" }
  ]
}
```

**Phase 2 — Kuzu (embedded graph DB)**

[Kuzu](https://kuzudb.com/) is an embedded graph database (no server, pure Python/C++). It enables proper Cypher-style queries without operational overhead. The Kuzu database file is built from `graph.json` at startup and can be queried by agents:

```cypher
MATCH (s:Service)-[:GOVERNED_BY]->(p:Policy)
WHERE s.name = 'sample-backend-api'
RETURN p.name, p.enforcer
```

The transition from Phase 1 to Phase 2 is additive — `graph.json` remains the source of truth; Kuzu is built from it.

---

## Agent Query Interface

Agents do not query the graph directly via Cypher. They use a dedicated MCP server that exposes a small set of typed queries:

| Tool | Arguments | Returns |
|---|---|---|
| `get_service_context` | `service_name` | owner, repo, dependencies, policies, runbooks |
| `get_environment_topology` | `env_name` | services deployed, infra components, governing policies |
| `get_runbook` | `runbook_name` | trigger conditions, step summary |
| `find_policy_violations` | `service_name`, `proposed_change` | matching policies that would be violated |

This keeps graph internals hidden from agents. The MCP server is the single point of access — it enforces read-only access and logs every query.

---

## Constraints and Risks

**Extraction quality is LLM-dependent.** The graph is only as accurate as what Claude extracts. Poorly structured or ambiguous source documents produce sparse or incorrect nodes. Mitigation: enforce a documentation structure standard for operational docs (headings, ownership fields, dependency lists).

**Schema drift.** As the system evolves, new node/edge types will be needed. The JSON schema must be versioned and migration scripts maintained alongside the graph.

**The extraction agent is an agentic process.** It must follow the same security constraints as other agents: read-only access to source files, write access only to the graph output path, no network access beyond the Claude API. It should not be able to modify the source docs it reads.

**Graph completeness vs. maintenance cost.** A richer graph schema captures more context but requires more maintenance. Start minimal — only the relationships that agents demonstrably need — and expand incrementally.
