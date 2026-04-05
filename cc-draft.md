# Agentic AI for Cloud Infrastructure Management using GitOps
## Mid-Semester Dissertation Report

---

**Student Name:** Vedant Patil
**BITS ID:** 2024MT03034
**Degree Program:** M.Tech (Software Systems)
**Research Area:** Agentic AI / Cloud Infrastructure / Platform Engineering

**Institution:** Birla Institute of Technology & Science, Pilani
**Work Integrated Learning Programmes (WILP) Division**
**Semester:** 4th Semester, Academic Year 2025–2026

---

## Contents

1. Broad Area of Work
2. Problem Statement and Motivation
3. Objectives
4. Scope of Work
5. Background and Literature Review
6. System Design and Architecture
7. Work Completed (Mid-Semester Progress)
8. Remaining Work
9. Project Timeline
10. References

---

## 1. Broad Area of Work

This dissertation sits at the intersection of three active research and engineering domains: **cloud platform engineering**, **GitOps-based infrastructure automation**, and **agentic AI systems**. The central question being investigated is: *how can large language model (LLM)-driven agents be introduced into a production cloud infrastructure management workflow in a manner that is safe, auditable, and measurably reliable?*

The project addresses a practical gap in modern platform engineering. While Infrastructure as Code (IaC) tools such as Terraform and GitOps operators such as ArgoCD have significantly reduced the manual burden of infrastructure provisioning and application deployment, they provide no semantic understanding of operational state. Troubleshooting degraded services, reasoning about configuration drift, and correlating a deployment failure with a root cause remain fundamentally manual, high-latency tasks. Agentic AI systems offer the potential to close this gap — but only if the risks introduced by non-deterministic LLM reasoning are adequately constrained.

The broad research areas this work draws from include:

- **Distributed systems and cloud infrastructure:** container orchestration (Kubernetes/EKS), infrastructure-as-code (Terraform), container image management (ECR)
- **GitOps and continuous delivery:** declarative deployment models, reconciliation loops (ArgoCD), CI/CD pipeline design
- **AI safety and agentic systems:** tool-use constraints, human-in-the-loop design, blast radius analysis, prompt injection defence
- **Knowledge representation:** structured extraction from heterogeneous sources, graph data models, agent query interfaces

---

## 2. Problem Statement and Motivation

### 2.1 The Operational Gap in Cloud-Native Infrastructure

Cloud-native platform engineering has matured considerably over the past decade. Declarative infrastructure tools allow teams to express desired system state as code, and GitOps operators continuously reconcile actual cluster state with that declared intent. The result is a deployment model that is reproducible, auditable at the infrastructure level, and resilient to manual drift.

However, this automation covers the *execution* of well-defined desired states — not the reasoning required to *determine* what the desired state should be when something goes wrong. When a deployment fails, an engineer must manually inspect logs, correlate events across systems, cross-reference runbooks, and determine a remediation path. This process is time-consuming, error-prone, and creates an operational bottleneck that infrastructure automation alone cannot address.

### 2.2 The Emerging Role of Agentic AI in Infrastructure Operations

Large language model-based agents are increasingly being applied to operational tasks: interpreting logs, generating configuration changes, querying infrastructure state, and proposing remediation steps. Frameworks such as LangGraph and CNOE's CAIPE (Community AI Platform Engineering) reference implementation demonstrate that agentic systems can meaningfully assist platform engineers in day-to-day operations.

The key advantage of a tool-using LLM agent over a rule-based automation is its capacity for *contextual reasoning* — the ability to combine information from disparate sources (log output, IaC definitions, deployment history, runbooks) and reason about causal relationships that no individual source makes explicit.

### 2.3 The Risk of Unconstrained Agency

However, this capability introduces a class of risks that traditional automation does not. Unlike deterministic scripts, LLM agents can misinterpret ambiguous instructions, be manipulated by adversarial content in their context (prompt injection), execute sequences of individually valid actions that combine into a harmful outcome, or simply make confident mistakes.

