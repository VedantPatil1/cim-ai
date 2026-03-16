# sample-api — Master Project Document
> Complete reference for the CI/CD pipeline setup
> AWS Account: 065571033838 | Region: us-east-1

---

## Dissertation Context

This project is the infrastructure foundation for a dissertation on:

1. Identifying secure practices, design patterns, and guardrails for
   Agentic Systems in sensitive production environments
2. Leveraging LLM-based reasoning across infrastructure state, GitOps
   repositories, IaC definitions, CI/CD pipelines, and operational docs
3. Designing controlled automation mechanisms that prioritise security,
   reliability, and traceability over full autonomy
4. Providing Zero Touch Provisioning (ZTP) capabilities for continuous
   and progressive enhancements for Agentic Systems

The infrastructure is deliberately observable and machine-readable at
every layer — Terraform state, ArgoCD Application CRs, Kubernetes API,
GitHub Actions workflows — to serve as inputs for LLM-based reasoning.

---

## Repository Structure

```
sample-api-app/        FastAPI application code + CI/CD workflows
sample-api-infra/      Terraform infrastructure (manually applied)
sample-api-deploy/     Kubernetes manifests — GitOps source of truth (planned)
sample-api-docs/       Zensical documentation site (planned)
```

---

## Technology Stack

| Layer | Technology | Reason |
|---|---|---|
| Compute | EKS Fargate | No node management, pay per pod |
| Orchestration | Kubernetes 1.30 | Industry standard, portable |
| GitOps | ArgoCD | Mature k8s GitOps, traceable |
| Manifests | Kustomize | Base + overlays per environment |
| Registry | ECR | Native EKS integration |
| CI | GitHub Actions | Already standard |
| IaC | Terraform | Manually triggered, auditable |
| Secrets | AWS Secrets Manager | Runtime injection |
| Ingress | AWS ALB Controller | Required for Fargate |
| State | S3 + DynamoDB | Remote state + locking |

---

## Naming Convention

Pattern: `sample-api-{component}-{type}`

All IAM roles and policies must follow `sample-api-*` prefix —
the executor policy is scoped to this prefix.

| Resource | Name |
|---|---|
| AWS Account | 065571033838 |
| Personal admin | `vedant-admin` (outside project convention) |
| CLI user | `sample-api-cli-user` |
| Terraform role | `sample-api-terraform-executor-role` |
| Terraform policy | `sample-api-terraform-executor-policy` |
| ALB controller role | `sample-api-alb-controller-role` |
| ALB controller policy | `sample-api-alb-controller-policy` |
| EKS cluster | `sample-api-cluster` |
| ECR repository | `sample-api-ecr` |
| VPC | `sample-api-vpc` |
| S3 state bucket | `sample-api-tfstate-065571033838` |
| DynamoDB lock table | `sample-api-tfstate-lock` |
| Future IAM roles | `sample-api-*` |
| Future IAM policies | `sample-api-*` |

---

## AWS IAM Setup

### Identity Model

```
vedant-admin (IAM user)
  Console access + MFA
  AdministratorAccess
  No access keys — break-glass only

sample-api-cli-user (IAM user)
  No console access
  One permission only: assume terraform executor role
  Access keys stored in ~/.aws/credentials

sample-api-terraform-executor-role (IAM role)
  Assumed by sample-api-cli-user
  Holds all Terraform permissions
  Scoped to sample-api-* resources where possible
```

### Local AWS Profile Config

```ini
# ~/.aws/config
[profile sample-api-cli]
region = us-east-1

[profile sample-api-terraform]
role_arn       = arn:aws:iam::065571033838:role/sample-api-terraform-executor-role
source_profile = sample-api-cli
region         = us-east-1
```

```bash
# Set before every Terraform or AWS CLI operation
export AWS_PROFILE=sample-api-terraform
```

### Executor Policy Scope

| Service | Resource Scope |
|---|---|
| EC2, EKS, ECR, ELB, KMS, CloudWatch | `*` (describe actions require it) |
| S3 bucket actions | `sample-api-tfstate-*` only |
| S3 object actions | `sample-api-tfstate-*/*` only |
| DynamoDB | `sample-api-*` tables only |
| Secrets Manager | `sample-api-*` secrets only |
| IAM Role actions | `sample-api-*` roles only |
| IAM Policy actions | `sample-api-*` policies only |
| `iam:PassRole` | `sample-api-*` + PassedToService condition |
| `iam:CreateServiceLinkedRole` | eks, eks-fargate, elb paths only |
| OIDC | eks + GitHub Actions provider ARNs only |

---

## Infrastructure — Current State

### Permanent (always running)

| Resource | Cost |
|---|---|
| S3 state bucket | ~$0.00/mo |
| DynamoDB lock table | ~$0.07/mo |
| ECR repository | ~$0.01/mo |

### On-demand (destroy when not working)

