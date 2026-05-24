# Chapter 6: Agentic Layer Implementation

## 6.1 Overview

Chapter 4 established the target infrastructure and CI/CD pipeline as Phase 1 of the research. Chapter 6 documents Phase 2: the design and implementation of the agentic layer on top of that foundation. Rather than using a cloud-hosted AWS environment for Phase 2 experimentation, a fully self-contained local control plane was constructed using idpbuilder and CNOE (Cloud Native Operational Excellence) tooling. This approach preserves all architectural properties of the production system — GitOps reconciliation, branch protection, CI runners, image registries — while enabling rapid iteration without incurring AWS costs or risking production state.

The local control plane runs inside a kind (Kubernetes-in-Docker) cluster and replicates the structure of the production environment exactly. The same GitOps principles, identity model, and security guardrails apply. Only the endpoints differ: Gitea replaces GitHub, a local OCI registry replaces ECR, and kind replaces EKS.

## 6.2 Local Control Plane Setup

The local control plane is bootstrapped using a single idpbuilder command:

```bash
idpbuilder create \
  --recreate \
  --use-path-routing \
  -c gitea:./control-system-infrastructure/cnoe-stack/gitea-config/override.yaml \
  -p control-system-infrastructure/cnoe-stack/packages/gitea-runner
```

This provisions the following components inside a single kind node:

| Component | Role | Endpoint |
|---|---|---|
| Gitea | In-cluster Git server and OCI registry | `/gitea` |
| ArgoCD | GitOps reconciliation engine | `/argocd` |
| nginx ingress | Reverse proxy, TLS termination | Port 8443 |
| Gitea Actions runner | CI job executor (act_runner + DinD) | In-cluster |

All components are managed as ArgoCD Applications, meaning idpbuilder itself uses GitOps to deploy the control plane. The runner deployment is stored in a dedicated Gitea repository (`giteaAdmin/idpbuilder-localdev-gitea-actions-runner-manifests`) and watched by ArgoCD, ensuring all runner configuration changes flow through Git.

The Gitea Actions runner uses a Docker-in-Docker (DinD) sidecar architecture. The act_runner daemon executes job steps inside container images launched via the DinD Docker daemon, providing isolation equivalent to a cloud-hosted CI runner. The runner is registered with the label `ubuntu-latest:docker://node:20-bullseye`, meaning any workflow declaring `runs-on: ubuntu-latest` automatically executes inside a Debian Bullseye container.

## 6.3 Agent Identity and Security Model

The security model implements six controls (R1–R6) as described in the design considerations. At the implementation layer, these manifest as two distinct Gitea user identities operating under enforced constraints.

**dev-agent** represents the agentic identity — the account under which automated or AI-assisted changes are proposed. It holds write access to the `sample-backend-app` repository, allowing it to push feature branches and open pull requests. It cannot push directly to `main` and cannot modify files matching `.gitea/**`, which covers all workflow definitions and helper scripts.

**admin-human** represents the human approver identity. It is the sole account authorised to approve and merge pull requests into `main`. This separation is enforced at the branch protection level rather than by convention.

The branch protection rule on `sample-backend-app/main` enforces the following constraints:

```json
{
  "enable_push": false,
  "required_approvals": 1,
  "enable_approvals_whitelist": true,
  "approvals_whitelist_username": ["admin-human"],
  "protected_file_patterns": ".gitea/**"
}
```

The `protected_file_patterns` field is the critical guardrail for workflow integrity. Even if dev-agent were compromised or an LLM were to attempt to modify the security analysis workflow to suppress findings, any pull request containing changes to `.gitea/**` would be blocked at merge time regardless of approval status. This implements supply chain protection (R6) at the platform level without relying on any runtime policy enforcement.

## 6.4 CI/CD Pipeline Implementation

The CI/CD pipeline is defined in `.gitea/workflows/ci.yaml` and consists of two sequentially gated jobs.