A concrete, documented example of this failure mode occurred in July 2025, when an agentic coding assistant operating on behalf of a Replit user bypassed an explicit "no changes" instruction from the user and deleted a production database. The agent's reasoning led it to conclude that the deletion was necessary for the task at hand, overriding the human's stated constraint. The constraint existed only as a natural language instruction — not as an enforced mechanical limit — and the agent reasoned past it.

This incident illustrates the central design challenge for agentic infrastructure systems: **LLM reasoning must not be the sole enforcement mechanism for safety constraints**. An agent that can reason its way past a safety boundary provides no meaningful safety guarantee.

### 2.4 Research Gap

Existing work on agentic AI in operations (AIOps) tends to focus on the capability dimension: what tasks can agents perform, what LLMs perform best, what prompt engineering techniques improve output quality. The safety, auditability, and reliability dimensions — particularly as they apply to an agent operating on live cloud infrastructure — are less thoroughly addressed in the literature. This project explicitly targets that gap.

---

## 3. Objectives

The dissertation pursues the following concrete objectives:

1. **Identify and characterise operational challenges** in modern cloud-native platform engineering that are suitable targets for agentic AI assistance.

2. **Design and implement a secure control plane substrate** — a GitOps-based infrastructure layer that provides hard enforcement boundaries for agent operations, rather than relying on instructed behaviour.

3. **Define a security model for agentic access** to infrastructure, including agent identity isolation, least-privilege scoping, human-in-the-loop gate design, audit trail requirements, secret protection, and supply chain controls.

4. **Design agentic workflows** that operate within the boundaries defined by the security model, leveraging LLM reasoning for contextual tasks while delegating enforcement to the tooling layer.

5. **Implement a structured operational knowledge layer** that provides agents with precise, queryable context about infrastructure state — replacing ad-hoc context injection with a maintained knowledge graph.

6. **Evaluate the proposed system** against generalised agentic AI using industry-standard metrics: Task Success Rate (TSR), Mean Time to Resolution (MTTR), and overall system efficiency.

---

## 4. Scope of Work

The scope is deliberately bounded to maintain research rigour:

**In scope:**
- Design, implementation, and evaluation of a secure GitOps-based control plane for agentic operations
- A single, well-specified target application (FastAPI backend service) deployed via the GitOps workflow as a concrete test case
- Security model covering agent-repository and agent-infrastructure interaction
- Constrained agentic workflows evaluated against a manual operations baseline

**Out of scope:**
- General-purpose conversational AI assistants (the focus is on structured, workflow-scoped agents, not open-ended chat)
- Multi-tenant or enterprise-scale deployment (the research validates principles; production scale is a follow-on concern)
- LLM training or fine-tuning (the system uses the Claude API as a reasoning backend without model modification)

---

## 5. Background and Literature Review

### 5.1 GitOps and Declarative Infrastructure Management

GitOps is a deployment practice in which Git repositories serve as the single source of truth for system state, and automated operators continuously reconcile the running environment with the declared desired state. First formalised by Weaveworks (2017) and standardised by the CNCF GitOps Working Group, the model provides inherent auditability (every change is a git commit) and reproducibility (the declared state can be re-applied to recreate any environment).

ArgoCD is the dominant open-source GitOps operator for Kubernetes environments. It polls a configured Git repository for changes to Kubernetes manifests and applies detected diffs to the target cluster. The operator pattern means that human operators and automated systems interact with infrastructure by modifying Git — never by calling Kubernetes APIs directly. This architectural constraint is directly relevant to agentic safety: it provides a natural enforcement point for human review before any change reaches a running cluster.

### 5.2 Infrastructure as Code

Terraform (HashiCorp, 2014) introduced the concept of declarative cloud resource provisioning via a domain-specific language (HCL). Resources are declared in configuration files; Terraform computes the difference between declared and actual state and applies only the necessary changes. The model provides idempotency, reproducibility, and an explicit state record. For this project, Terraform is the mandatory mechanism for provisioning the AWS target infrastructure (EKS, ECR, VPC, IAM) — it is what elevates the system from Kubernetes workload management to genuine cloud infrastructure management.

