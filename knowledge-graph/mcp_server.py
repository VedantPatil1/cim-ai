#!/usr/bin/env python3
"""
Knowledge Graph MCP Server.

Exposes 4 typed query tools over the knowledge graph (graph.json).
Runs as a simple HTTP server — no external MCP framework required.

Endpoints (POST /tool with JSON body {"tool": "<name>", "args": {...}}):
  - get_service_context        {"service_name": "sample-backend-api"}
  - get_environment_topology   {"env_name": "staging"}
  - get_runbook                {"runbook_name": "deploy-sample-backend"}
  - find_policy_violations     {"service_name": "...", "proposed_change": "..."}

Usage:
  python mcp_server.py               # runs on port 8765
  python mcp_server.py --port 9000

Requires: anthropic pydantic (only find_policy_violations uses Claude)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from schema import EdgeRel, KnowledgeGraph, NodeType

GRAPH_PATH = Path(__file__).parent / "graph.json"


# ---------------------------------------------------------------------------
# Query implementations
# ---------------------------------------------------------------------------

def get_service_context(graph: KnowledgeGraph, service_name: str) -> dict:
    """Return owner, repo, dependencies, policies, and runbooks for a service."""
    # Resolve node id: accept bare name or prefixed id
    node_id = service_name if service_name.startswith("svc:") else f"svc:{service_name}"
    node = graph.find_node(node_id)
    if node is None:
        # Try fuzzy match on name attr
        for n in graph.nodes:
            if n.type == NodeType.SERVICE and n.attrs.get("name") == service_name:
                node = n
                node_id = n.id
                break
    if node is None:
        return {"error": f"Service '{service_name}' not found in knowledge graph"}

    owners = [n.attrs for n in graph.incoming(node_id, EdgeRel.OWNS)]
    deps = [{"id": n.id, **n.attrs} for n in graph.neighbours(node_id, EdgeRel.DEPENDS_ON)]
    policies = [{"id": n.id, **n.attrs} for n in graph.neighbours(node_id, EdgeRel.GOVERNED_BY)]
    runbooks = [{"id": n.id, **n.attrs} for n in graph.neighbours(node_id, EdgeRel.DOCUMENTED_BY)]

    # Repo from attrs
    repo_id = node.attrs.get("repo")
    repo_node = graph.find_node(repo_id) if repo_id else None
    repo = repo_node.attrs if repo_node else {}

    return {
        "service": {"id": node.id, **node.attrs},
        "owner": owners[0] if owners else None,
        "repo": repo,
        "dependencies": deps,
        "policies": policies,
        "runbooks": runbooks,
    }


def get_environment_topology(graph: KnowledgeGraph, env_name: str) -> dict:
    """Return services deployed to, infra components in, and policies for an environment."""
    node_id = env_name if env_name.startswith("env:") else f"env:{env_name}"
    node = graph.find_node(node_id)
    if node is None:
        return {"error": f"Environment '{env_name}' not found in knowledge graph"}

    # Services / repos that deploy to this env
    deployers = [
        {"id": n.id, "type": n.type.value, **n.attrs}
        for n in graph.incoming(node_id, EdgeRel.DEPLOYS_TO)
    ]
    # Policies governing this env
    policies = [{"id": n.id, **n.attrs} for n in graph.neighbours(node_id, EdgeRel.GOVERNED_BY)]
    # Runbooks
    runbooks = [{"id": n.id, **n.attrs} for n in graph.neighbours(node_id, EdgeRel.DOCUMENTED_BY)]
    # Infra components provisioned for this env
    components = [
        {"id": n.id, **n.attrs}
        for n in graph.incoming(node_id, EdgeRel.PROVISIONS)
    ]

    return {
        "environment": {"id": node.id, **node.attrs},
        "deployers": deployers,
        "components": components,
        "policies": policies,
        "runbooks": runbooks,
    }


def get_runbook(graph: KnowledgeGraph, runbook_name: str) -> dict:
    """Return trigger conditions and step summary for a runbook."""
    node_id = runbook_name if runbook_name.startswith("runbook:") else f"runbook:{runbook_name}"
    node = graph.find_node(node_id)
    if node is None:
        # Fuzzy name match
        for n in graph.nodes:
            if n.type == NodeType.RUNBOOK and n.attrs.get("name") == runbook_name:
                node = n
                node_id = n.id
                break
    if node is None:
        # List available runbooks
        available = [n.id for n in graph.nodes if n.type == NodeType.RUNBOOK]
        return {
            "error": f"Runbook '{runbook_name}' not found",
            "available": available,
        }

    return {"runbook": {"id": node.id, **node.attrs}}


def find_policy_violations(
    graph: KnowledgeGraph,
    service_name: str,
    proposed_change: str,
) -> dict:
    """
    Identify policies that a proposed change to a service might violate.

    Uses Claude to reason about the change against each policy's description.
    Falls back to listing all governing policies if Claude is unavailable.
    """
    ctx = get_service_context(graph, service_name)
    if "error" in ctx:
        return ctx

    policies = ctx.get("policies", [])
    if not policies:
        return {"service": service_name, "violations": [], "note": "No governing policies found"}

    # Try Claude-assisted violation analysis
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

            policy_text = "\n".join(
                f"- {p.get('name', p['id'])}: {p.get('description', p.get('rules', ''))}"
                for p in policies
            )

            prompt = f"""You are a platform security reviewer.