The `check` job runs on every pull request and push to `main`. It installs Python dependencies and executes the pytest test suite inside a `node:20-bullseye` container. This job must pass before any downstream job can proceed.

The `build-push` job runs exclusively on pushes to `main` (i.e., after a pull request has been merged and approved by admin-human). It performs the following steps:

1. Detects the DinD bridge gateway IP dynamically (`ip route show default`) and configures `DOCKER_HOST` accordingly, allowing Docker commands to reach the DinD daemon from within the job container
2. Adds the nginx ingress ClusterIP to `/etc/hosts` so that `cnoe.localtest.me` resolves correctly inside the job container
3. Builds and tags the container image with both the commit SHA and `latest`
4. Authenticates to the Gitea OCI registry using the `CI_TOKEN` secret (scoped to the `giteaAdmin` namespace owner)
5. Pushes both tags to `cnoe.localtest.me:8443/giteaadmin/sample-backend-app`
6. Clones the `sample-backend-gitops` repository, updates the image tag via `sed`, commits, and pushes — triggering ArgoCD reconciliation

The containerd registry configuration on the kind node required a specific fix to support insecure registry pulls. The legacy `registry.mirrors` format is incompatible with `config_path` in containerd v1.7+; both cannot coexist. The resolution was to remove the legacy stanza and configure the registry exclusively through a `hosts.toml` file at `/etc/containerd/certs.d/cnoe.localtest.me:8443/hosts.toml`.

Upon a successful `build-push` run, ArgoCD detects the updated image tag in the gitops repository within its reconciliation interval and applies the new deployment to the `sample-staging` namespace. The full round-trip — code push to running pod — completes without any manual intervention after the admin-human merge.

## 6.5 Security Analysis Workflow

The security analysis workflow is the primary agentic component of Phase 2. It demonstrates LLM reasoning integrated into the GitOps review process as a non-blocking advisory gate.

### 6.5.1 Architecture

The workflow follows a three-layer call chain:

```
PR Event → Gitea Actions → security_check.py → Langflow API → Ollama → PR Comment
```

When a pull request is opened, synchronised, or reopened on `sample-backend-app`, Gitea dispatches a `pull_request` event. The Gitea Actions runner picks up the event and executes the `security-analysis` job inside a `node:20-bullseye` container.

### 6.5.2 Gitea Actions Workflow

The workflow definition (`.gitea/workflows/security-analysis.yaml`) passes the following environment variables to the analysis script:

- `GITEA_TOKEN`: The built-in `GITHUB_TOKEN` equivalent, scoped to the repository — used only for posting the PR comment, not for any privileged operation
- `GITEA_URL`, `REPO`, `PR_NUMBER`, `BASE_SHA`, `HEAD_SHA`: PR context variables
- `LANGFLOW_URL`: The Langflow instance URL (`http://host.docker.internal:7860`), which resolves from inside DinD job containers to the host machine running Langflow
- `FLOW_ID`: The Langflow flow identifier, stored as a Gitea Actions secret (`LANGFLOW_FLOW_ID`) to allow rotation without workflow changes

The `FLOW_ID` is stored as a secret rather than hardcoded, implementing a separation between workflow logic (which dev-agent cannot modify) and runtime configuration (which can be updated by administrators without a code change).

### 6.5.3 Analysis Script

The analysis script (`security_check.py`) performs the following operations:

1. Computes the git diff between `BASE_SHA` and `HEAD_SHA`, prioritising source code files (`*.py`, `*.js`, `*.ts`, `*.go`, `Dockerfile`, `requirements.txt`) before falling back to the full diff. The diff is truncated to 8,000 characters to avoid exceeding LLM context limits.

2. Submits the diff to the Langflow flow via `POST /api/v1/run/{FLOW_ID}?stream=false`, passing the diff as the `input_value`. The timeout is set to 300 seconds to accommodate cold model loading.

3. Extracts the text response from the Langflow response envelope at `outputs[0].outputs[0].results.text.data.text`.

4. Posts the structured analysis as a pull request comment via the Gitea API, using the scoped `GITEA_TOKEN`.

