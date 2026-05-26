#!/usr/bin/env python3
from __future__ import annotations
"""
PR analysis agent v3 — semantic drift detection with remediation and cross-repo awareness.

Fetches authoritative docs from both the app and gitops repos, inspects open PRs in the
companion repo for compounding violations, then asks Claude to:
  - identify semantic drift against the documented requirements
  - suggest the minimal corrective patch per violation
  - flag cross-repository interactions between this PR and open companion PRs

Required env vars:
  ANTHROPIC_API_KEY   — Claude API key
  GITEA_TOKEN         — Gitea token (secrets.GITHUB_TOKEN in workflow)
  GITEA_URL           — https://cnoe.localtest.me:8443/gitea
  REPO                — owner/repo of the repo containing this PR
  PR_NUMBER           — PR number to analyse
"""

import base64
import datetime
import difflib
import json
import os
import ssl
import urllib.request
import urllib.error

import anthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GITEA_TOKEN       = os.environ["GITEA_TOKEN"]
GITEA_URL         = os.environ["GITEA_URL"].rstrip("/")
REPO              = os.environ["REPO"]
PR_NUMBER         = os.environ["PR_NUMBER"]

OWNER, REPO_NAME = REPO.split("/", 1)

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Gitea helpers
# ---------------------------------------------------------------------------

def gitea_get(path: str):
    url = f"{GITEA_URL}/api/v1{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"token {GITEA_TOKEN}"})
    with urllib.request.urlopen(req, context=_SSL, timeout=15) as resp:
        return json.loads(resp.read())


def gitea_get_safe(path: str):
    try:
        return gitea_get(path)
    except Exception:
        pass
    # GITHUB_TOKEN is scoped to current repo; fall back to unauthenticated for public repos
    try:
        url = f"{GITEA_URL}/api/v1{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=_SSL, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def fetch_file(owner: str, repo: str, path: str, ref: str = "main") -> str | None:
    """Return file content as a string, or None if not found."""
    try:
        url = f"{GITEA_URL}/api/v1/repos/{owner}/{repo}/contents/{path}?ref={ref}"
        req = urllib.request.Request(url, headers={"Authorization": f"token {GITEA_TOKEN}"})
        with urllib.request.urlopen(req, context=_SSL, timeout=15) as resp:
            data = json.loads(resp.read())
        return base64.b64decode(data["content"]).decode(errors="replace")
    except Exception:
        return None


def get_file_lines(owner: str, repo: str, path: str, ref: str) -> list[str]:
    content = fetch_file(owner, repo, path, ref)
    return content.splitlines(keepends=True) if content else []


def _companion_repos() -> tuple[str, str]:
    """Return (app_repo_name, gitops_repo_name) for this repo."""
    if "-gitops" in REPO_NAME:
        return REPO_NAME.replace("-gitops", "-app"), REPO_NAME
    if "-app" in REPO_NAME:
        return REPO_NAME, REPO_NAME.replace("-app", "-gitops")
    return REPO_NAME, REPO_NAME + "-gitops"


# ---------------------------------------------------------------------------
# PR diff
# ---------------------------------------------------------------------------

def fetch_pr_diff() -> tuple[str, str, str]:
    """Returns (formatted_diff, base_sha, head_sha)."""
    pr    = gitea_get(f"/repos/{OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}")
    files = gitea_get(f"/repos/{OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}/files")

    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]

    file_sections = []
    for f in files:
        fname  = f["filename"]
        status = f["status"]

        old_lines = get_file_lines(OWNER, REPO_NAME, fname, base_sha) if status != "added"   else []
        new_lines = get_file_lines(OWNER, REPO_NAME, fname, head_sha) if status != "removed" else []

        diff = "".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{fname}", tofile=f"b/{fname}", lineterm=""
        ))
        if not diff:
            diff = f"(file {status}, content unavailable)"

        file_sections.append(f"### {fname} ({status})\n```diff\n{diff}\n```")

    header = (
        f"PR #{PR_NUMBER}: {pr['title']}\n"
        f"Author: {pr['user']['login']}\n"
        f"Branch: {pr['head']['label']} -> {pr['base']['label']}\n\n"
        + "\n\n".join(file_sections)
    )
    return header, base_sha, head_sha


# ---------------------------------------------------------------------------
# Policy documents
# ---------------------------------------------------------------------------

def fetch_policy_docs() -> str:
    app_repo, gitops_repo = _companion_repos()
    sections = []

    api_req = fetch_file(OWNER, app_repo, "docs/api-requirements.md", ref="main")
    if api_req:
        sections.append(f"## API Requirements ({app_repo}/docs/api-requirements.md)\n\n{api_req}")

    deploy_policy = fetch_file(OWNER, gitops_repo, "docs/deployment-policy.md", ref="main")
    if deploy_policy:
        sections.append(f"## Deployment Policy ({gitops_repo}/docs/deployment-policy.md)\n\n{deploy_policy}")

    return "\n\n---\n\n".join(sections) if sections else "(no authoritative documentation found)"


# ---------------------------------------------------------------------------
# Cross-repo awareness: open PRs in the companion repo
# ---------------------------------------------------------------------------

