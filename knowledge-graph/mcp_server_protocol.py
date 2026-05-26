#!/usr/bin/env python3
"""
Knowledge Graph MCP Server — standard Model Context Protocol implementation.

Exposes the same 4 tools as mcp_server.py but speaks the MCP protocol
(JSON-RPC 2.0 over stdio or SSE) so it works with MCP Inspector,
Claude Desktop, and any MCP-native client.

Usage:
  stdio (MCP Inspector subprocess mode):
    python mcp_server_protocol.py

  SSE (MCP Inspector network mode):
    python mcp_server_protocol.py --transport sse --port 8766
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

sys.path.insert(0, str(Path(__file__).parent))
from schema import KnowledgeGraph

GRAPH_PATH = Path(__file__).parent / "graph.json"

server = Server("knowledge-graph-mcp")


def load_graph() -> KnowledgeGraph:
    return KnowledgeGraph.load(GRAPH_PATH)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_service_context",
            description=(
                "Return the owner, repository, dependencies, governing policies, "
                "and runbooks for a named service in the infrastructure knowledge graph."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "Service name or id (e.g. 'sample-backend-api')",
                    }
                },
                "required": ["service_name"],
            },
        ),
        types.Tool(
            name="get_environment_topology",
            description=(
                "Return all deployers, components, and policies for a named environment "
                "(e.g. 'staging', 'local-kind')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "env_name": {
                        "type": "string",
                        "description": "Environment name (e.g. 'staging')",
                    }
                },
                "required": ["env_name"],
            },
        ),
        types.Tool(
            name="get_runbook",
            description="Return the trigger conditions and step summary for a named runbook.",
            inputSchema={
                "type": "object",
                "properties": {
                    "runbook_name": {
                        "type": "string",
                        "description": "Runbook name (e.g. 'deploy-sample-backend')",
                    }
                },
                "required": ["runbook_name"],
            },
        ),
        types.Tool(
            name="find_policy_violations",
            description=(
                "Given a service name and a description of a proposed change, identify "
                "which governing policies the change would violate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "Service to check (e.g. 'sample-backend-api')",
                    },
                    "proposed_change": {
                        "type": "string",
                        "description": "Plain-English description of the proposed change",
                    },
                },
                "required": ["service_name", "proposed_change"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool call handler
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[types.TextContent]:
    graph = load_graph()

    # Import the query functions from the HTTP server module so logic is shared
    from mcp_server import (
        find_policy_violations,
        get_environment_topology,
        get_runbook,
        get_service_context,
    )

    handlers = {
        "get_service_context": lambda: get_service_context(
            graph, arguments["service_name"]
        ),
        "get_environment_topology": lambda: get_environment_topology(
            graph, arguments["env_name"]
        ),
        "get_runbook": lambda: get_runbook(graph, arguments["runbook_name"]),
        "find_policy_violations": lambda: find_policy_violations(
            graph,
            arguments["service_name"],
            arguments["proposed_change"],
        ),
    }

    if name not in handlers:
        raise ValueError(f"Unknown tool: {name}")

    result = handlers[name]()
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def run_stdio():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


async def run_sse(port: int):
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    import uvicorn

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1],
                server.create_initialization_options(),
            )

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    print(f"Knowledge Graph MCP Server (SSE)")
    print(f"  Endpoint: http://localhost:{port}/sse")
    print(f"  MCP Inspector: npx @modelcontextprotocol/inspector")
    print(f"  Then connect to: http://localhost:{port}/sse")
    await uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")).serve()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    import asyncio
    if args.transport == "sse":
        asyncio.run(run_sse(args.port))
    else:
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
