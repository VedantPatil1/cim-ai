# Abstract

Modern cloud-native platforms use IaC and GitOps to automate deployments reliably — but they cannot semantically reason about why a system is failing or whether a configuration aligns with business objectives. This leaves complex auditing and troubleshooting as manual, high-latency tasks.
LLM-based Multi-Agentic Systems are increasingly used to bridge this gap — but they introduce a new risk. As demonstrated by the July 2025 Replit incident, where an agentic assistant bypassed explicit "no-change" directives and deleted a production database, fully autonomous AI lacks the deterministic reliability required for infrastructure management. Without rigorous guardrails, LLM reasoning becomes a liability rather than an asset.

A controlled, auditable, and secure tooling-based agentic workflow system for standardised Control Plane Infrastructure — sitting between risky fully autonomous AI and tedious manual operations.

- Identify operational challenges in modern cloud-native platform engineering
- Implement reliable guardrails using security-by-design: A2A authentication, tool-based actions, human-in-the-loop authorisation, and Principle of Least Privilege
- Design agentic workflows operating as part of a standardised platform control plane
- Leverage LLM reasoning across infrastructure state, GitOps repos, IaC definitions, CI/CD pipelines, and operational documentation
- Implement controlled automation that prioritises stability, reliability, and traceability over full autonomy
- Compare proposed agentic workflows against generalised systems using metrics: Task Success Rate (TSR), Mean Time to Resolution (MTTR), and System Efficiency & Cost

Design and develop secure, constrained, and specialised agentic workflows for Standardised Platform Control Planes. Implement a set of standards, rules, and practices for safe workflow execution. Evaluate against generalised Agentic AI using industry-standard metrics. Refine for context awareness and token efficiency aligned with real-world use cases.

The infrastructure being built in this project — EKS, ArgoCD, GitOps pipelines, OIDC-based access, Terraform IaC — is not just a deployment platform. It is the experimental environment in which constrained agentic workflows operate. Every design decision — PoLP IAM, scoped tokens, auditable git commits, human promotion gates — directly maps to a security principle being researched and validated.


## Section 4 — Design Considerations

### 4.1 Security as an Architectural Constraint, Not an Afterthought

The central design philosophy of this project is that security for agentic systems cannot
be bolted on after the fact. Every infrastructure decision — from IAM role naming
conventions to network topology to CI/CD authentication mechanisms — was made with
the eventual agentic access layer as an explicit requirement. This approach differs
fundamentally from conventional platform engineering, where security hardening typically
follows initial deployment. In this system, the security model is the deployment model.

A concrete example is the IAM identity structure. Rather than using a single
administrative identity for all operations, the system implements a role-chaining model
in which a minimally privileged CLI user (`sample-api-cli-user`) is permitted only to
assume a single role (`sample-api-terraform-executor-role`), which itself holds only the
permissions required to provision the specific infrastructure components of this project.
This structure was designed not merely for the human operator but as a reference pattern
for the agent identity model that will be built on top of it. If the human operator operates
under least privilege, the agent identities will be scoped even more tightly.

### 4.2 The Two-Boundary Trust Model

A key architectural decision is the introduction of two explicit trust boundaries rather
than a single perimeter. This choice was motivated by the observation that a single
boundary model provides inadequate defence in depth for agentic systems. If a tool is
compromised, a single boundary gives an attacker direct access to all infrastructure. Two
boundaries mean that both the LLM frontend and the tooling layer must be simultaneously
compromised for a serious breach to occur.

Boundary 1 sits between the LLM layer and the tooling layer. It enforces user
authentication, determines the scope of the incoming request based on the authenticated
user's role, generates a time-limited scoped token specific to that request, and applies
rate limiting to prevent runaway agent behaviour. Critically, all responses from the
tooling layer pass back through this boundary before being returned to the LLM, where a
response filter strips any content that should not be visible to the requesting user —
including credentials, internal IP addresses, raw log output, and stack traces.

Boundary 2 sits between the tooling layer and the control system infrastructure. It
enforces Principle of Least Privilege at the credential level, restricts tool invocations to
a pre-approved whitelist of actions, validates every action against policy before execution,
and logs all operations to AWS CloudTrail. No tool in the tooling layer is permitted to
call infrastructure APIs with credentials broader than those required for that specific
operation.