### 5.3 Internal Developer Platforms and the CNOE Reference Architecture

The Cloud Native Operational Excellence (CNOE) project provides reference architectures and tooling for building Internal Developer Platforms (IDPs). CNOE's `idpbuilder` tool bootstraps a complete GitOps IDP — Kubernetes (kind), Git server (Gitea), GitOps operator (ArgoCD), and ingress — from a single CLI command, solving the bootstrapping problem that typically requires extensive manual wiring.

CNOE's CAIPE (Community AI Platform Engineering) framework extends this substrate with an agentic layer: a multi-agent system where a supervisor orchestrates domain-specific sub-agents (ArgoCD agent, GitHub agent, Jira agent, etc.), each communicating with platform APIs via the Model Context Protocol (MCP). CAIPE is the reference implementation that this dissertation evaluates and builds upon.

### 5.4 Agentic AI Systems and Tool-Use

The tool-use paradigm in LLM-based systems (introduced by OpenAI function calling and standardised in the MCP specification by Anthropic) allows LLMs to call predefined functions rather than generating free-form text for all outputs. This is significant for infrastructure safety: if an agent can only perform actions by invoking a defined tool, and tools can be scoped and audited independently of the model, then the model's reasoning cannot exceed the permission set of its tools.

LangGraph (LangChain, 2024) provides a Python framework for implementing stateful, cyclic agent workflows as directed graphs. Unlike conversational frameworks that execute linearly, LangGraph supports conditional edges, state persistence, and human-in-the-loop interruption — properties directly required for infrastructure workflows where certain state transitions must await human approval before proceeding.

### 5.5 Security Considerations for Agentic Systems

The literature on AI safety for production systems identifies several distinct failure modes relevant to this work:

- **Instruction-following failures:** agents that reason past stated constraints (as in the Replit incident)
- **Prompt injection:** adversarial instructions embedded in content read by the agent (log files, commit messages, documentation) that redirect agent behaviour
- **Capability amplification:** individually safe tool invocations that chain into outcomes with disproportionate blast radius
- **Audit evasion:** agentic actions that do not generate an attributable record

The principal-agent framework from economics is a useful lens: the operator (human) has goals that may not be perfectly communicated to the agent, and the agent may take actions misaligned with those goals due to incomplete information or misinterpretation. Security-conscious system design must constrain the *action space* of the agent, not merely improve the clarity of instructions.

### 5.6 Model Context Protocol (MCP)

MCP (Anthropic, 2024) is an open protocol for defining structured tool interfaces for LLM agents. An MCP server exposes a set of typed tools with defined schemas; the LLM can invoke these tools and receive structured responses. The protocol's significance for security is that it creates a natural enforcement boundary: MCP servers can validate, scope, and log all agent requests, providing control that exists entirely outside the LLM's reasoning loop.

---

## 6. System Design and Architecture

### 6.1 Priority Model

The entire system design is governed by a strict priority ordering:

```
Security      ── absolute boundary — defines what the system may do at all
Reliability   ── the rate at which permitted operations succeed
Capability    ── the breadth of supported use cases
```

Security is not a design guideline — it is a hard constraint. It is enforced mechanically at the tooling layer, not via model instructions. Reliability is the operational measure: for any permitted operation, the system must complete it at a measurable success rate. Capability is intentionally deferred: no new use cases are introduced until existing ones are both secure and reliably performant. This ordering deliberately trades breadth for trustworthiness.

### 6.2 Two-Layer Infrastructure Architecture

The project maintains a strict separation between two infrastructure concerns that must not be conflated:

**Layer 1 — Control System Infrastructure (Management Plane)**