| Resource | Cost |
|---|---|
| VPC + NAT Gateway | ~$32/mo / ~$1.08/day |
| EKS control plane | ~$73/mo / ~$2.40/day |
| Fargate pods | ~$5-15/mo / ~$0.24/day |
| ALB | ~$16/mo / ~$0.53/day |
| **Total active** | **~$4.00/day** |

---

## Terraform Module Structure

```
sample-api-infra/
├── bootstrap/          Local state — run once only
│   └── main.tf         Creates S3 + DynamoDB
├── ecr/                Remote state
│   └── main.tf         ECR repository + lifecycle policy
├── vpc/                Remote state
│   └── main.tf         VPC, subnets, NAT, IGW
├── eks/                Remote state
│   ├── main.tf         EKS cluster + Fargate profiles
│   └── alb-controller.tf  ALB controller IAM + Helm release
└── k8s-manual-test/    Temporary — manual deploy manifests
    └── deployment.yaml
```

### Remote State Backend (all modules except bootstrap)

```hcl
terraform {
  backend "s3" {
    bucket         = "sample-api-tfstate-065571033838"
    key            = "MODULE_NAME/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "sample-api-tfstate-lock"
    encrypt        = true
  }
}
```

| Module | Key |
|---|---|
| ecr | `ecr/terraform.tfstate` |
| vpc | `vpc/terraform.tfstate` |
| eks | `eks/terraform.tfstate` |

---

## EKS Cluster

```
Name:      sample-api-cluster
Version:   1.30
Region:    us-east-1
Type:      Fargate only (no EC2 nodes)
```

### Fargate Profiles

| Profile | Namespace |
|---|---|
| `sample-api-kube-system` | kube-system |
| `sample-api-argocd` | argocd |
| `sample-api-staging` | staging |
| `sample-api-prod` | prod |

### Cluster Addons

- CoreDNS (Fargate mode)
- kube-proxy
- vpc-cni

### kubectl Access

```bash
aws eks update-kubeconfig \
  --name sample-api-cluster \
  --region us-east-1 \
  --profile sample-api-terraform
```

---

## FastAPI Application

### Repository: `sample-api-app`

```
src/
└── main.py          FastAPI app — module path: main:app
requirements.txt
requirements.dev.txt
Dockerfile.python    Production Dockerfile
docker-compose.yml   Local development only
```

### Key App Details

```
Framework:      FastAPI
Entry point:    uvicorn main:app --host 0.0.0.0 --port 8000
Health check:   GET /health → {"status": "ok"}
Required env:   SECRET_KEY
Port:           8000
```

### Dockerfile (final version)

```dockerfile
FROM --platform=linux/amd64 python:3.12-slim
LABEL maintainer="vedantpatil.w.1@gmail.com"
ENV PYTHONUNBUFFERED=1
COPY ./requirements.txt /tmp/requirements.txt
COPY ./requirements.dev.txt /tmp/requirements.dev.txt
COPY ./src /src
WORKDIR /src
EXPOSE 8000
ARG DEV=false
RUN python -m venv /py && \
    /py/bin/pip install --upgrade pip && \
    /py/bin/pip install --no-cache-dir -r /tmp/requirements.txt && \
    if [ "$DEV" = "true" ]; \
        then /py/bin/pip install --no-cache-dir -r /tmp/requirements.dev.txt ; \
    fi && \
    rm -rf /tmp && \
    adduser --disabled-password --no-create-home app-user
ENV PATH="/py/bin:$PATH"
USER app-user
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### ECR Image Tags

| Tag | Status | Notes |
|---|---|---|
| `manual-test` | Old | Chunk 3 test — bad Dockerfile |
| `v1` | Old | Missing SECRET_KEY caused crash |
| `v2` | Current | Working — deployed to staging |

### Build Command (M1 Mac)

```bash
docker build --platform linux/amd64 -t sample-api-ecr .
```

Always use `--platform linux/amd64` on M1 — EKS Fargate runs amd64.

---

## ECR Push Sequence

```bash
export AWS_PROFILE=sample-api-terraform

# Authenticate
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS \
    --password-stdin 065571033838.dkr.ecr.us-east-1.amazonaws.com

# Build
docker build --platform linux/amd64 -t sample-api-ecr .

# Tag
docker tag sample-api-ecr:latest \
  065571033838.dkr.ecr.us-east-1.amazonaws.com/sample-api-ecr:TAG

# Push
docker push 065571033838.dkr.ecr.us-east-1.amazonaws.com/sample-api-ecr:TAG
```

---

## Session Management

### Start of Session

```bash
export AWS_PROFILE=sample-api-terraform

# Recreate VPC first
cd sample-api-infra/vpc && terraform apply

# Then EKS
cd sample-api-infra/eks && terraform apply

# Update kubeconfig
aws eks update-kubeconfig \
  --name sample-api-cluster \
  --region us-east-1 \
  --profile sample-api-terraform
```

### End of Session

```bash
# Always delete k8s resources first if ALB exists
kubectl delete -f sample-api-infra/k8s-manual-test/deployment.yaml

