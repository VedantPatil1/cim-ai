# Abstract

## The Problem

Modern cloud-native platforms use Infrastructure as Code and GitOps to automate deployments reliably — but they cannot semantically reason about *why* a system is failing or whether a configuration aligns with business objectives. This leaves complex auditing and troubleshooting as manual, high-latency tasks.

LLM-based agentic systems are increasingly used to bridge this gap — but they introduce a new risk class. In July 2025, an agentic coding assistant operating on a Replit user's behalf bypassed explicit *"no-change"* directives and deleted a production database. The safety constraint existed only as a natural language instruction. The agent reasoned past it.

Fully autonomous AI lacks the deterministic reliability required for infrastructure management. Without rigorous guardrails, LLM reasoning becomes a liability rather than an asset.

---

## The Proposed Solution

A **controlled, auditable, and secure tooling-based agentic workflow system** for standardised Control Plane Infrastructure — sitting between risky fully autonomous AI and tedious manual operations.

The system is built on a GitOps substrate where every agent action must be expressed as a Git commit. The Git history is the audit trail. An agent that cannot commit cannot act — and an agent that commits leaves an irrevocable, causally linked record of exactly what it did and why.

---

## Objectives

1. Identify operational challenges in cloud-native platform engineering that are viable targets for agentic AI assistance
2. Implement a secure control plane substrate that enforces hard mechanical constraints on agent behaviour — not instructed constraints
3. Define and implement a security model (R1–R6) covering agent identity, least privilege, HITL gates, audit trail, secret protection, and supply chain integrity
4. Design agentic workflows that operate within these constraints, leveraging LLM reasoning for contextual tasks while delegating enforcement to the tooling layer
5. Build a structured operational knowledge layer (knowledge graph) to give agents precise, queryable context rather than raw documentation
6. Evaluate the constrained system against a manual baseline and unrestricted AI using Task Success Rate, Mean Time to Resolution, and system efficiency metrics

---

## Key Architectural Decisions

**GitOps as the enforcement layer** — agents cannot call cloud APIs directly. All mutations flow through pull requests, which ArgoCD applies only after human review. The deployment mechanism *is* the audit mechanism.

**Two-boundary trust model** — Boundary 1 sits between the LLM and the tooling layer (authentication, token scoping, response sanitisation). Boundary 2 sits between the tooling layer and infrastructure (least privilege credentials, blast radius assessment, operation whitelisting). Both boundaries must be simultaneously compromised for a breach to have effect.

**Tool scoping over prompt scoping** — each agent identity receives only the MCP tools required for its specific function. A state reader cannot write. A staging promoter cannot touch production. Constraints are enforced at the credential and RBAC level, not in the system prompt.

**Extraction-on-commit knowledge graph** — operational knowledge (runbooks, service dependencies, environment topology) is extracted from source files on every relevant commit and stored as a versioned graph. Agents query typed graph endpoints rather than reading raw markdown — precision replaces retrieval.

---

## Mid-Semester Status

The control system infrastructure (Layer 1) is fully implemented and validated locally. The end-to-end GitOps pipeline — push to Gitea → CI builds and pushes image → ArgoCD reconciles → kind cluster updated — is live. The AWS production environment (EKS, ECR, VPC, ALB) is manually provisioned and operational. The security model is fully specified. Remaining work: Terraform IaC, Kyverno policy enforcement, the agentic layer, and evaluation.

See the [Progress Tracker](progress.md) for the full breakdown.
