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

## Quick Start

Spin up the full platform locally with one command:

```bash
idpbuilder create \
  --use-path-routing \
  -c gitea:./control-system-infrastructure/cnoe-stack/gitea-config/override.yaml \
  -p ./control-system-infrastructure/cnoe-stack/packages/local-registry
```

Then register the Gitea Actions runner (host Docker). See `control-system-infrastructure/README.md` for the full bootstrap sequence including pre-requisites.
