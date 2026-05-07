"""
Security Analyser Webhook Bridge
---------------------------------
Receives Gitea PR webhooks, fetches the diff, calls the Langflow security
analyser flow, and posts the result as a comment on the PR.

Usage:
    python webhook_bridge.py

Environment variables (or edit the CONFIG block below):
    GITEA_URL          https://cnoe.localtest.me:8443/gitea
    GITEA_TOKEN        Gitea API token (giteaAdmin or dev-agent)
    LANGFLOW_URL       http://localhost:7860
    LANGFLOW_FLOW_ID   UUID of the flow (printed on first run after import)
"""

import hashlib
import hmac
import json
import os
import ssl
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Configuration ────────────────────────────────────────────────────────────

GITEA_URL      = os.getenv("GITEA_URL",     "https://cnoe.localtest.me:8443/gitea")
GITEA_TOKEN    = os.getenv("GITEA_TOKEN",   "")          # set via env or fill in
OLLAMA_URL     = os.getenv("OLLAMA_URL",    "http://localhost:11434")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL",  "FenkoHQ/Foundation-Sec-8B:latest")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "cim-security-analyser")
LISTEN_PORT    = int(os.getenv("LISTEN_PORT", "7861"))

# ── SSL context (Gitea uses self-signed cert) ─────────────────────────────────

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _request(url, method="GET", payload=None, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        ctx = _ssl_ctx if url.startswith("https") else None
        with urllib.request.urlopen(req, context=ctx) as r:
            body = r.read()
            return json.loads(body) if body else {}, r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}"), e.code


# ── Gitea helpers ─────────────────────────────────────────────────────────────

def get_pr_diff(owner, repo, pr_number):
    """Returns the raw unified diff for a PR."""
    # Use the raw .diff endpoint — most reliable across Gitea versions
    url = f"{GITEA_URL}/api/v1/repos/{owner}/{repo}/pulls/{pr_number}.diff"
    headers = {"Authorization": f"token {GITEA_TOKEN}"}
    req = urllib.request.Request(url, headers={**{"Content-Type": "application/json"}, **headers})
    try:
        ctx = _ssl_ctx if url.startswith("https") else None
        with urllib.request.urlopen(req, context=ctx) as r:
            diff = r.read().decode("utf-8", errors="replace")
            # Cap to 300 lines to avoid token overflow
            lines = diff.splitlines()[:300]
            return "\n".join(lines) if lines else "(no changes)"
    except urllib.error.HTTPError as e:
        return f"(diff unavailable: {e.code})"


def post_pr_comment(owner, repo, pr_number, body):
    """Posts a comment on a Gitea PR."""
    url = f"{GITEA_URL}/api/v1/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {"Authorization": f"token {GITEA_TOKEN}"}
    result, status = _request(url, method="POST", payload={"body": body}, headers=headers)
    return status


# ── Ollama helper ─────────────────────────────────────────────────────────────


def run_security_analysis(diff, context):
    """Calls Ollama Foundation-Sec-8B via streaming chat and returns the analysis."""
    url = f"{OLLAMA_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a security analyst reviewing code changes in a GitOps repository. "
                    "Analyse diffs for security implications. Be concise and structured. "
                    "Always respond with: ## Risk Level, ## Summary, ## Findings, ## GitOps Impact."
                )
            },
            {
                "role": "user",
                "content": (
                    f"PR Context:\n{context}\n\n"
                    f"Code Diff:\n{diff}\n\n"
                    "Analyse the above diff for security issues. "
                    "Risk Level: CRITICAL / HIGH / MEDIUM / LOW / INFORMATIONAL. "
                    "List specific findings with Risk and Recommendation for each. "
                    "Note any GitOps pipeline or secrets handling concerns."
                )
            }
        ],
        "stream": True,
        "options": {"temperature": 0.1, "num_ctx": 8192}
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            chunks = []
            for line in r:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    content = obj.get("message", {}).get("content", "")
                    if content:
                        chunks.append(content)
                    if obj.get("done"):
                        break
                except json.JSONDecodeError:
                    pass
            return "".join(chunks) or "⚠️ Model returned empty analysis."
    except Exception as e:
        return f"⚠️ Ollama error: {e}"


# ── Webhook handler ───────────────────────────────────────────────────────────

def format_comment(analysis, pr_title, author, diff_stats):
    return f"""## Security Analysis

> Automated analysis by [Foundation-Sec-8B](https://huggingface.co/FenkoHQ/Foundation-Sec-8B) via Ollama
> PR: **{pr_title}** · Author: `{author}`
> Changes: {diff_stats}

---

{analysis}

---
<sub>🤖 Generated by CIM-AI Security Analyser · Foundation-Sec-8B via Ollama</sub>"""


class WebhookHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[bridge] {self.address_string()} {format % args}")

    def do_POST(self):
        if self.path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # Verify Gitea webhook signature
        sig = self.headers.get("X-Gitea-Signature", "")
        expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if sig and not hmac.compare_digest(sig, expected):
            print("[bridge] ⚠️  Signature mismatch — ignoring")
            self.send_response(401)
            self.end_headers()
            return

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        self.send_response(200)
        self.end_headers()

        # Only handle PR open/sync events
        action = payload.get("action", "")
        if action not in ("opened", "synchronize", "reopened"):
            print(f"[bridge] Skipping action: {action}")
            return

        pr      = payload.get("pull_request", {})
        repo    = payload.get("repository", {})
        owner   = repo.get("owner", {}).get("login", "")
        repo_name = repo.get("name", "")
        pr_num  = pr.get("number")
        pr_title = pr.get("title", "")
        author  = pr.get("user", {}).get("login", "")

        print(f"[bridge] PR #{pr_num} '{pr_title}' by {author} in {owner}/{repo_name}")

        # Fetch diff
        diff = get_pr_diff(owner, repo_name, pr_num)
        additions = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
        diff_stats = f"+{additions} -{deletions} lines"

        context = f"PR #{pr_num}: {pr_title}\nAuthor: {author}\nRepo: {owner}/{repo_name}"

        # Run analysis
        print(f"[bridge] Running security analysis ({diff_stats})...")
        analysis = run_security_analysis(diff, context)

        # Post comment
        comment = format_comment(analysis, pr_title, author, diff_stats)
        status = post_pr_comment(owner, repo_name, pr_num, comment)
        print(f"[bridge] Comment posted [{status}] on PR #{pr_num}")


def main():
    print(f"[bridge] Security Analyser Webhook Bridge")
    print(f"[bridge] Listening on :{LISTEN_PORT}/webhook")
    print(f"[bridge] Gitea:    {GITEA_URL}")
    print(f"[bridge] Ollama:   {OLLAMA_URL}")
    print(f"[bridge] Model:    {OLLAMA_MODEL}")
    server = HTTPServer(("0.0.0.0", LISTEN_PORT), WebhookHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