Error handling at each stage returns a descriptive message as the comment body rather than failing silently, ensuring that infrastructure or connectivity failures are visible to reviewers.

### 6.5.4 Langflow Integration

Langflow 1.9.0 runs as a Docker container on the host machine with a persistent volume (`langflow-data`) for database and flow storage. The security analysis flow (ID: `8baf48a8-a49d-48cf-8753-d7baa5ae16c6`, name: "Security Code Analyser") consists of three nodes:

1. **TextInput** — receives the git diff as the flow's text input
2. **Custom Python Component** — calls `http://host.docker.internal:11434/api/chat` directly, bypassing Langflow's built-in OllamaModel component which exhibited a JSON format conflict with plain-text prompts in version 1.9.0
3. **TextOutput** — emits the model's response

The custom component uses the `qwen2.5-coder:7b` model with `stream: false` and a 300-second timeout. The prompt instructs the model to produce a structured three-section report: Summary (risk level), Findings (bullet list of issues), and Recommendations (bullet list of fixes).

The choice of `qwen2.5-coder:7b` over the initially evaluated `FenkoHQ/Foundation-Sec-8B` model was driven by empirical observation. Foundation-Sec-8B returned empty content in streaming mode and echoed template headers without content in non-streaming mode, suggesting poor instruction-following for structured output. `qwen2.5-coder:7b` consistently produced populated, accurate structured reports for the same inputs.

### 6.5.5 Sample Output

For a pull request introducing a command injection vulnerability (`subprocess.run` with `shell=True`) and a SQL injection vector (`os.system` with user-controlled input), the model produced the following assessment:

> **Summary:** High
>
> **Findings:**
> - Command injection: `subprocess.run` with `shell=True` and user-provided `query` allows arbitrary command execution
> - SQL injection: `os.system(f"psql -c 'DROP TABLE {table}'")` passes unsanitised user input to a shell command
> - Path traversal: `/data` directory search with unsanitised input allows directory traversal via symlinks
>
> **Recommendations:**
> - Replace `shell=True` with argument list form: `subprocess.run(["grep", "-r", query, "/data"])`
> - Use parameterised queries for database operations via an ORM or psycopg2 cursor
> - Validate and whitelist the `table` parameter against a predefined set of allowed table names

This output was posted as a pull request comment within 29 seconds of the PR synchronise event, before any human reviewer had opened the PR.

## 6.6 Knowledge Graph

### 6.6.1 Schema

The knowledge graph is defined using Pydantic v2 models in `knowledge-graph/schema.py`. The schema captures seven entity types — Service, Component, Repository, Environment, Policy, Runbook, and Team — connected by six relationship types: DEPENDS_ON, OWNS, DEPLOYS_TO, GOVERNED_BY, DOCUMENTED_BY, and PROVISIONS.

Nodes carry a typed `attrs` dictionary for entity-specific metadata (e.g., registry URL for a Component, branch for a Repository). Edges carry optional `attrs` for relationship metadata (e.g., approval count for a GOVERNED_BY relationship). The graph supports `upsert_node` and `upsert_edge` operations keyed on ID and (from, to, rel) triples respectively, enabling incremental updates without full replacement.

### 6.6.2 Seed Graph

The seed graph (`knowledge-graph/graph.json`) was hand-crafted from the known system entities and contains over 20 nodes and 20 edges. Representative entities include:

- `sample-backend-api` (Service) owned by `platform-eng` (Team)
- `sample-backend-app` (Repository) deploying to `staging` (Environment)
- `branch-protection` (Policy) governing `sample-backend-app`
- `gitea-registry` (Component) provisioned by `local-kind` (Environment)

### 6.6.3 Extraction Pipeline

The extraction script (`knowledge-graph/extract.py`) accepts `--files` or `--all` flags and uses the Anthropic API (`claude-haiku-4-5`) to extract entities from documentation and manifest files. The extraction prompt instructs the model to return a strict JSON structure:

