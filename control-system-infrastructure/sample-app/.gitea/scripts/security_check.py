#!/usr/bin/env python3
"""
Security analyser: diffs the PR, sends to Langflow (security-analysis flow),
posts the structured analysis as a Gitea PR comment.
"""
import datetime
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

GITEA_URL    = os.environ["GITEA_URL"].rstrip("/")
GITEA_TOKEN  = os.environ["GITEA_TOKEN"]
REPO         = os.environ["REPO"]           # e.g. giteaAdmin/sample-backend-app
PR_NUMBER    = os.environ["PR_NUMBER"]
BASE_SHA     = os.environ["BASE_SHA"]
HEAD_SHA     = os.environ["HEAD_SHA"]
LANGFLOW_URL = os.environ.get("LANGFLOW_URL", "http://host.docker.internal:7860")
FLOW_ID      = os.environ["FLOW_ID"]


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()


def get_diff():
    diff = run(["git", "diff", f"{BASE_SHA}...{HEAD_SHA}", "--", "*.py", "*.js", "*.ts", "*.go", "Dockerfile", "requirements.txt"])
    if not diff:
        diff = run(["git", "diff", f"{BASE_SHA}...{HEAD_SHA}"])
    # Truncate to avoid hitting model context limits
    return diff[:8000] if len(diff) > 8000 else diff


def call_langflow(diff):
    payload = json.dumps({
        "input_value": diff,
        "input_type": "text",
        "output_type": "text",
    }).encode()

    req = urllib.request.Request(
        f"{LANGFLOW_URL}/api/v1/run/{FLOW_ID}?stream=false",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
            # Navigate Langflow response: outputs[0].outputs[0].results.text.data.text
            text = data["outputs"][0]["outputs"][0]["results"]["text"]["data"]["text"]
            print(text)
            return text
    except urllib.error.URLError as e:
        return f"⚠️ Could not reach Langflow at `{LANGFLOW_URL}`: {e}\n\nEnsure Langflow is running with flow ID `{FLOW_ID}`."
    except (KeyError, IndexError) as e:
        return f"⚠️ Unexpected Langflow response structure: {e}"
    except Exception as e:
        return f"⚠️ Unexpected error calling Langflow: {e}"


def post_comment(body):
    url = f"{GITEA_URL}/api/v1/repos/{REPO}/issues/{PR_NUMBER}/comments"
    payload = json.dumps({"body": body}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"token {GITEA_TOKEN}",
        },
        method="POST",
    )
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            print(f"Comment posted (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        print(f"Failed to post comment: {e}", file=sys.stderr)


def main():
    print("=== Getting PR diff ===")
    diff = get_diff()
    if not diff:
        print("No diff found — skipping analysis.")
        post_comment("🔒 **Security Analysis**: No code changes detected in this PR.")
        return

    print(f"Diff size: {len(diff)} chars")
    print(f"=== Calling Langflow (flow: {FLOW_ID}) ===")
    analysis = call_langflow(diff)

    comment = f"""## 🔒 Security Analysis (qwen2.5-coder via Langflow)

{analysis}

---
*Automated analysis by [qwen2.5-coder:7b](https://ollama.com/library/qwen2.5-coder) via [Langflow](http://localhost:7860). Review findings carefully — this is AI-generated output.*
"""
    # Write token metrics — does not affect main logic
    try:
        metrics = {
            "workflow": "security-analysis",
            "model": "FenkoHQ/Foundation-Sec-8B (via Langflow/Ollama)",
            "pr": f"{REPO}#{PR_NUMBER}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "input_chars": len(diff),
            "output_chars": len(analysis),
            "estimated_input_tokens": len(diff) // 4,
            "estimated_output_tokens": len(analysis) // 4,
            "note": "token counts estimated (chars/4); exact counts unavailable through Langflow",
        }
        with open("/tmp/security-analysis-metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"Metrics: ~{metrics['estimated_input_tokens']} in / ~{metrics['estimated_output_tokens']} out tokens")
    except Exception as e:
        print(f"Warning: could not write metrics: {e}")

    print("=== Posting PR comment ===")
    post_comment(comment)


if __name__ == "__main__":
    main()