Service: {service_name}
Governing policies:
{policy_text}

Proposed change:
{proposed_change}

For each policy, determine if the proposed change would violate it.
Return JSON: {{"violations": [{{"policy": "<name>", "reason": "<why violated>"}}], "safe_policies": ["<name>", ...]}}
Return only JSON, no explanation."""

            message = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:-1])
            result = json.loads(raw)
            return {
                "service": service_name,
                "proposed_change": proposed_change[:200],
                **result,
            }
        except Exception as e:
            # Fallback below
            pass

    # Fallback: list all policies without violation analysis
    return {
        "service": service_name,
        "proposed_change": proposed_change[:200],
        "note": "Claude unavailable — listing all governing policies for manual review",
        "governing_policies": policies,
    }


# ---------------------------------------------------------------------------
# Tool registry
#
# Each entry declares: access level, scope, phase, and args schema.
# Phase-1 tools have implementations; Phase-2 stubs return a deferred
# status so the access model is visible without requiring full implementation.
#
# Access levels:
#   read        — returns data, no side effects
#   write       — produces a side effect (post comment, trigger job)
#
# Scope narrows what a tool can touch within its access level.
# Enforcement is in the tool implementation, not in the LLM prompt.
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, dict] = {
    # ------------------------------------------------------------------
    # Phase 1 — Knowledge Graph (read-only, implemented)
    # ------------------------------------------------------------------
    "get_service_context": {
        "access": "read",
        "scope": "knowledge-graph",
        "phase": 1,
        "args": {"service_name": "str"},
        "description": "Return owner, repo, dependencies, policies, and runbooks for a service.",
        "fn": get_service_context,
    },
    "get_environment_topology": {
        "access": "read",
        "scope": "knowledge-graph",
        "phase": 1,
        "args": {"env_name": "str"},
        "description": "Return all components, deployers, and policies for an environment.",
        "fn": get_environment_topology,
    },
    "get_runbook": {
        "access": "read",
        "scope": "knowledge-graph",
        "phase": 1,
        "args": {"runbook_name": "str"},
        "description": "Return trigger conditions and step summary for a runbook.",
        "fn": get_runbook,
    },
    "find_policy_violations": {
        "access": "read",
        "scope": "knowledge-graph",
        "phase": 1,
        "args": {"service_name": "str", "proposed_change": "str"},
        "description": "Identify policies that a proposed change to a service might violate.",
        "fn": find_policy_violations,
    },

    # ------------------------------------------------------------------
    # Phase 2 — Repository read access (read-only, not yet implemented)
    # Scope: files present in the PR diff only. Cannot traverse outside
    # the diff-touched paths or access unrelated repositories.
    # ------------------------------------------------------------------
    "get_file_contents": {
        "access": "read",
        "scope": "repo:diff-paths-only",
        "phase": 2,
        "args": {"repo": "str", "path": "str", "ref": "str"},
        "description": "Read a file from a repository at a given ref. Scoped to paths present in the current diff.",
    },
    "get_pr_diff": {
        "access": "read",
        "scope": "repo:current-pr",
        "phase": 2,
        "args": {"repo": "str", "pr_number": "int"},
        "description": "Fetch the unified diff for a pull request.",
    },
    "get_commit_history": {
        "access": "read",
        "scope": "repo:current-pr",
        "phase": 2,
        "args": {"repo": "str", "path": "str", "limit": "int"},
        "description": "Return recent commit history for a file path.",
    },

    # ------------------------------------------------------------------
    # Phase 2 — Cross-repository read (read-only, not yet implemented)
    # Scope: explicitly listed repos only. Cannot traverse outside the
    # allowlist regardless of how the tool is invoked.
    # ------------------------------------------------------------------
    "get_gitops_manifest": {
        "access": "read",
        "scope": "repo:allowlist=[sample-backend-gitops,sample-backend-infra]",
        "phase": 2,
        "args": {"repo": "str", "path": "str"},
        "description": "Read a deployment manifest or infra definition from a related repository. Allowlisted repos only.",
    },

    # ------------------------------------------------------------------
    # Phase 2 — Static analysis (read-only, not yet implemented)
    # Scope: files in the diff only. Invokes external linters/scanners;
    # cannot write results back to the repo.
    # ------------------------------------------------------------------
    "run_static_analysis": {
        "access": "read",
        "scope": "diff-files-only",
        "phase": 2,
        "args": {"files": "list[str]", "tool": "str"},
        "description": "Run a linter or static analyser against changed files. Returns structured tool output for the LLM to reason about.",
    },

    # ------------------------------------------------------------------
    # Phase 2 — CI log access (read-only, not yet implemented)
    # Scope: current pipeline run and last N runs for the same repo.
    # ------------------------------------------------------------------
    "get_ci_logs": {
        "access": "read",
        "scope": "repo:current-run",
        "phase": 2,
        "args": {"repo": "str", "run_id": "str"},
        "description": "Read stdout/stderr from a CI run. Used to correlate proposed changes with recent test failures.",
    },

    # ------------------------------------------------------------------
    # Phase 2 — Web search (read-only, not yet implemented)
    # Scope: external. Results are summarised before passing to the LLM
    # to prevent context overflow and prompt injection via search results.
    # ------------------------------------------------------------------
    "web_search": {
        "access": "read",
        "scope": "external",
        "phase": 2,
        "args": {"query": "str", "max_results": "int"},
        "description": "Search for CVE entries, vulnerability docs, or remediation guidance. Results summarised before LLM handoff.",
    },

    # ------------------------------------------------------------------
    # Phase 2 — Comment write (write-scoped, not yet implemented)
    # This is the ONLY write tool in the registry. Scope is deliberately
    # narrow: post or update a PR comment. Cannot push code, modify
    # branch configuration, or interact with any resource outside the
    # target PR. Invoked only by the output assembly step, not by any
    # analysis component.
    # ------------------------------------------------------------------
    "post_pr_comment": {
        "access": "write",
        "scope": "repo:target-pr-comments-only",
        "phase": 2,
        "args": {"repo": "str", "pr_number": "int", "body": "str"},
        "description": "Post or update a PR comment. Cannot push code or modify branch settings. Used exclusively by the output assembly step.",
    },
}

# Separate callable tools (phase 1) from declared stubs (phase 2)
CALLABLE_TOOLS = {name: meta["fn"] for name, meta in TOOL_REGISTRY.items() if "fn" in meta}


class MCPHandler(BaseHTTPRequestHandler):
    graph: KnowledgeGraph  # set at server startup

    def log_message(self, format, *args):  # noqa: A002
        print(f"[mcp] {format % args}")

    def send_json(self, code: int, body: Any) -> None:
        data = json.dumps(body, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "nodes": len(self.graph.nodes), "edges": len(self.graph.edges)})
        elif self.path == "/tools":
            tools = []
            for name, meta in TOOL_REGISTRY.items():
                entry = {
                    "name": name,
                    "access": meta["access"],
                    "scope": meta["scope"],
                    "phase": meta["phase"],
                    "args": meta["args"],
                    "description": meta["description"],
                    "status": "implemented" if "fn" in meta else "phase-2-deferred",
                }
                tools.append(entry)
            write_tools = [t["name"] for t in tools if t["access"] == "write"]
            self.send_json(200, {
                "tools": tools,
                "write_tools": write_tools,
                "summary": {
                    "total": len(tools),
                    "read": sum(1 for t in tools if t["access"] == "read"),
                    "write": len(write_tools),
                    "implemented": sum(1 for t in tools if t["status"] == "implemented"),
                    "deferred": sum(1 for t in tools if t["status"] == "phase-2-deferred"),
                },
            })
        else:
            self.send_json(404, {"error": "Not found. Available: GET /health, GET /tools, POST /tool"})

    def do_POST(self):
        if self.path != "/tool":
            self.send_json(404, {"error": "POST /tool expected"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON"})
            return

        tool_name = req.get("tool")
        args = req.get("args", {})

        if tool_name not in TOOL_REGISTRY:
            self.send_json(400, {"error": f"Unknown tool '{tool_name}'", "available": list(TOOL_REGISTRY)})
            return

        meta = TOOL_REGISTRY[tool_name]
        if "fn" not in meta:
            self.send_json(200, {
                "status": "phase-2-deferred",
                "tool": tool_name,
                "access": meta["access"],
                "scope": meta["scope"],
                "description": meta["description"],
                "note": "This tool is declared and scoped but not yet implemented. Access level and scope constraints are enforced at the registry level.",
            })
            return

        # Reload graph on each request so it picks up updates
        self.__class__.graph = KnowledgeGraph.load(GRAPH_PATH)

        try:
            result = CALLABLE_TOOLS[tool_name](self.graph, **args)
            self.send_json(200, result)
        except TypeError as e:
            self.send_json(400, {"error": f"Bad arguments for {tool_name}: {e}"})
        except Exception as e:
            self.send_json(500, {"error": str(e)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge Graph MCP server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--graph", type=Path, default=GRAPH_PATH)
    args = parser.parse_args()

    graph = KnowledgeGraph.load(args.graph)
    MCPHandler.graph = graph
    print(f"Knowledge Graph MCP Server")
    print(f"  Graph: {args.graph} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
    print(f"  Listening on http://localhost:{args.port}")
    implemented = [n for n, m in TOOL_REGISTRY.items() if "fn" in m]
    deferred = [n for n, m in TOOL_REGISTRY.items() if "fn" not in m]
    print(f"  Implemented tools ({len(implemented)}): {', '.join(implemented)}")
    print(f"  Deferred tools    ({len(deferred)}): {', '.join(deferred)}")

    server = HTTPServer(("", args.port), MCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