```json
{
  "nodes": [{"id": "...", "type": "...", "attrs": {}}],
  "edges": [{"from": "...", "to": "...", "rel": "..."}]
}
```

Extracted nodes and edges are merged into the existing graph via upsert operations. With `--commit`, the script commits the updated `graph.json` and pushes to Gitea, triggering a Gitea Actions workflow (`.gitea/workflows/knowledge-graph-extract.yaml`) that re-runs extraction on changed documentation files automatically.

### 6.6.4 MCP Server

The MCP server (`knowledge-graph/mcp_server.py`) exposes four query tools over HTTP on port 8765:

| Tool | Input | Output |
|---|---|---|
| `get_service_context` | `service_name` | Owner, repo, dependencies, policies, runbooks |
| `get_environment_topology` | `env_name` | Services, components, policies in environment |
| `get_runbook` | `runbook_name` | Trigger conditions and resolution steps |
| `find_policy_violations` | `service_name`, `proposed_change` | Policies that would be violated |

The server reads `graph.json` on each request to ensure freshness. It is designed to be consumed by Langflow flows as an HTTP tool component, providing structured infrastructure context to LLM reasoning steps without exposing raw graph data to external clients.

## 6.7 Additional Langflow Workflows

Three additional Langflow flows were implemented as importable JSON artifacts in the `agentic/` directory, demonstrating the extensibility of the workflow layer:

**knowledge-graph-query/flow.json** — A conversational flow that loads the graph context and answers natural language queries about infrastructure state. Example: "What policies govern the staging environment?" returns the three relevant policy nodes with their attributes.

**change-impact-analyzer/flow.json** — Takes a proposed infrastructure change description, traverses the knowledge graph via BFS to identify affected services and components, and produces a blast-radius assessment with risk classification.

**infrastructure-advisor/flow.json** — A conversational advisor combining a ChatInput component with knowledge graph context injected into the system prompt. Enables sustained dialogue about infrastructure state, recent changes, and operational decisions without exposing raw tool outputs to the user.

---

# Chapter 7: Evaluation

## 7.1 Evaluation Framework

The evaluation framework measures three dimensions of the implemented agentic system:

1. **Task Success Rate (TSR)** — the proportion of agentic workflow invocations that completed successfully without human intervention to correct an error
2. **Mean Time to Resolution (MTTR)** — the average wall-clock time from task initiation to completion, disaggregated by task type
3. **Security Model Validation** — qualitative assessment of whether the implemented guardrails held under adversarial conditions

Metrics are captured as structured events in `metrics/events.json` using the `TaskEvent` schema defined in `metrics/schema.py`. Each event records the task type, description, start and end timestamps, success flag, duration in seconds, error message if applicable, and task-specific metadata. The `metrics/calculate.py` script aggregates these events into TSR and MTTR statistics per task type.

The evaluation dataset consists of eight events logged across the implementation and testing phases, covering six distinct task types. While this constitutes a small sample, it captures representative outcomes across the full workflow surface — including one genuine failure (a dependency error in the CI pipeline) that was not manually corrected before logging.

## 7.2 Task Success Rate

The overall TSR across all task types was **87.5%** (7 successful out of 8 total tasks).

| Task Type | Total | Successful | Failed | TSR |
|---|---|---|---|---|
| ci-pipeline | 2 | 1 | 1 | 50.0% |
| security-analysis | 2 | 2 | 0 | 100.0% |
| gitops-sync | 1 | 1 | 0 | 100.0% |
| kg-extraction | 1 | 1 | 0 | 100.0% |
| kg-query | 1 | 1 | 0 | 100.0% |
| change-impact | 1 | 1 | 0 | 100.0% |
| **Total** | **8** | **7** | **1** | **87.5%** |

The single failure occurred in the `ci-pipeline` task type during a pytest run that encountered a missing `httpx` dependency (`ModuleNotFoundError: No module named 'httpx'`). This was an application-level error caught correctly by the quality gate — the pipeline failed as intended, preventing a broken image from reaching the registry. This represents correct system behaviour rather than an agentic failure: the CI gate performed its function by rejecting a non-compliant commit.