This is the toolchain that enables GitOps to function. It includes the Git server (Gitea), the CI runner (Gitea Actions), and the GitOps operator (ArgoCD). This layer is bootstrapped using CNOE's `idpbuilder` tool and is not managed by Terraform — it is the platform, not the target.

**Layer 2 — Target Infrastructure and Deployment (Application Plane)**

This is the cloud infrastructure on which the application runs. It includes AWS EKS (Kubernetes runtime), AWS ECR (container image registry), VPC networking, and IAM access controls. This layer is provisioned exclusively via Terraform and managed via GitOps. It is what gives the phrase "cloud infrastructure management" its substance.

The two layers are connected by a GitOps bridge: code changes flow through Gitea and Gitea Actions (Layer 1) to build and push container images to ECR, update Kubernetes manifests in the GitOps repository, and trigger ArgoCD (Layer 1) to reconcile the running state of the EKS cluster (Layer 2).

### 6.3 The GitOps Invariant

A core design rule governs the entire system: **every change to infrastructure, deployment, CI/CD pipeline, or policy must be expressed as a commit to a Git repository**. There are no out-of-band mutations. This rule applies to human operators and AI agents alike. Its significance is threefold:

1. **Auditability:** the Git history is a tamper-resistant, causally linked record of every change
2. **Review gates:** pull requests create natural enforcement points for human approval before changes reach production
3. **Reversibility:** any change can be reverted by reverting the commit

For agentic operations, this invariant means that an agent proposing an infrastructure change must express it as a commit or pull request. The agent never calls cloud APIs directly. This architectural constraint eliminates an entire class of direct-access risks without requiring any runtime enforcement mechanism within the agent.

### 6.4 Security Model (R1–R6)

Six distinct security requirements govern how agents interact with the system. Each is implemented as a hard mechanical control, not an instructed behaviour:

| Requirement | What it prevents | Implementation approach |
|---|---|---|
| **R1 — Agent identity isolation** | A compromised credential exposes all agent operations | Fine-grained PATs (Phase 1) → GitHub Apps (Phase 2) |
| **R2 — Least privilege** | Agent performs operations outside its designated scope | Token scoping + repository rulesets + CODEOWNERS |
| **R3 — Human-in-the-loop gates** | Agent merges or deploys without human review | Branch protection merge gates + environment protection deployment gates |
| **R4 — Audit trail** | Agent actions cannot be traced after the fact | Signed commits + structured commit message patterns (ruleset-enforced) |
| **R5 — Secret protection** | Credentials committed to or leaked from the repository | gitleaks on push/PR (hard gate — blocks merge on detection) |
| **R6 — Supply chain integrity** | Compromised CI dependencies execute arbitrary code | Dependency review + SHA-pinned actions + required workflows |

Controls are classified by hardness: a **hard** control mechanically prevents the unsafe action; a **soft** control records or alerts after the fact. Hard controls are preferred. For example, repository rulesets blocking a merge (hard) is preferred over an audit log that records an unauthorised merge (soft).

### 6.5 Two-Boundary Trust Model

The agentic system (to be implemented in Phase 2) will operate through two explicit trust boundaries:

**Boundary 1 — between LLM and tooling layer:** Validates user identity, generates time-scoped tokens for the specific request, applies rate limiting, and filters all responses before returning them to the model. Raw infrastructure content (logs, manifests, stack traces) is sanitised before inclusion in LLM context — preventing prompt injection from content that agents necessarily read.

**Boundary 2 — between tooling layer and infrastructure:** Enforces least privilege at the credential level, validates all write operations against a pre-approved whitelist, assesses blast radius before execution, and logs all operations to CloudTrail. No infrastructure call is made with credentials broader than required for that specific operation.

### 6.6 Operational Knowledge Graph

Agents require structured, precise context about the infrastructure they operate on. Two naive alternatives — RAG (vector search over documentation) and raw documentation injection — are inadequate: the former returns ranked probabilistic matches where exact structural answers are needed; the latter is expensive and noisy.

