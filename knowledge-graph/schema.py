"""
Knowledge graph schema — Pydantic v2 models.

Matches the design in docs/knowledge-graph.md.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    SERVICE = "Service"
    COMPONENT = "Component"
    REPOSITORY = "Repository"
    ENVIRONMENT = "Environment"
    POLICY = "Policy"
    RUNBOOK = "Runbook"
    TEAM = "Team"


class EdgeRel(str, Enum):
    DEPENDS_ON = "DEPENDS_ON"
    OWNS = "OWNS"
    DEPLOYS_TO = "DEPLOYS_TO"
    GOVERNED_BY = "GOVERNED_BY"
    DOCUMENTED_BY = "DOCUMENTED_BY"
    PROVISIONS = "PROVISIONS"


# ---------------------------------------------------------------------------
# Graph elements
# ---------------------------------------------------------------------------

class Node(BaseModel):
    id: str = Field(..., description="Stable identifier, e.g. 'svc:sample-backend-api'")
    type: NodeType
    attrs: dict[str, Any] = Field(default_factory=dict)

    def key(self) -> str:
        return self.id


class Edge(BaseModel):
    from_: str = Field(..., alias="from", description="Source node id")
    to: str = Field(..., description="Target node id")
    rel: EdgeRel
    attrs: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    def key(self) -> tuple[str, str, str]:
        return (self.from_, self.to, self.rel.value)

    def to_dict(self) -> dict:
        d = self.model_dump(by_alias=True)
        d["rel"] = self.rel.value
        return d


# ---------------------------------------------------------------------------
# Graph container
# ---------------------------------------------------------------------------

class KnowledgeGraph(BaseModel):
    version: int = 1
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def find_node(self, node_id: str) -> Node | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def upsert_node(self, node: Node) -> None:
        """Add node, or replace existing node with same id."""
        for i, n in enumerate(self.nodes):
            if n.id == node.id:
                self.nodes[i] = node
                return
        self.nodes.append(node)

    def upsert_edge(self, edge: Edge) -> None:
        """Add edge, or replace existing edge with same (from, to, rel) key."""
        key = edge.key()
        for i, e in enumerate(self.edges):
            if e.key() == key:
                self.edges[i] = edge
                return
        self.edges.append(edge)

    def remove_node(self, node_id: str) -> bool:
        before = len(self.nodes)
        self.nodes = [n for n in self.nodes if n.id != node_id]
        # also remove dangling edges
        self.edges = [
            e for e in self.edges if e.from_ != node_id and e.to != node_id
        ]
        return len(self.nodes) < before

    # ------------------------------------------------------------------
    # Query helpers (used by mcp_server)
    # ------------------------------------------------------------------

    def neighbours(self, node_id: str, rel: EdgeRel | None = None) -> list[Node]:
        """Return nodes reachable from node_id (optionally filtered by rel)."""
        targets = [
            e.to for e in self.edges
            if e.from_ == node_id and (rel is None or e.rel == rel)
        ]
        return [n for n in self.nodes if n.id in targets]

    def incoming(self, node_id: str, rel: EdgeRel | None = None) -> list[Node]:
        """Return nodes that point to node_id."""
        sources = [
            e.from_ for e in self.edges
            if e.to == node_id and (rel is None or e.rel == rel)
        ]
        return [n for n in self.nodes if n.id in sources]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "nodes": [
                {"id": n.id, "type": n.type.value, "attrs": n.attrs}
                for n in self.nodes
            ],
            "edges": [e.to_dict() for e in self.edges],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> "KnowledgeGraph":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        nodes = [Node(**n) for n in raw.get("nodes", [])]
        edges = [Edge(**e) for e in raw.get("edges", [])]
        return cls(version=raw.get("version", 1), nodes=nodes, edges=edges)

    # ------------------------------------------------------------------
    # Merge: incorporate a partial graph (from extraction) into self
    # ------------------------------------------------------------------

    def merge(self, other: "KnowledgeGraph") -> None:
        for node in other.nodes:
            self.upsert_node(node)
        for edge in other.edges:
            self.upsert_edge(edge)