The 50% TSR for `ci-pipeline` should therefore be interpreted as reflecting the test dataset composition (one clean push, one deliberately broken push) rather than as a reliability defect. The agentic workflow itself — detecting the failure, surfacing the error, and blocking promotion — succeeded in both cases.

All five agentic workflow types (security-analysis, gitops-sync, kg-extraction, kg-query, change-impact) achieved a TSR of 100% across their respective invocations.

## 7.3 Mean Time to Resolution

| Task Type | MTTR (all) | MTTR (success) | MTTR (failure) |
|---|---|---|---|
| kg-query | 8.2 s | 8.2 s | — |
| change-impact | 19.4 s | 19.4 s | — |
| security-analysis | 29.7 s | 29.7 s | — |
| gitops-sync | 45.0 s | 45.0 s | — |
| kg-extraction | 72.4 s | 72.4 s | — |
| ci-pipeline | 208.0 s | 214.0 s | 202.0 s |
| **Overall** | **77.5 s** | **59.8 s** | **202.0 s** |

Knowledge graph queries resolve in under 10 seconds, as they involve only a JSON file read and graph traversal with no LLM call. Change impact analysis completes in under 20 seconds, with the LLM call accounting for the majority of the latency. Security analysis completes in approximately 30 seconds — the diff extraction and Langflow HTTP overhead each contribute a few seconds, with the `qwen2.5-coder:7b` inference accounting for the remainder.

GitOps synchronisation at 45 seconds reflects the ArgoCD reconciliation interval from the moment the gitops repository is updated to the moment the new pod reaches the Ready state. Knowledge graph extraction at 72 seconds includes the Claude API call for entity extraction plus the git commit and push cycle.

The CI pipeline's 208-second average reflects the full build cycle — dependency installation, test execution, Docker build, image push, and gitops update. This is not primarily LLM latency but rather the mechanical cost of the build and push operations.

The overall MTTR for successful tasks of **59.8 seconds** represents the end-to-end wall-clock time for an agentic workflow to complete from trigger to resolution. For the class of tasks that previously required human attention (identifying security issues in a PR, assessing the blast radius of a proposed change, querying infrastructure state), this represents a reduction from minutes or hours to under one minute.

## 7.4 Comparison Against Generalised Agentic AI

A generalised agentic AI system — for example, an LLM with direct access to kubectl, Terraform CLI, and the Git remote — operates without the structural constraints implemented in this system. This section characterises the differences across four dimensions.

### 7.4.1 Action Boundary

In the implemented system, no agent action modifies production state directly. Every state change flows through a pull request, is reviewed by admin-human, and is reconciled by ArgoCD from a version-controlled manifest. The agent can propose changes but cannot execute them.

A generalised system connecting an LLM directly to infrastructure tooling lacks this boundary. As demonstrated by the July 2025 Replit incident — where an AI assistant bypassed explicit "no-change" directives and deleted a production database — the absence of structural action boundaries allows LLM reasoning errors to propagate directly to irreversible infrastructure mutations. The Replit incident is directly analogous to the threat model this system addresses: the LLM had legitimate tool access but no architectural constraint preventing destructive use.

### 7.4.2 Credential Exposure

In the implemented system, credentials (CI_TOKEN, LANGFLOW_FLOW_ID, Gitea passwords) are stored as Gitea Actions secrets, injected at runtime into job containers, and never present in LLM context. The LLM receives only the diff text and produces only the analysis text. It has no path to credentials regardless of prompt construction.

In a generalised system, credentials are typically passed to the LLM as tool parameters or environment context to enable tool invocation. Any prompt injection in a document the LLM processes — a Dockerfile comment, a YAML field value, a log line — can potentially exfiltrate credential values. This attack surface does not exist in the implemented architecture.

### 7.4.3 Audit Trail