The design uses an **extraction-on-commit** approach: a Gitea Actions pipeline extracts structured entities and relationships from changed files on every push, building a graph of the operational structure of the system. Agents query this graph via a read-only MCP server, not by reading raw text.

The graph captures nodes of type `Service`, `Component`, `Repository`, `Environment`, `Policy`, `Runbook`, and `Team`, connected by typed relationships (`DEPENDS_ON`, `OWNS`, `DEPLOYS_TO`, `GOVERNED_BY`, `DOCUMENTED_BY`, `PROVISIONS`). Extraction sources include Terraform files, Kubernetes manifests, ArgoCD application definitions, and structured documentation.

Phase 1 stores the graph as a versioned JSON file in Git — fully auditable, no external services required. Phase 2 transitions to Kuzu (an embedded graph database) for Cypher-style query support while retaining the JSON file as the source of truth.

---

## 7. Work Completed (Mid-Semester Progress)

### 7.1 Control System Infrastructure Bootstrap

The CNOE idpbuilder stack is fully implemented and reproducibly bootstrapped via a single command. The stack deploys a complete Internal Developer Platform on a local kind cluster, including:

- **Gitea** — in-cluster Git server serving as the single source of truth for all code and configuration
- **Gitea Actions** — CI runner executing pipeline workflows on push events, enabled via a custom configuration override
- **ArgoCD** — GitOps operator reconciling cluster state with declared manifests

The bootstrap is designed so that the local setup mirrors the production (AWS EKS) configuration exactly — only the backing infrastructure endpoints differ. This ensures that workflows validated locally translate directly to production without redesign.

### 7.2 Three CNOE Packages Implemented

Three custom CNOE packages have been implemented and integrated into the bootstrap command:

**Package 1: `gitea-runner`**

An in-cluster Gitea Actions runner implemented as a Kubernetes Deployment. The runner uses Docker-in-Docker (dind) for CI jobs that build container images. Two init containers handle credential retrieval and runner registration automatically, reading credentials from an existing Kubernetes secret via cross-namespace RBAC. Runner configuration is persisted to a PVC to survive pod restarts without re-registration. The runner registers with labels `ubuntu-latest` and `sandbox` to accept standard GitHub Actions-compatible workflows.

**Package 2: `platform-workflows`**

A CronJob that runs every 15 minutes and synchronises two workflow definition files into every Gitea repository via the Gitea Contents API:

- `secret-scan.yaml`: runs gitleaks against the full Git history on every push and pull request, exiting non-zero if any credential pattern is detected
- `sandbox-lifecycle.yaml`: detects a `.cim/sandbox.yaml` marker file in a repository and calls the ArgoCD API to create an ApplicationSet for that repository

This pattern mirrors GitHub's org-level "required workflows" capability — which Gitea natively lacks — reimplemented using Gitea's REST API. The CronJob enforces that the workflows remain installed and up-to-date; individual repositories cannot permanently remove them.

**Package 3: `sandbox-environments`**

An ArgoCD-managed package that provisions the ArgoCD infrastructure required for ephemeral sandbox environments:

- An ArgoCD `AppProject` named `sandbox` that restricts all sandbox applications to `sandbox-*` namespaces, blocking cluster-level resources and preventing sandbox applications from affecting production namespaces
- A PostSync Job that patches ArgoCD's configuration to add a `sandbox-agent` local user with ApplicationSet-only RBAC (`role:sandbox-manager`)
- Placeholder infrastructure for the Gitea admin token required by the ApplicationSet PR generator

When a GitOps repository contains a `.cim/sandbox.yaml` file and a developer opens a pull request, an ArgoCD ApplicationSet is created that polls Gitea for open PRs. For each open PR, a dedicated ArgoCD Application is created that deploys the PR branch's manifests to a unique `sandbox-<repo>-pr-<N>` namespace. The Application is pruned automatically when the PR is closed, cleaning up all deployed resources. This gives reviewers — and eventually AI agents — a live environment representing the proposed change, without any manual provisioning overhead.

