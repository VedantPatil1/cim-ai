## The Problem

Modern cloud-native platforms use IaC and GitOps to automate deployments reliably — but they cannot semantically reason about why a system is failing or whether a configuration aligns with business objectives. This leaves complex auditing and troubleshooting as manual, high-latency tasks.

LLM-based Multi-Agentic Systems are increasingly used to bridge this gap — but they introduce a new risk. As demonstrated by the July 2025 Replit incident, where an agentic assistant bypassed explicit "no-change" directives and deleted a production database, fully autonomous AI lacks the deterministic reliability required for infrastructure management. Without rigorous guardrails, LLM reasoning becomes a liability rather than an asset.

---

## The Proposed Solution

A controlled, auditable, and secure tooling-based agentic workflow system for standardised Control Plane Infrastructure — sitting between risky fully autonomous AI and tedious manual operations.

---

## Objectives

- Identify operational challenges in modern cloud-native platform engineering
- Implement reliable guardrails using security-by-design: A2A authentication, tool-based actions, human-in-the-loop authorisation, and Principle of Least Privilege
- Design agentic workflows operating as part of a standardised platform control plane
- Leverage LLM reasoning across infrastructure state, GitOps repos, IaC definitions, CI/CD pipelines, and operational documentation
- Implement controlled automation that prioritises stability, reliability, and traceability over full autonomy
- Compare proposed agentic workflows against generalised systems using metrics: Task Success Rate (TSR), Mean Time to Resolution (MTTR), and System Efficiency & Cost

---

## Scope

Design and develop secure, constrained, and specialised agentic workflows for Standardised Platform Control Planes. Implement a set of standards, rules, and practices for safe workflow execution. Evaluate against generalised Agentic AI using industry-standard metrics. Refine for context awareness and token efficiency aligned with real-world use cases.

---

## Timeline

| Phase | Period |
|---|---|
| Literature Review + Outline | Jan 31 – Feb 7, 2026 |
| Design & Development | Feb 7 – Mar 7, 2026 |
| Testing & User Evaluation | Mar 7 – Mar 15, 2026 |
| Packaging & Metric Evaluation | Mar 15 – Apr 15, 2026 |
| Documentation | Apr 15 – Apr 25, 2026 |
| Supervisor Review | Apr 25 – May 12, 2026 |
| Final Submission | Mar 26 – Mar 30, 2026 |

---

## Why This Matters

The infrastructure being built in this project — EKS, ArgoCD, GitOps pipelines, OIDC-based access, Terraform IaC — is not just a deployment platform. It is the experimental environment in which constrained agentic workflows operate. Every design decision — PoLP IAM, scoped tokens, auditable git commits, human promotion gates — directly maps to a security principle being researched and validated.