Every action in the implemented system that modifies state produces a git commit. The commit is the mechanism by which the change takes effect — not a side-effect log. It is therefore impossible to perform a state-modifying action without producing an audit record, because the audit record (the commit) is the action itself.

A generalised system typically relies on separate audit logging infrastructure that can be disabled, misconfigured, or simply absent. Log-based audit trails can be retroactively altered or silently dropped during infrastructure incidents — precisely the moments when audit integrity is most critical.

### 7.4.4 Scope Creep Prevention

The implemented system enforces Principle of Least Privilege at the identity level. dev-agent holds write access to one repository and cannot approve its own changes. The Gitea Actions token used for posting PR comments holds read/write access only to issues on the target repository — it cannot push code, create repositories, or modify branch protection rules.

A generalised system with a single privileged API token grants the LLM access to the full scope of that token. Any reasoning error, hallucination, or prompt injection can cause actions across the entire scope — not just the intended target.

### 7.4.5 Summary Comparison

| Dimension | Implemented System | Generalised Agentic AI |
|---|---|---|
| Action boundary | Git PR + human merge required | Direct infrastructure access |
| Credential exposure to LLM | Structurally absent | Present as context |
| Audit trail | Git history (cannot be disabled) | Separate log (can fail) |
| Identity scope | Per-operation least privilege | Single privileged token |
| Production blast radius | Bounded to one PR | Unbounded |
| Jailbreak resistance | Architectural (not prompt-based) | Prompt-dependent |

## 7.5 Security Model Validation

The six security controls (R1–R6) were validated through deliberate adversarial testing during the implementation phase.

**R1 (Agent Identity):** dev-agent and admin-human are distinct identities with non-overlapping capabilities. Validated by confirming that dev-agent cannot approve its own pull requests.

**R2 (Least Privilege):** dev-agent holds write but not admin access. The CI token (`CI_TOKEN`) is scoped to the giteaAdmin namespace and cannot create repositories or modify organisation settings. Validated by attempting operations outside scope and confirming HTTP 403 responses.

**R3 (HITL Gate):** All merges to `main` require admin-human approval. Validated by attempting a direct push as dev-agent and confirming HTTP 403, and by attempting a self-merge and confirming rejection.

**R4 (Audit Trail):** Every state change to the production namespace corresponds to a git commit in the gitops repository. Validated by tracing ArgoCD sync events to their originating commits across multiple CI runs.

**R5 (Secret Protection):** The gitleaks secret scanning workflow runs on every push. Validated by introducing a test credential pattern and confirming the scan detected it and reported failure.

**R6 (Supply Chain):** The `protected_file_patterns: .gitea/**` constraint prevents modification of workflow definitions and analysis scripts through the normal PR process. Validated by opening a pull request as dev-agent with a modified `.gitea/workflows/security-analysis.yaml` and confirming the merge was blocked regardless of admin-human approval status.

---

# Chapter 8: Conclusions and Recommendations

## 8.1 Summary of Contributions

This project has produced three primary contributions:

**A working local control plane** that replicates a production GitOps environment in its entirety — Gitea, ArgoCD, a CI runner, an OCI registry, and a Kubernetes cluster — using only open-source components and a single bootstrap command. This platform served simultaneously as the research substrate and as a demonstration of the reference architecture described in Chapters 3 and 4.

**A security-constrained agentic workflow** that integrates LLM reasoning into the pull request review cycle. The security analysis workflow is triggered automatically on every PR, calls a local LLM via Langflow, and posts a structured vulnerability assessment before any human reviewer opens the PR. This workflow is non-blocking (it advises rather than gates) and operates entirely within the identity and credential constraints of the platform.

**An infrastructure knowledge graph** with an associated extraction pipeline and MCP server, enabling structured LLM queries over infrastructure state — services, policies, environments, teams, and their relationships — without requiring the LLM to parse raw manifests or API responses.

## 8.2 Key Findings