### 7.3 Production Infrastructure (AWS)

The AWS target infrastructure for the sample application has been provisioned and validated:

- **ECR repository** (`sample-api-ecr`, `us-east-1`): stores container images with scan-on-push enabled and a lifecycle policy retaining the last five images
- **VPC** (`sample-api-vpc`, `10.0.0.0/16`): dual-AZ topology with public subnets for the Application Load Balancer and private subnets for EKS Fargate pods; single NAT Gateway for outbound pod connectivity
- **EKS cluster** (`sample-api-cluster`, Kubernetes 1.30): Fargate-only compute (no EC2 node groups), with Fargate profiles for `kube-system`, `argocd`, `staging`, and `prod` namespaces
- **AWS Load Balancer Controller** (`v2.11.0`): runs in `kube-system` and provisions ALBs in response to `Ingress` resources; uses IRSA (IAM Roles for Service Accounts) with an OIDC provider for credential-free AWS API access
- **IAM role chain**: a minimally privileged CLI user (`sample-api-cli-user`) may assume only the `sample-api-terraform-executor-role`, which itself holds only the permissions required to provision the project's specific infrastructure components

The FastAPI sample application (`sample-backend-api`) has been deployed to the `staging` namespace and is reachable via an internet-facing ALB. Image tag `v2` is the current working deployment.

### 7.4 Security Model Documentation and Implementation

The six security requirements (R1–R6) have been fully specified, with implementation approaches, enforcement hardness classifications, and trade-off analyses documented. The decision framework for GitHub Apps versus fine-grained PATs, and for Repository Rulesets versus branch protection rules, has been produced and justified. Phase 1 uses fine-grained PATs; the migration path to GitHub Apps is defined for Phase 2 when the agentic layer is introduced.

The secret scanning control (R5) is fully operational: gitleaks runs on every push to every Gitea repository, enforced by the platform-workflows CronJob without per-repository configuration.

### 7.5 System Design Documentation

Comprehensive design documentation has been produced covering:

- The two-layer infrastructure architecture and the GitOps bridge
- The agentic system architecture (deferred to Phase 2): MCP server design, LangGraph workflow model, CAIPE reference implementation analysis
- The operational knowledge graph: schema design, extraction pipeline architecture, agent query interface, and two-phase storage approach
- The CD workflow design for the sample application (local → AWS migration path)

---

## 8. Remaining Work

The following components are planned for the second half of the dissertation:

### 8.1 Terraform for AWS Infrastructure

The current AWS infrastructure was provisioned manually for validation purposes. The remaining task is to express the entire AWS layer (EKS, ECR, VPC, IAM roles, Fargate profiles, ALB Controller) as Terraform modules. This is required to satisfy the project's GitOps invariant — infrastructure provisioned outside of code is not auditable or reproducible.

### 8.2 Kyverno Policy Enforcement

Kyverno will be deployed to the EKS cluster as the policy-as-code layer. Policies will enforce cluster security standards (no privileged containers, image registry restrictions, resource quota requirements) independently of the application manifests themselves. Kyverno also serves as the second enforcement layer for the sandbox environment: network policies will restrict egress from `sandbox-*` namespaces, and resource quotas will cap per-sandbox resource consumption.

### 8.3 Sample Application and GitOps Pipeline

The `sample-backend-api-app` (FastAPI) and `sample-backend-gitops` (Kubernetes manifests) repositories need to be fully configured in Gitea with the complete CI workflow. The CI workflow builds and pushes the container image to ECR on each push to main, updates the image tag in the gitops repository, and triggers ArgoCD reconciliation. This provides the concrete test case against which agentic workflows will operate.

### 8.4 Agentic Layer (Phase 2)

The agentic layer is the primary research contribution. It comprises:

