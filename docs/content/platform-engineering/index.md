# Platform Engineering

This section covers the infrastructure and CI/CD platform built to support the CIM-AI project.
The platform follows a **GitOps-first** approach using [idpbuilder](https://cnoe.io/docs/reference-implementation/installations/idpbuilder)
to bootstrap a local Internal Developer Platform (IDP) with a single command.

## Contents

| Page | Description |
|------|-------------|
| [idpbuilder & CNOE](01-idpbuilder-and-cnoe.md) | Overview of the CNOE ecosystem, idpbuilder architecture, and how packages are processed |
| [CD Workflow Design](02-cd-workflow-design.md) | End-to-end CI/CD pipeline: Gitea Actions → local registry → ArgoCD → Kubernetes |
| [Manual Setup (Gitea Actions)](03-manual-setup-gitea-actions.md) | Step-by-step guide to setting up the runner, registry, and ArgoCD application manually |
| [Secret Scanning](04-secret-scanning.md) | Platform-enforced gitleaks scanning installed into every Gitea repo automatically |
| [Sandbox Environments](05-sandbox-environments.md) | Ephemeral PR-based sandbox environments for AI agent testing, powered by ArgoCD ApplicationSet PR generator |

## Architecture: Three Platform Packages

The control plane is bootstrapped from three ArgoCD-managed CNOE packages, each with a distinct responsibility:

```
idpbuilder create \
  --use-path-routing \
  -c gitea:./control-system-infrastructure/cnoe-stack/gitea-config/override.yaml \
  -p ./control-system-infrastructure/cnoe-stack/packages/gitea-runner \
  -p ./control-system-infrastructure/cnoe-stack/packages/platform-workflows \
  -p ./control-system-infrastructure/cnoe-stack/packages/sandbox-environments
```

| Package | What it deploys | Key resource |
|---|---|---|
| `gitea-runner` | In-cluster Gitea Actions runner (DinD) | `Deployment: gitea-runner` + PVC |
| `platform-workflows` | Workflow enforcement CronJob | `CronJob: platform-workflow-sync` |
| `sandbox-environments` | ArgoCD sandbox infrastructure | `AppProject: sandbox` + PostSync setup Job |

## Quick Start

Spin up the full platform locally:

```bash
# Bootstrap the control plane
idpbuilder create \
  --use-path-routing \
  -c gitea:./control-system-infrastructure/cnoe-stack/gitea-config/override.yaml \
  -p ./control-system-infrastructure/cnoe-stack/packages/gitea-runner \
  -p ./control-system-infrastructure/cnoe-stack/packages/platform-workflows \
  -p ./control-system-infrastructure/cnoe-stack/packages/sandbox-environments

# After sync completes, run the sandbox bootstrap steps
# See: control-system-infrastructure/cnoe-stack/packages/sandbox-environments/README.md
```

The in-cluster runner self-registers with Gitea via an init container. No manual runner setup is required.
