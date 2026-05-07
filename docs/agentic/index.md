# Agentic Layer

**Phase 1 — implemented May 2026**

The agentic layer sits on top of the GitOps substrate and adds reasoning capability to it. Where the GitOps pipeline handles *execution* (build, deploy, sync), the agentic layer handles *understanding* — answering questions about the system, assessing the impact of changes, and surfacing security risks before code merges.

---

## What Was Built

Three subsystems, all operating within the same security model as the rest of the platform.

### 1. Knowledge Graph

A structured representation of the operational system — services, repositories, environments, policies, and runbooks — extracted from docs and manifests using the Claude API and stored as `knowledge-graph/graph.json`.

```
docs/**/*.md
**/deployment.yaml         Claude API           knowledge-graph/
**/app.yaml           →   (extraction)    →    graph.json
**.tf                      claude-haiku-4-5     (versioned in Git)
```

The graph is queried via a lightweight HTTP MCP server (not fed raw to the LLM), which keeps agent context tight and costs low.

**Key properties:**

- Fully auditable — every update is a Git diff
- Incremental — only changed files are re-processed
- No external service — JSON file committed back to the repo
- Phase 2 path: Kuzu embedded graph DB for Cypher-style queries

### 2. MCP Server

An HTTP server (`knowledge-graph/mcp_server.py`) that exposes 4 typed query tools. Agents call the MCP server instead of reading `graph.json` directly.

| Tool | Arguments | Returns |
|---|---|---|
| `get_service_context` | `service_name` | owner, repo, dependencies, policies, runbooks |
| `get_environment_topology` | `env_name` | deployers, components, policies |
| `get_runbook` | `runbook_name` | trigger conditions, step summary |
| `find_policy_violations` | `service_name`, `proposed_change` | violated policies (Claude-assisted) |

The server reloads `graph.json` on each request, so it always reflects the latest extraction.

### 3. Langflow Agent Flows

Four importable flows for Langflow 1.5. Each uses `claude-haiku-4-5-20251001` for cost efficiency and can be upgraded to `claude-sonnet-4-6` for more complex reasoning.

| Flow | File | Use case |
|---|---|---|
| Security Analyser | `agentic/security-analyser/flow.json` | Analyse a PR diff for security risks |
| KG Query | `agentic/knowledge-graph-query/flow.json` | Answer questions about the infra from the graph |
| Change Impact | `agentic/change-impact-analyzer/flow.json` | Blast radius analysis for a proposed change |
| Infrastructure Advisor | `agentic/infrastructure-advisor/flow.json` | Conversational advisor with full KG context |

### 4. Evaluation Framework

`metrics/` contains a simple event log + calculator for the two core metrics used to evaluate the agentic system.

| Metric | Definition | Seed value |
|---|---|---|
| **TSR** (Task Success Rate) | `(successful tasks / total tasks) × 100` | 87.5% |
| **MTTR** (Mean Time to Resolution) | Average `duration_s` across all tasks | 77.5s |

---

## Architecture Diagram

```
                     ┌─────────────────────────────────────┐
                     │         Agentic Layer                │
                     │                                      │
  User / PR event ──►│  Langflow Flow                       │
                     │    ├─ Security Analyser              │
                     │    ├─ KG Query                       │
                     │    ├─ Change Impact                  │
                     │    └─ Infra Advisor                  │
                     │           │                          │
                     │           ▼                          │
                     │    MCP Server (port 8765)            │
                     │           │                          │
                     │           ▼                          │
                     │    knowledge-graph/graph.json        │
                     │           ▲                          │
                     │           │ (on push to docs/**)     │
                     │    Gitea Actions: extract.py         │
                     │    (calls claude-haiku-4-5)          │
                     └─────────────────────────────────────┘
                                 │
                     ┌───────────▼──────────────────────────┐
                     │         GitOps Substrate             │
                     │  Gitea · Gitea Actions · ArgoCD      │
                     └──────────────────────────────────────┘
```

---

## Security Boundaries

The agentic layer operates within the same security model as the rest of the platform:

- The **extraction agent** (`extract.py`) has read-only access to source files and write-only access to `knowledge-graph/graph.json`. It cannot modify the docs it reads.
- The **MCP server** is read-only. No mutations happen through it.
- The **Langflow flows** call the Claude API and the MCP server. They do not connect to Gitea, ArgoCD, or any cluster directly.
- Any infrastructure change a flow recommends must still go through a PR → `admin-human` approval → ArgoCD sync. The agentic layer cannot bypass the HITL gate.

---

## Files

```
knowledge-graph/
  schema.py          Pydantic models: Node, Edge, KnowledgeGraph
  extract.py         Extraction script (Claude API, incremental)
  graph.json         Knowledge graph (versioned in Git)
  mcp_server.py      HTTP MCP server, port 8765

.gitea/workflows/
  knowledge-graph-extract.yaml  Gitea Actions trigger

agentic/
  security-analyser/flow.json      Langflow 1.5
  knowledge-graph-query/flow.json  Langflow 1.5
  change-impact-analyzer/flow.json Langflow 1.5
  infrastructure-advisor/flow.json Langflow 1.5

metrics/
  schema.py          TaskEvent dataclass
  events.json        Event log
  calculate.py       TSR / MTTR calculator
```

---

## Next Steps

- [Usage Guide](usage.md) — how to run each component locally
- [Demo Scenarios](scenarios.md) — end-to-end walkthroughs for demonstration