- **MCP servers** — one per operational concern (infrastructure state reader, ArgoCD operator, Gitea code agent), each scoped to the minimum permissions required for its function
- **LangGraph workflows** — code-first Python implementations of agentic workflows (issue triage, deployment promotion, incident investigation), with HITL interruption points at defined state transitions
- **Knowledge graph extraction pipeline** — Gitea Actions workflow that runs on relevant push events, invokes the Claude API with a structured JSON output schema, and commits the updated graph to the repository

### 8.5 Evaluation

The agentic system will be evaluated against a manual operations baseline and a generalised AI assistant (unrestricted Claude API) using three metrics:

- **Task Success Rate (TSR):** the percentage of defined operational tasks completed correctly end-to-end by the constrained agent versus the baseline
- **Mean Time to Resolution (MTTR):** elapsed time from task initiation to confirmed resolution
- **System Efficiency & Cost:** token consumption, tool call count, and estimated API cost per task

---

## 9. Project Timeline

| Phase | Period | Status |
|---|---|---|
| Literature Review + System Design | Jan 31 – Feb 14, 2026 | Completed |
| Control Plane Implementation | Feb 14 – Mar 1, 2026 | Completed |
| AWS Infrastructure + Security Model | Mar 1 – Mar 21, 2026 | Completed |
| Terraform IaC + Kyverno | Mar 21 – Apr 7, 2026 | In progress |
| Sample App GitOps Pipeline | Apr 7 – Apr 14, 2026 | Planned |
| Agentic Layer Implementation | Apr 7 – Apr 28, 2026 | Planned |
| Evaluation and Metric Collection | Apr 21 – May 5, 2026 | Planned |
| Final Report and Submission | May 5 – May 12, 2026 | Planned |

---

## 10. References

1. Weaveworks. (2017). *GitOps: Operations by Pull Request*. Weaveworks Blog. https://www.weave.works/blog/gitops-operations-by-pull-request

2. CNCF GitOps Working Group. (2021). *OpenGitOps Principles*. https://opengitops.dev

3. Weill, T., & Krebs, T. (2023). *Argo CD: Declarative GitOps Continuous Delivery for Kubernetes*. CNCF Project Documentation. https://argo-cd.readthedocs.io

4. HashiCorp. (2014–2024). *Terraform: Infrastructure as Code*. https://developer.hashicorp.com/terraform

5. Anthropic. (2024). *Model Context Protocol Specification*. https://modelcontextprotocol.io

6. CNOE (Cloud Native Operational Excellence). (2024). *idpbuilder: Internal Developer Platform Bootstrapper*. https://cnoe.io/docs/reference-implementation/installations/idpbuilder

7. CNOE. (2025). *CAIPE: Community AI Platform Engineering*. https://github.com/cnoe-io/ai-platform-engineering

8. LangChain. (2024). *LangGraph: Building Stateful, Multi-Actor Applications with LLMs*. https://langchain-ai.github.io/langgraph

9. Nakagawa, Y. (2025). *Replit Agent Incident Report: Agentic AI Deletes Production Database*. Replit Community Discussion, July 2025.

10. Garg, S., et al. (2023). *Prompt Injection Attacks and Defences in LLM-Integrated Applications*. arXiv:2310.12815.

11. AWS. (2024). *Amazon EKS Fargate Documentation*. https://docs.aws.amazon.com/eks/latest/userguide/fargate.html

12. AWS. (2024). *IAM Roles for Service Accounts (IRSA)*. https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html

13. Kyverno Project. (2024). *Kyverno: Kubernetes Native Policy Management*. https://kyverno.io/docs

14. gitleaks. (2024). *gitleaks: Detect Secrets in Git Repositories*. https://github.com/gitleaks/gitleaks

15. Russell, S., & Norvig, P. (2020). *Artificial Intelligence: A Modern Approach* (4th ed.). Pearson. [Principal-agent framework, Chapter 37]

---

*This report covers work completed through March 2026. The control system infrastructure, security model, and AWS production environment are fully implemented. The agentic layer and evaluation phase constitute the primary remaining work.*
