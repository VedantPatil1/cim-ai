#!/usr/bin/env python3
from __future__ import annotations
"""
Infrastructure PR analysis — Terraform drift detection.

Fetches docs/infra-policy.md from this repo as the authoritative policy,
then asks Claude to identify violations in the PR diff and suggest remediation.

Required env vars:
  ANTHROPIC_API_KEY   — Claude API key
  GITEA_TOKEN         — Gitea token (secrets.GITHUB_TOKEN in workflow)
  GITEA_URL           — https://cnoe.localtest.me:8443/gitea
  REPO                — owner/repo
  PR_NUMBER           — PR number to analyse
"""

import base64
import datetime
import difflib
import json
import os
import ssl
import urllib.request

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


def gitea_get(path: str):
    url = f"{GITEA_URL}/api/v1{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"token {GITEA_TOKEN}"})
    with urllib.request.urlopen(req, context=_SSL, timeout=15) as r:
        return json.loads(r.read())


def fetch_file(owner: str, repo: str, path: str, ref: str = "main") -> str | None:
    try:
        url = f"{GITEA_URL}/api/v1/repos/{owner}/{repo}/contents/{path}?ref={ref}"
        req = urllib.request.Request(url, headers={"Authorization": f"token {GITEA_TOKEN}"})
        with urllib.request.urlopen(req, context=_SSL, timeout=15) as r:
            return base64.b64decode(json.loads(r.read())["content"]).decode(errors="replace")
    except Exception:
        return None


def get_file_lines(owner: str, repo: str, path: str, ref: str) -> list[str]:
    content = fetch_file(owner, repo, path, ref)
    return content.splitlines(keepends=True) if content else []


def fetch_pr_diff() -> tuple[str, str, str]:
    pr    = gitea_get(f"/repos/{OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}")
    files = gitea_get(f"/repos/{OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}/files")

    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]

    sections = []
    for f in files:
        fname  = f["filename"]
        status = f["status"]
        old = get_file_lines(OWNER, REPO_NAME, fname, base_sha) if status != "added"   else []
        new = get_file_lines(OWNER, REPO_NAME, fname, head_sha) if status != "removed" else []
        diff = "".join(difflib.unified_diff(old, new, fromfile=f"a/{fname}", tofile=f"b/{fname}", lineterm=""))
        sections.append(f"### {fname} ({status})\n```diff\n{diff or '(content unavailable)'}\n```")

    header = (
        f"PR #{PR_NUMBER}: {pr['title']}\n"
        f"Author: {pr['user']['login']}\n"
        f"Branch: {pr['head']['label']} -> {pr['base']['label']}\n\n"
        + "\n\n".join(sections)
    )
    return header, base_sha, head_sha


SYSTEM_PROMPT = """\
You are a senior cloud infrastructure security engineer and platform reviewer.

You will be given:
1. INFRASTRUCTURE POLICY — the authoritative constraints for all Terraform changes (ground truth).
2. PULL REQUEST DIFF — the proposed Terraform changes.

Your task is to identify POLICY VIOLATIONS and SECURITY RISKS in the diff.

Focus areas:
- Overly permissive network access (0.0.0.0/0 CIDR blocks, security groups)
- IAM: wildcard permissions, missing least-privilege, cluster-admin granted too broadly
- Missing encryption (at rest and in transit)
- Cluster configuration regressions (version downgrades, logging disabled)
- Unapproved resources or namespaces
- Missing required tags or outputs
- State backend misconfiguration

Return your review in EXACTLY this format:

## Infrastructure PR Analysis

**Risk Level:** LOW | MEDIUM | HIGH | CRITICAL

### Summary
One sentence describing what the PR changes.

### Policy Violations
For every clause violated, one bullet:
- **[Policy § Section]** Expected: `<what the policy says>` | Actual: `<what the diff does>`

If none: _No policy violations detected._

### Security Findings
For each security concern not already in policy violations:
- One bullet per finding with severity in brackets: [LOW] [MEDIUM] [HIGH] [CRITICAL]

### Suggested Remediation
For each violation above (same order), the corrected Terraform snippet. Label each with the file and policy section.

### Blast Radius
What breaks in production if this PR is merged as-is, and which environments or downstream systems are affected.\
"""


def post_comment(body: str) -> None:
    url     = f"{GITEA_URL}/api/v1/repos/{OWNER}/{REPO_NAME}/issues/{PR_NUMBER}/comments"
    payload = json.dumps({"body": body}).encode()
    req     = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"token {GITEA_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=_SSL, timeout=15) as r:
        result = json.loads(r.read())
        print(f"Comment posted: {result['html_url']}")


def main() -> None:
    print(f"Fetching PR #{PR_NUMBER} from {OWNER}/{REPO_NAME} ...", flush=True)
    pr_diff, base_sha, head_sha = fetch_pr_diff()
    print(f"Diff: {len(pr_diff)} chars (base={base_sha[:8]} head={head_sha[:8]})", flush=True)

    print("Fetching infrastructure policy ...", flush=True)
    policy = fetch_file(OWNER, REPO_NAME, "docs/infra-policy.md", ref="main")
    policy_text = f"## Infrastructure Policy\n\n{policy}" if policy else "(policy document not found)"
    print(f"Policy: {len(policy_text)} chars", flush=True)

    user_message = (
        "# Infrastructure Policy\n\n"
        + policy_text
        + "\n\n---\n\n"
        "# Pull Request Diff\n\n"
        + pr_diff
    )

    print("Running analysis ...", flush=True)
    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
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

    try:
        metrics = {
            "workflow": "infra-pr-analysis",
            "model": "claude-haiku-4-5-20251001",
            "pr": f"{REPO}#{PR_NUMBER}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
            "total_tokens": message.usage.input_tokens + message.usage.output_tokens,
            "estimated_cost_usd": round(
                (message.usage.input_tokens / 1_000_000) * 0.80
                + (message.usage.output_tokens / 1_000_000) * 4.00,
                6,
            ),
        }
        with open("/tmp/infra-analysis-metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"Metrics: {metrics['total_tokens']} tokens, ${metrics['estimated_cost_usd']:.6f} USD")
    except Exception as e:
        print(f"Warning: could not write metrics: {e}")

    post_comment(analysis)
    print("Done.")


if __name__ == "__main__":
    main()
