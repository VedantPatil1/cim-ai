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
import base64
import difflib
import json
import os
import ssl
import urllib.request

from pydantic_ai import Agent

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GITEA_TOKEN       = os.environ["GITEA_TOKEN"]
GITEA_URL         = os.environ["GITEA_URL"].rstrip("/")
REPO              = os.environ["REPO"]           # owner/repo
PR_NUMBER         = os.environ["PR_NUMBER"]

OWNER, REPO_NAME = REPO.split("/", 1)

# SSL context for self-signed Gitea cert
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


def gitea_get(path: str) -> dict | list:
    url = f"{GITEA_URL}/api/v1{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"token {GITEA_TOKEN}"})
    with urllib.request.urlopen(req, context=_SSL, timeout=10) as resp:
        return json.loads(resp.read())


def get_file_content(path: str, ref: str) -> list[str]:
    """Return file lines at a given ref, or empty list if not found."""
    try:
        resp = gitea_get(f"/repos/{OWNER}/{REPO_NAME}/contents/{path}?ref={ref}")
        return base64.b64decode(resp["content"]).decode(errors="replace").splitlines(keepends=True)  # type: ignore[index]
    except Exception:
        return []


def fetch_pr_context() -> str:
    """Fetch PR metadata + unified diffs from Gitea API."""
    pr = gitea_get(f"/repos/{OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}")
    files = gitea_get(f"/repos/{OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}/files")

    base_sha = pr["base"]["sha"]  # type: ignore[index]
    head_sha = pr["head"]["sha"]  # type: ignore[index]

    file_sections = []
    for f in files:  # type: ignore[union-attr]
        fname = f["filename"]
        status = f["status"]

        old_lines = get_file_content(fname, base_sha) if status != "added" else []
        new_lines = get_file_content(fname, head_sha) if status != "removed" else []

        diff = "".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{fname}", tofile=f"b/{fname}", lineterm=""
        ))
        if not diff:
            diff = f"(file {status}, content unavailable)"

        file_sections.append(f"### {fname} ({status})\n```diff\n{diff}\n```")

    return (
        f"PR #{PR_NUMBER}: {pr['title']}\n"  # type: ignore[index]
        f"Author: {pr['user']['login']}\n"  # type: ignore[index]
        f"Branch: {pr['head']['label']} -> {pr['base']['label']}\n\n"  # type: ignore[index]
        + "\n\n".join(file_sections)
    )

SYSTEM_PROMPT = """\
You are a code review assistant for a GitOps infrastructure project.

You will be given the full diff of a pull request. Return a structured review in exactly this format:

## PR Analysis

**Risk Level:** LOW | MEDIUM | HIGH | CRITICAL

### Summary
One sentence describing what the PR does.

### Findings
Bullet list of specific issues or observations (security, code quality, correctness).

### GitOps Impact
Which components, environments, or policies are affected by this change.\
"""


def post_comment(body: str) -> None:
    """Post a comment to the PR via the Gitea API directly."""
    url = f"{GITEA_URL}/api/v1/repos/{OWNER}/{REPO_NAME}/issues/{PR_NUMBER}/comments"
    payload = json.dumps({"body": body}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"token {GITEA_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=_SSL, timeout=10) as resp:
        result = json.loads(resp.read())
        print(f"Comment posted: {result['html_url']}")


async def main() -> None:
    print(f"Fetching PR #{PR_NUMBER} from Gitea ...", flush=True)
    pr_context = fetch_pr_context()
    print(f"Got diff ({len(pr_context)} chars). Running analysis ...", flush=True)

    agent = Agent("claude-haiku-4-5", system_prompt=SYSTEM_PROMPT)

    prompt = (
        f"Review this pull request diff and return your structured analysis:\n\n"
        f"{pr_context}"
    )

    result = await agent.run(prompt)
    analysis = result.output

    print("\n--- Analysis ---")
    print(analysis)
    print("--- End ---\n")

    post_comment(analysis)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
