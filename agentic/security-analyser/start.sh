#!/bin/bash
# Security Analyser Webhook Bridge — standalone fallback
# NOTE: superseded by .gitea/workflows/security-analysis.yaml in sample-backend-app.
# Use this only for manual/ad-hoc testing outside the CI pipeline.
export GITEA_URL="https://cnoe.localtest.me:8443/gitea"
export GITEA_TOKEN="65d9e714a11996d12d100044e54fdcf337988126"
export OLLAMA_URL="http://localhost:11434"
export OLLAMA_MODEL="FenkoHQ/Foundation-Sec-8B:latest"
export WEBHOOK_SECRET="cim-security-analyser"
export LISTEN_PORT="7861"
cd "$(dirname "$0")"
python3 webhook_bridge.py