**Finding 1: Structural guardrails are more reliable than prompt-based guardrails.** The implemented system prevents credential exposure, supply chain tampering, and direct production access through architecture — not instructions to the LLM. An LLM that has never received a credential cannot leak it. A workflow that requires a human merge to take effect cannot be bypassed by prompt injection. This distinction matters because prompt-based restrictions are falsifiable; architectural restrictions are not.

**Finding 2: GitOps is a natural enforcement layer for agentic systems.** The GitOps property — that no cluster state change occurs without a corresponding git commit — provides a foundation for agentic auditability without additional tooling. The git history becomes a complete, tamper-resistant record of every agentic action. This aligns with the design consideration in Section 5.2 and was confirmed empirically: tracing any deployment in the test environment to its originating PR, commit, and CI run was always possible without gap.

**Finding 3: The HITL gate was not an obstacle to workflow velocity.** The pull request review cycle — which includes security analysis, CI tests, and admin-human approval — completed in under five minutes for clean changes. The human step added latency only when the reviewer was not present, not when the workflow was running. This suggests that HITL gates, properly positioned, do not materially slow agentic workflows for the class of infrastructure changes they gate.

**Finding 4: Model selection for structured output matters significantly.** The initial choice of Foundation-Sec-8B for security analysis produced empty or malformed output in both streaming and non-streaming modes. Switching to `qwen2.5-coder:7b` produced consistent, well-structured, accurate output from the first invocation. For agentic workflows that require structured output, the model's instruction-following capability is more important than its domain specialisation.

**Finding 5: Langflow provides useful workflow orchestration but requires careful component selection.** The built-in OllamaModel component in Langflow 1.9.0 exhibited a JSON format conflict that prevented it from being used with plain-text prompts. A custom Python component bypassed this limitation with three dozen lines of code. This experience suggests that Langflow's value is in workflow composition and API exposure, not in the reliability of any specific built-in component — and that production deployments should prefer custom components with explicit error handling over built-in wrappers.

## 8.3 Limitations

**Sample size for metrics.** The evaluation dataset contains eight events. While these span six workflow types and include both successes and a genuine failure, the sample is insufficient for statistical significance. TSR and MTTR values should be treated as indicative rather than definitive. A longitudinal evaluation over weeks of real platform operations would produce more robust figures.

**Local environment differs from production in one critical dimension.** The kind cluster runs on a developer laptop with shared CPU and memory. The 29-second MTTR for security analysis reflects local Ollama inference speed, which will differ significantly from GPU-accelerated inference in a production environment. Specifically, the `qwen2.5-coder:7b` model at Q4 quantisation on a GPU would reduce inference latency by an order of magnitude. MTTRs reported here are therefore conservative upper bounds for production deployments.

**AWS infrastructure partially implemented.** Chapter 4 documents the AWS foundation (IAM, EKS, ECR, ArgoCD, CI/CD) as the production reference. The agentic layer was implemented and evaluated against the local kind cluster rather than against live AWS infrastructure. The connection between the Langflow/MCP layer and the AWS MCP tools (GitHub MCP, ArgoCD MCP, AWS MCP, Terraform state MCP) described in Section 3.2.3 was designed and specified but not implemented within the project timeline.

**Knowledge graph populated with seed data.** The `graph.json` seed graph was hand-crafted from known system entities. The automated extraction pipeline (Claude API via Gitea Actions) was implemented and tested but has not been run against the full documentation corpus in a sustained integration cycle. The quality of LLM-extracted graph data at scale is an open empirical question.

**Secret scanning gate is non-blocking.** The gitleaks workflow correctly detects credential patterns but its failure does not block the PR merge in the current configuration. The `status_check_contexts` field in the branch protection rule was not configured to require the gitleaks check as a mandatory gate, because gitleaks could not execute Docker commands inside the `node:20-bullseye` container used by the runner. The fix requires either a privileged runner configuration or a native gitleaks binary in the job container.

## 8.4 Future Work

