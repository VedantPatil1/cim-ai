#!/usr/bin/env python3
"""
Call the Langflow Change Impact Analyzer flow with a PR diff
and post the result as a Gitea PR comment.

Usage: python3 change_impact.py <pr_number> <diff_file>
"""
import json
import sys
import urllib.request
import os

LANGFLOW_URL = os.environ.get("LANGFLOW_URL", "http://host.docker.internal:7860")
FLOW_ID = os.environ.get("CHANGE_IMPACT_FLOW_ID", "b908e9c2-340d-454b-9e1b-ab356f66cceb")

GITEA_URL = os.environ.get("GITEA_URL", "http://my-gitea-http.gitea.svc.cluster.local:3000")
GITEA_TOKEN = os.environ.get("GITEA_TOKEN", "")
GITEA_REPO = os.environ.get("GITHUB_REPOSITORY", "")


def langflow_token():
    req = urllib.request.Request(f"{LANGFLOW_URL}/api/v1/auto_login")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["access_token"]


def run_flow(token: str, diff: str) -> str:
    payload = json.dumps({
        "input_value": diff,
        "input_type": "chat",
        "output_type": "chat",
    }).encode()
    req = urllib.request.Request(
        f"{LANGFLOW_URL}/api/v1/run/{FLOW_ID}?stream=false",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    return data["outputs"][0]["outputs"][0]["results"]["text"]["data"]["text"]


def post_comment(pr: int, body: str):
    if not GITEA_TOKEN or not GITEA_REPO:
        print("No GITEA_TOKEN or GITHUB_REPOSITORY set — skipping comment")
        return
    owner, repo = GITEA_REPO.split("/", 1)
    payload = json.dumps({"body": body}).encode()
    req = urllib.request.Request(
        f"{GITEA_URL}/api/v1/repos/{owner}/{repo}/issues/{pr}/comments",
        data=payload,
        headers={
            "Authorization": f"token {GITEA_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <pr_number> <diff_file>")
        sys.exit(1)

    pr = int(sys.argv[1])
    diff_file = sys.argv[2]

    with open(diff_file) as f:
        diff = f.read()

    if not diff.strip():
        print("Empty diff — nothing to analyse")
        sys.exit(0)

    # Truncate to avoid Ollama context limits
    diff = diff[:8000]

    print(f"Calling Change Impact Analyzer (flow {FLOW_ID}) ...")
    try:
        token = langflow_token()
        result = run_flow(token, diff)
    except Exception as e:
        result = f"Change impact analysis unavailable: {e}"
        print(f"WARNING: {e}")

    print("\n--- Change Impact Analysis ---")
    print(result)
    print("--- End ---\n")

    comment = f"""## Change Impact Analysis

**Flow:** Change Impact Analyzer (Langflow)
**Model:** qwen2.5-coder:7b via Ollama

{result}

---
*Automated analysis by the CIM-AI agentic layer. Review before merging.*"""

    post_comment(pr, comment)
    print(f"Comment posted to PR #{pr}")


if __name__ == "__main__":
    main()