def fetch_companion_prs() -> str:
    """Return a structured summary of open PRs in the companion repo."""
    app_repo, gitops_repo = _companion_repos()
    companion = gitops_repo if REPO_NAME == app_repo else app_repo

    prs = gitea_get_safe(f"/repos/{OWNER}/{companion}/pulls?state=open&limit=10")
    if not prs:
        return ""

    lines = [f"## Open PRs in companion repo ({companion})\n"]
    for pr in prs:
        num   = pr["number"]
        title = pr["title"]
        author = pr["user"]["login"]
        branch = pr["head"]["label"]

        # fetch the files this PR touches
        files = gitea_get_safe(f"/repos/{OWNER}/{companion}/pulls/{num}/files") or []
        changed = [f["filename"] for f in files]

        # fetch a short diff snippet for context (first changed file only)
        snippets = []
        for f in files[:3]:
            fname  = f["filename"]
            status = f["status"]
            base   = pr["base"]["sha"]
            head   = pr["head"]["sha"]
            old    = get_file_lines(OWNER, companion, fname, base) if status != "added"   else []
            new    = get_file_lines(OWNER, companion, fname, head) if status != "removed" else []
            d = "".join(difflib.unified_diff(old, new, fromfile=f"a/{fname}", tofile=f"b/{fname}", lineterm=""))
            if d:
                snippets.append(f"#### {fname}\n```diff\n{d[:1500]}\n```")

        lines.append(
            f"### PR #{num}: {title}\n"
            f"Author: {author} | Branch: {branch}\n"
            f"Files changed: {', '.join(changed)}\n\n"
            + ("\n\n".join(snippets) if snippets else "(diff unavailable)")
        )

    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a senior code reviewer and platform engineer for a GitOps infrastructure project.

You will be given:
1. AUTHORITATIVE DOCUMENTATION — the API requirements spec and deployment policy (ground truth).
2. THIS PULL REQUEST DIFF — the changes being proposed.
3. OPEN PRs IN THE COMPANION REPO — diffs of currently open pull requests in the paired
   repository (app ↔ gitops). Use these to identify compounding effects: situations where
   two open PRs together create a worse outcome than either alone.

Your primary task is to detect SEMANTIC DRIFT and provide actionable remediation.

Return your review in EXACTLY this format (no extra sections, no preamble):

## PR Analysis

**Risk Level:** LOW | MEDIUM | HIGH | CRITICAL

### Summary
One sentence describing what the PR does.

### Semantic Drift
For every documented requirement or policy clause this PR violates, one bullet:
- **[Document § Section]** Expected: `<what the doc says>` | Actual: `<what the PR does>`

If none: _No semantic drift detected._

### Suggested Remediation
For each violation above (in the same order), provide the minimal corrected code or
configuration that brings it into compliance. Use a fenced code block per fix, labelled
with the file and the section header matching the violation above. Keep fixes surgical —
change only what is needed.

### Cross-Repository Impact
Examine the open PRs in the companion repo. For each one that interacts with a violation
in this PR, write one bullet:
- **[Companion PR #N: title]** How the two PRs combine to create a compounding effect.

If no companion PRs were provided or none interact with the violations:
_No cross-repository compounding identified._

### Findings
Bullet list of additional issues not already covered above: security, correctness,
code quality, test coverage gaps.

### GitOps Impact
What would break in production if this PR were merged as-is, and which components,
environments, or downstream systems are affected.\
"""


# ---------------------------------------------------------------------------
# Post comment
# ---------------------------------------------------------------------------

def post_comment(body: str) -> None:
    url     = f"{GITEA_URL}/api/v1/repos/{OWNER}/{REPO_NAME}/issues/{PR_NUMBER}/comments"
    payload = json.dumps({"body": body}).encode()
    req     = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"token {GITEA_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=_SSL, timeout=15) as resp:
        result = json.loads(resp.read())
        print(f"Comment posted: {result['html_url']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Fetching PR #{PR_NUMBER} from {OWNER}/{REPO_NAME} ...", flush=True)
    pr_diff, base_sha, head_sha = fetch_pr_diff()
    print(f"Diff: {len(pr_diff)} chars (base={base_sha[:8]} head={head_sha[:8]})", flush=True)

    print("Fetching policy documents ...", flush=True)
    policy_docs = fetch_policy_docs()
    print(f"Docs: {len(policy_docs)} chars", flush=True)

    print("Fetching companion repo open PRs ...", flush=True)
    companion_prs = fetch_companion_prs()
    print(f"Companion PRs: {len(companion_prs)} chars", flush=True)

    user_message = (
        "# Authoritative Documentation\n\n"
        + policy_docs
        + "\n\n---\n\n"
        "# Pull Request Diff\n\n"
        + pr_diff
        + (("\n\n---\n\n" + companion_prs) if companion_prs else "")
    )

    print("Running analysis ...", flush=True)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    analysis = message.content[0].text

    print("\n--- Analysis ---")
    print(analysis)
    print("--- End ---\n")

    # Write token metrics — does not affect main logic
    try:
        metrics = {
            "workflow": "pr-analysis",
            "model": "claude-haiku-4-5-20251001",
            "pr": f"{REPO}#{PR_NUMBER}",
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
            "total_tokens": message.usage.input_tokens + message.usage.output_tokens,
            "estimated_cost_usd": round(
                (message.usage.input_tokens / 1_000_000) * 0.80
                + (message.usage.output_tokens / 1_000_000) * 4.00,
                6,
            ),
        }
        with open("/tmp/pr-analysis-metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"Metrics: {metrics['total_tokens']} tokens, ${metrics['estimated_cost_usd']:.6f} USD")
    except Exception as e:
        print(f"Warning: could not write metrics: {e}")

    post_comment(analysis)
    print("Done.")


if __name__ == "__main__":
    main()