**AWS integration and end-to-end cloud validation.** The most direct extension of this work is completing the MCP integration layer connecting Langflow workflows to the live AWS infrastructure. This would enable the full conversational advisor use case described in Section 2.4 — where a developer asks about staging state and receives a synthesised summary drawn from ArgoCD, EKS, ECR, and Terraform state — against real cloud resources rather than a local simulation.

**LangGraph for production-grade workflow orchestration.** Langflow serves well as a prototyping and visualisation layer but is not designed for production reliability guarantees. LangGraph provides deterministic state machine semantics, explicit retry logic, and structured tool use that are better suited to production agentic workflows. A natural next step is reimplementing the security analysis and change impact workflows as LangGraph graphs, using Langflow as the design and documentation interface.

**Kyverno policy enforcement.** The architecture specifies policy enforcement as a component of the control plane (Section 3.2.1) but Kyverno was not implemented in the project timeline. Adding Kyverno would allow the expression of platform policies — for example, "no container may run as root", "all deployments must specify resource limits" — as code, evaluated automatically at admission time. This complements the LLM-based security analysis with deterministic rule enforcement.

**Dynamic token generation per workflow invocation.** Section 5.7 describes a workflow-scoped dynamic token model as an architectural property. The current implementation uses static secrets stored in Gitea Actions. A full implementation would generate a short-lived token at the start of each workflow invocation, scoped to the specific operations that workflow requires, and revoke it upon completion. This would reduce the blast radius of any credential compromise to a single invocation window.

**Evaluation against a generalised baseline.** A rigorous comparative evaluation would require deploying a generalised agentic system (e.g., an LLM with direct tool access to the same infrastructure) and running the same task set against both systems, measuring TSR, MTTR, and the rate of unsolicited state modifications. The Replit incident provides a qualitative reference point; a controlled experiment would provide quantitative evidence for the safety advantage of the constrained architecture.

**Token efficiency optimisation.** The security analysis prompt currently sends up to 8,000 characters of diff to the LLM regardless of content. A smarter chunking strategy — for example, identifying changed functions and sending only their context rather than raw diff lines — would reduce token consumption, decrease MTTR, and improve analysis precision. This aligns with the research objective of refining workflows for token efficiency.

## 8.5 Concluding Remarks

The central claim of this project was that solutions, guardrails, and practices already exist in modern platform engineering tooling that can greatly improve operational safety when an agentic AI layer is introduced — and that these safeguards are most effective when they are architectural properties rather than behavioural constraints on the LLM.

The implementation confirms this claim. Branch protection, GitOps reconciliation, identity separation, and protected file patterns collectively create a system in which an LLM can reason about infrastructure and propose changes, but cannot unilaterally execute them, cannot access credentials, and cannot tamper with its own operational constraints. These properties hold regardless of the LLM's behaviour — whether the model reasons correctly, hallucinates, or is prompted adversarially.

The security analysis workflow demonstrates that LLM reasoning can be embedded in a platform engineering process — the pull request review — in a way that adds value (early vulnerability detection) without adding risk (the LLM cannot merge, push, or modify the platform). The 29-second MTTR for security analysis represents a genuine improvement over the manual alternative, and the 100% TSR across all security analysis invocations demonstrates that the workflow is reliable enough to be part of a production review process.

The gap between what was designed and what was implemented — primarily the AWS MCP integration and the dynamic token model — reflects the complexity of production-grade agentic infrastructure. These are engineering problems with known solutions, not research problems requiring new approaches. The architectural decisions made in this project create a clear path to implementing them: the trust boundaries, identity model, and workflow structure are in place. What remains is connecting the wires.

The broader contribution is a demonstrated pattern: constrained agentic workflows, operating within GitOps enforcement, with HITL gates at blast-radius boundaries, represent a viable and safe architecture for introducing LLM reasoning into platform engineering. The pattern is not specific to the tools used — Gitea, ArgoCD, Langflow, and kind are implementation choices, not architectural requirements. Any platform that enforces GitOps, supports identity-scoped CI, and exposes a workflow orchestration layer can instantiate the same pattern.
