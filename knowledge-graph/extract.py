#!/usr/bin/env python3
"""
Knowledge graph extraction agent.

Reads changed (or all) source files, calls Claude API to extract
structured nodes/edges, merges into knowledge-graph/graph.json.

Usage:
  python extract.py                          # process files changed in HEAD~1
  python extract.py --files docs/foo.md ...  # process specific files
  python extract.py --all                    # scan all eligible files
  python extract.py --all --commit           # extract + git commit + push

Requires: ANTHROPIC_API_KEY env var
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import anthropic
from pydantic import ValidationError

# Add project root to path so schema.py is importable
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from schema import KnowledgeGraph, Node, Edge

GRAPH_PATH = Path(__file__).parent / "graph.json"

# File patterns eligible for extraction
ELIGIBLE_GLOBS = [
    "docs/**/*.md",
    "**/*.tf",
    "**/deployment.yaml",
    "**/kustomization.yaml",
    "**/app.yaml",
    "control-system-infrastructure/**/*.yaml",
]

# Skip generated or non-informative paths
SKIP_PREFIXES = [
    "site/",
    "knowledge-graph/",
    ".git/",
    "node_modules/",
    "uv.lock",
]

EXTRACTION_PROMPT = """\
You are a knowledge extraction agent for a cloud infrastructure documentation corpus.
Your job is to extract structured entities and relationships from the provided file.

## Schema

Node types: Service, Component, Repository, Environment, Policy, Runbook, Team

Edge relationships:
- DEPENDS_ON: Service/Component → Service/Component
- OWNS: Team → Service/Repository
- DEPLOYS_TO: Repository → Environment
- GOVERNED_BY: Service/Environment → Policy
- DOCUMENTED_BY: Service → Runbook
- PROVISIONS: Repository → Component

## ID conventions

Use prefixed IDs:
- svc:   Service
- comp:  Component
- repo:  Repository
- env:   Environment
- pol:   Policy (use policy: prefix)
- rb:    Runbook (use runbook: prefix)
- team:  Team

Example: "svc:sample-backend-api", "env:staging", "team:platform-eng"

## Instructions

1. Read the file content below carefully.
2. Extract ONLY entities and relationships that are explicitly mentioned or strongly implied.
3. Do NOT hallucinate entities that are not present in the file.
4. Return ONLY valid JSON matching the schema below — no markdown, no explanation.

## Output schema

{
  "nodes": [
    {"id": "<prefix:name>", "type": "<NodeType>", "attrs": {"name": "<name>", ...}}
  ],
  "edges": [
    {"from": "<node-id>", "to": "<node-id>", "rel": "<EdgeRel>"}
  ]
}

If the file contains nothing extractable, return: {"nodes": [], "edges": []}

## File: {filename}

{content}
"""


def get_changed_files() -> list[Path]:
    """Get files changed in the last commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True, text=True, cwd=REPO_ROOT, check=True,
        )
        files = [REPO_ROOT / f.strip() for f in result.stdout.splitlines() if f.strip()]
        return [f for f in files if f.exists()]
    except subprocess.CalledProcessError:
        # Fallback: single commit repo
        result = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        files = [REPO_ROOT / f.strip() for f in result.stdout.splitlines() if f.strip()]
        return [f for f in files if f.exists()]


def get_all_eligible_files() -> list[Path]:
    """Scan the repo for all eligible source files."""
    files: list[Path] = []
    for pattern in ELIGIBLE_GLOBS:
        for p in REPO_ROOT.glob(pattern):
            if p.is_file():
                files.append(p)
    return files


def should_skip(path: Path) -> bool:
    rel = str(path.relative_to(REPO_ROOT))
    for prefix in SKIP_PREFIXES:
        if rel.startswith(prefix):
            return True
    return False


def extract_from_file(client: anthropic.Anthropic, path: Path) -> KnowledgeGraph:
    """Call Claude to extract nodes/edges from a single file."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"  [skip] cannot read {path}: {e}")
        return KnowledgeGraph()

    # Truncate very large files to avoid token limits
    max_chars = 12_000
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[... truncated ...]"

    rel_path = str(path.relative_to(REPO_ROOT))
    prompt = EXTRACTION_PROMPT.format(filename=rel_path, content=content)

    print(f"  Extracting: {rel_path}")
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [warn] JSON parse error for {rel_path}: {e}")
        return KnowledgeGraph()

    partial = KnowledgeGraph()
    for n in data.get("nodes", []):
        try:
            partial.upsert_node(Node(**n))
        except (ValidationError, ValueError) as e:
            print(f"  [warn] invalid node {n.get('id', '?')}: {e}")

    for e in data.get("edges", []):
        try:
            partial.upsert_edge(Edge(**e))
        except (ValidationError, ValueError) as err:
            print(f"  [warn] invalid edge {e}: {err}")

    return partial


def commit_graph() -> None:
    """Git add + commit + push the updated graph.json."""
    rel = str(GRAPH_PATH.relative_to(REPO_ROOT))
    subprocess.run(["git", "config", "user.email", "kg-agent@cnoe.local"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.name", "Knowledge Graph Agent"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "add", rel], cwd=REPO_ROOT, check=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT
    )
    if result.returncode == 0:
        print("No changes to graph — skipping commit.")
        return

    subprocess.run(
        ["git", "commit", "-m", "feat(kg): update knowledge graph [skip ci]"],
        cwd=REPO_ROOT, check=True,
    )
    subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
    print("Graph committed and pushed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract knowledge graph from repo sources")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--files", nargs="+", type=Path, help="Specific files to process")
    group.add_argument("--all", action="store_true", help="Process all eligible files")
    parser.add_argument("--commit", action="store_true", help="Commit and push updated graph.json")
    parser.add_argument("--dry-run", action="store_true", help="Extract but do not write graph.json")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Determine which files to process
    if args.files:
        files = [Path(f).resolve() for f in args.files]
    elif args.all:
        files = [f for f in get_all_eligible_files() if not should_skip(f)]
    else:
        files = [f for f in get_changed_files() if not should_skip(f)]

    if not files:
        print("No eligible files to process.")
        return

    print(f"Processing {len(files)} file(s)...")

    # Load existing graph
    graph = KnowledgeGraph.load(GRAPH_PATH)
    print(f"Loaded existing graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # Extract and merge
    for path in files:
        partial = extract_from_file(client, path)
        if partial.nodes or partial.edges:
            print(f"  → +{len(partial.nodes)} nodes, +{len(partial.edges)} edges")
            graph.merge(partial)

    print(f"Graph after merge: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    if args.dry_run:
        print("Dry run — not writing graph.json")
        print(json.dumps(graph.to_dict(), indent=2)[:2000], "...")
        return

    graph.save(GRAPH_PATH)
    print(f"Saved to {GRAPH_PATH}")

    if args.commit:
        commit_graph()


if __name__ == "__main__":
    main()