This two-boundary model maps cleanly onto the existing GitOps architecture. The deploy
repository functions as the natural enforcement point for Boundary 2 — an agent that
wishes to deploy to production must commit a change to the deploy repository, which is
then reviewed and merged by a human before ArgoCD applies it to the cluster. The agent
never calls the Kubernetes API directly. This architectural constraint eliminates an entire
class of direct-access attacks without requiring any additional enforcement mechanism.

### 4.3 GitOps as an Immutable Audit Trail

A significant insight emerging from this work is that a properly implemented GitOps
architecture provides a natural, tamper-resistant audit trail for agentic operations at no
additional implementation cost. Every change an agent makes to the infrastructure state
must be expressed as a git commit in the deploy repository. That commit carries the
agent's identity, the timestamp, the specific change made, and the request identifier that
triggered it. This record cannot be silently modified without leaving evidence in the git
history.

This is qualitatively different from a conventional audit log, which is a separate system
that can fail, be misconfigured, or be deliberately disabled. The GitOps audit trail is the
deployment mechanism itself — if the commit does not exist, the deployment does not
happen. Auditability is therefore not a feature that can be bypassed; it is a prerequisite
for operation.

This property is particularly relevant for agentic systems because it provides a complete
causal chain from user request to infrastructure change. A security investigator can
reconstruct exactly what a user asked, what the agent decided to do, what commit it
generated, when ArgoCD applied it, and what the resulting cluster state was — all from
standard tooling without any specialised forensic capability.

### 4.4 Tooling Layer as Active Security Enforcement

The tooling layer in this architecture is not a passive API proxy. It is an active security
enforcement component that performs several distinct functions before any infrastructure
call is made.

The first function is blast radius assessment. Before executing any write operation, the
tooling layer evaluates the potential impact of the action — how many services are
affected, which environments are in scope, whether the action is reversible, and what the
rollback path is. If the assessed blast radius exceeds a configured threshold, the action
is escalated to a human operator rather than executed autonomously. This prevents a
class of failures where an agent takes a technically valid action that has consequences
disproportionate to the original intent.

The second function is prompt injection detection. Because the agent reads
infrastructure state — log files, configuration manifests, git commit messages — any of
this content could contain adversarial instructions designed to manipulate the agent's
behaviour. The tooling layer treats all infrastructure content as untrusted data, applying
structural parsing and content sanitisation before passing it to the LLM context. Raw
log output is never passed directly to the model.

The third function is idempotency enforcement. Agentic systems are susceptible to
repeated execution of the same action, particularly in error recovery scenarios. The
tooling layer assigns a unique identifier to each request and checks this identifier before
executing any write operation, ensuring that retried requests do not produce duplicate
infrastructure changes.

### 4.5 Principle of Least Privilege Applied to Agent Identities

The agent identity model follows the same least-privilege principles established for the
human operator identity model, but applied at finer granularity. Rather than a single
agent identity with broad infrastructure access, the system defines distinct identities for
distinct operation types.

A state reader identity is permitted only to call read operations — listing pods, querying
ArgoCD sync status, describing recent pipeline runs. It holds no write permissions
whatsoever. A staging promoter identity is permitted only to update the image tag in the
staging overlay of the deploy repository. It cannot touch the production overlay, cannot
modify IAM policies, and cannot call AWS APIs directly. An incident responder identity
is permitted to read logs and events but cannot modify any resource. These identities are
enforced at the Kubernetes RBAC level and at the IAM policy level simultaneously,
providing two independent enforcement points for the same constraint.

This approach also simplifies the audit trail. Because each operation type uses a distinct
identity, a CloudTrail log entry immediately indicates not just what action was taken but
what class of agent took it, without requiring additional correlation.

### 4.6 Human-in-the-Loop as an Architectural Primitive

The system treats human oversight not as an optional safety net but as an architectural
primitive — a first-class component of the deployment workflow with its own defined
triggers and escalation paths. Certain operations are categorised as requiring human
approval regardless of the agent's confidence in the action. These include any
deployment to the production environment, any modification to IAM policies or security
group rules, any operation that cannot be reversed within a defined time window, and any
action where the assessed blast radius exceeds the configured threshold.

The mechanism for human-in-the-loop in this architecture is the pull request. When an
agent determines that an action requires human approval, it raises a pull request in the
deploy repository with a structured description of the proposed change, the request that
triggered it, the assessed blast radius, and the recommended action. A human reviewer
approves or rejects the pull request, and ArgoCD applies the change only after merge.
This mechanism requires no specialised approval workflow tooling — it uses the same git
review process that the engineering team uses for all other infrastructure changes, making
human oversight a natural part of the operational workflow rather than an exceptional
intervention.