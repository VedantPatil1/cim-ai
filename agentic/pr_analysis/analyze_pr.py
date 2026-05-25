#!/usr/bin/env python3
"""
PR analysis agent — pydantic-ai + GitHub MCP server (pointed at Gitea).

The Gitea Actions workflow passes PR details and secrets as env vars.
This script uses the MCP server to read the PR diff and changed files,
analyses them with Claude, and posts a structured comment back to the PR.

Required env vars:
  ANTHROPIC_API_KEY   — Claude API key (stored as Gitea secret)
  GITEA_TOKEN         — Gitea personal access token (stored as Gitea secret)
  GITEA_URL           — Gitea base URL, e.g. https://cnoe.localtest.me:8443/gitea
  REPO                — owner/repo, e.g. giteaAdmin/sample-backend-app
  PR_NUMBER           — PR number to analyse
"""

import asyncio
import os


from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GITEA_TOKEN       = os.environ["GITEA_TOKEN"]
GITEA_URL         = os.environ["GITEA_URL"].rstrip("/")
REPO              = os.environ["REPO"]           # owner/repo
PR_NUMBER         = os.environ["PR_NUMBER"]

OWNER, REPO_NAME = REPO.split("/", 1)

SYSTEM_PROMPT = """\
You are a code review assistant for a GitOps infrastructure project.

When given a PR to review:
1. Use get_pull_request_files to retrieve the list of changed files.
2. Use get_file_contents to read each changed file (use the PR head branch as ref).
3. Analyse the changes for: security issues, blast radius, policy violations, and code quality.
4. Use add_issue_comment to post ONE structured comment to the PR with this format:

## PR Analysis

**Risk Level:** LOW | MEDIUM | HIGH | CRITICAL

### Summary
One sentence describing what the PR does.

### Findings
Bullet list of specific issues or observations.

### GitOps Impact
Which components, environments, or policies are affected.

Post the comment then stop. Do not summarise what you did.\
"""


async def main() -> None:
    # The GitHub MCP server speaks the MCP protocol over stdio.
    # Pointed at Gitea's GitHub-compatible API via GITHUB_API_URL.
    # NODE_TLS_REJECT_UNAUTHORIZED=0 is required for local self-signed certs.
    mcp_server = MCPServerStdio(
        "npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={
            **os.environ,
            "GITHUB_TOKEN":               GITEA_TOKEN,
            "GITHUB_API_URL":             f"{GITEA_URL}/api/v1",
            "NODE_TLS_REJECT_UNAUTHORIZED": "0",
        },
    )

    agent = Agent(
        "claude-haiku-4-5",
        mcp_servers=[mcp_server],
        system_prompt=SYSTEM_PROMPT,
    )

    prompt = (
        f"Review PR #{PR_NUMBER} in the repository {OWNER}/{REPO_NAME}. "
        f"Read the changed files, analyse them, and post a review comment to the PR."
    )

    print(f"Analysing PR #{PR_NUMBER} in {REPO} ...", flush=True)

    async with agent.run_mcp_servers():
        result = await agent.run(prompt)

    print("Done.")
    print(result.data)


if __name__ == "__main__":
    asyncio.run(main())