# Wait for ALB to be deleted
kubectl get ingress -n staging

# Then destroy — EKS before VPC
cd sample-api-infra/eks && terraform destroy
cd sample-api-infra/vpc && terraform destroy
```

---

## Planned Pipeline Design

### Two-Repo GitOps Model

```
sample-api-app (code repo)
  develop branch → checks.yml (trivy, ruff, pytest)
  main branch    → release.yml (build + push ECR + update deploy repo)

sample-api-deploy (deploy repo)
  ArgoCD watches this repo
  staging/ → auto-synced on every main merge
  prod/    → manually promoted via promote.yml
```

### GitHub Actions Workflows (planned)

**checks.yml** — triggers on push/PR to develop
```
trivy secret scan → ruff lint + format → pytest + coverage ≥ 80%
```

**release.yml** — triggers on push to main
```
Build image (linux/amd64) → push to ECR (git SHA tag)
→ update image tag in sample-api-deploy staging overlay
→ ArgoCD detects change → syncs staging namespace
```

**promote.yml** — manual trigger
```
Input: image tag
→ update image tag in sample-api-deploy prod overlay
→ ArgoCD detects change → syncs prod namespace
```

### ArgoCD Application Model (planned)

```
fastapi-staging → watches apps/sample-api/overlays/staging
                  auto-sync + self-heal
                  namespace: staging

fastapi-prod    → watches apps/sample-api/overlays/prod
                  auto-sync + self-heal
                  namespace: prod
```

### Rollback

```bash
# Git revert the image tag commit in deploy repo
git revert HEAD
git push
# ArgoCD reconciles automatically
```

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| EKS over ECS | GitOps with ArgoCD is far more mature on Kubernetes |
| Fargate over EC2 nodes | No node patching, no idle cost |
| Terraform manually applied | Infra changes are intentional and reviewed |
| Two repos (app + deploy) | ArgoCD watches deploy repo only — clean separation |
| Three repos (+ infra) | Terraform lifecycle independent of app deploys |
| OIDC over static keys | No credentials stored in GitHub |
| Custom IAM policy | Auditable, no unnecessary permissions from managed policies |
| `sample-api-*` naming | Policy scoping requires consistent prefix |
| Single NAT Gateway | Cost saving — resilience not needed for PoC |
| Local state for bootstrap | Chicken-and-egg — cannot use remote state to create remote state |

---

## IAM Lessons Learned

Issues encountered and resolved during setup — useful reference:

| Issue | Resolution |
|---|---|
| `kms:TagResource` denied | Added KMS statement to executor policy |
| `logs:CreateLogGroup` denied | Added CloudWatch Logs statement |
| `kms:DeleteKey` invalid action | Removed — use `kms:ScheduleKeyDeletion` |
| S3 redundant ARN warning | Split into bucket-level and object-level statements |
| OIDC provider ARN mismatch | Added `oidc.eks.us-east-1.amazonaws.com/*` |
| Fargate profile names not matching `sample-api-*` | Added `sample-api-` prefix to all profile names |
| `iam:CreateServiceLinkedRole` denied | Fixed path to `eks-fargate.amazonaws.com` |
| kubectl credentials error | Added `access_entries` block to EKS module |
| Policy exceeded 6144 char limit | Consolidated verbose action lists with wildcards |
| ALB controller VPC ID missing | Fargate has no instance metadata — pass `vpcId` explicitly |
| `ec2:GetSecurityGroupsForVpc` denied | Added to ALB controller policy |
| `elasticloadbalancing:DescribeListenerAttributes` denied | Added to ALB controller policy |

---

## Remaining Chunks

| Chunk | Description |
|---|---|
| 7 | GitHub Actions CI — checks.yml (develop branch) |
| 8 | GitHub Actions CD — release.yml (main → ECR) |
| 9 | Deploy repo + Kustomize manifests |
| 10 | ArgoCD install + first GitOps sync |
| 11 | Full GitOps loop — release.yml updates deploy repo |
| 12 | Prod environment + manual promotion |

### Parallel Track (local)

While the above chunks are built, a local cluster track runs in parallel:

```
k3d or minikube on laptop
ArgoCD installed locally
Full GitOps pipeline practiced at zero cost
Manifests identical to AWS — transfers directly
```

---

## CLAUDE.md — For Claude Code Sessions

When opening any repo in Claude Code, this is the essential context:

```
Project:     sample-api
Goal:        EKS Fargate + ArgoCD GitOps CI/CD pipeline
             Dissertation infrastructure for Agentic Systems research

AWS Account: 065571033838
Region:      us-east-1
Profile:     sample-api-terraform (always use this)

Naming:      All resources prefixed sample-api-*
             IAM policy scoped to this prefix — do not deviate

Current:     Chunks 0-6 complete
             App deployed manually to EKS staging
             ECR image: v2
             No GitHub Actions yet
             No ArgoCD yet
             No deploy repo yet

Next:        Chunk 7 — checks.yml GitHub Actions workflow
```
