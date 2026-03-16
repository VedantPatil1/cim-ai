# FastAPI — EKS GitOps CI/CD Implementation Plan
> Stack: GitHub Actions · ECR · EKS Fargate · ArgoCD · Kustomize · Terraform

---

## Overview

```
fastapi-app/          (Code Repo)
fastapi-deploy/       (Deploy Repo — GitOps source of truth)
fastapi-infra/        (Infrastructure Repo — Terraform)
```

---

## PART 1 — AWS ACCOUNT SETUP

### 1.1 Bootstrap IAM

**Task:** Create a dedicated IAM user for Terraform bootstrap (one-time only).
- Attach `AdministratorAccess` temporarily
- Generate access keys, store in local `~/.aws/credentials`
- After Terraform runs, revoke this user and switch to roles only

**Task:** Enable IAM Identity Center (SSO) for human access.
- No long-lived human IAM users
- Developers assume roles via SSO

---

### 1.2 GitHub Actions OIDC Trust (No Static Keys)

**Task:** Create IAM OIDC provider for GitHub Actions.

```hcl
# infra/iam/github-oidc.tf
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}
```

**Task:** Create IAM Role — `github-actions-ecr-push`
- Trust: `repo:YOUR_ORG/fastapi-app:ref:refs/heads/main`
- Permissions:
  - `ecr:GetAuthorizationToken`
  - `ecr:BatchCheckLayerAvailability`
  - `ecr:PutImage`
  - `ecr:InitiateLayerUpload`
  - `ecr:UploadLayerPart`
  - `ecr:CompleteLayerUpload`

**Task:** Create IAM Role — `github-actions-deploy`
- Trust: `repo:YOUR_ORG/fastapi-deploy:*`
- Permissions (deploy repo CD only):
  - `ecr:DescribeImages`
  - `eks:DescribeCluster`
  - `sts:GetCallerIdentity`

---

### 1.3 ECR Repository

**Task:** Create ECR repository `fastapi-app`.

```hcl
# infra/ecr/main.tf
resource "aws_ecr_repository" "fastapi" {
  name                 = "fastapi-app"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "fastapi" {
  repository = aws_ecr_repository.fastapi.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 20 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}
```

---

### 1.4 Networking (VPC)

**Task:** Create VPC with public/private subnets.

```hcl
# infra/vpc/main.tf
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "fastapi-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["us-east-1a", "us-east-1b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway   = true
  single_nat_gateway   = true   # cost saving — use one NAT
  enable_dns_hostnames = true

  # Required EKS tags
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }
}
```

---

### 1.5 EKS Cluster (Fargate)

**Task:** Create EKS cluster with Fargate profiles only (no EC2 nodes).

```hcl
# infra/eks/main.tf
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "fastapi-cluster"
  cluster_version = "1.30"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Fargate only — no managed node groups
  fargate_profiles = {
    staging = {
      selectors = [
        { namespace = "staging" },
        { namespace = "argocd" }
      ]
    }
    prod = {
      selectors = [
        { namespace = "prod" }
      ]
    }
    kube_system = {
      selectors = [
        { namespace = "kube-system" }
      ]
    }
  }

  cluster_addons = {
    coredns    = { most_recent = true }
    kube-proxy = { most_recent = true }
    vpc-cni    = { most_recent = true }
  }
}
```

---

### 1.6 AWS Load Balancer Controller

**Task:** Install AWS Load Balancer Controller via Helm (Terraform).
- Required to provision ALBs from Kubernetes Ingress resources
- Runs in `kube-system` namespace on Fargate

```hcl
# infra/eks/alb-controller.tf
resource "helm_release" "alb_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"

  set {
    name  = "clusterName"
    value = module.eks.cluster_name
  }
  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.alb_controller.arn
  }
}
```

---

### 1.7 Secrets Manager

**Task:** Create secrets for each environment.

```
/fastapi/staging/DATABASE_URL
/fastapi/staging/SECRET_KEY
/fastapi/prod/DATABASE_URL
/fastapi/prod/SECRET_KEY
```

Pods access these via the AWS Secrets Store CSI driver or directly via the AWS SDK.

---

### 1.8 Terraform State Backend

**Task:** Create S3 bucket + DynamoDB table for remote state.

```hcl
# bootstrap/backend.tf
resource "aws_s3_bucket" "tfstate" {
  bucket = "fastapi-tfstate-ACCOUNT_ID"
}

resource "aws_dynamodb_table" "tflock" {
  name         = "fastapi-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}
```

---

## PART 2 — CODE REPO (`fastapi-app`)

### 2.1 Repository Structure

```
fastapi-app/
├── app/
│   ├── main.py
│   ├── routers/
│   ├── models/
│   └── dependencies.py
├── tests/
│   ├── unit/
│   └── integration/
├── Dockerfile
├── pyproject.toml           ← ruff + pytest config lives here
├── .dockerignore
└── .github/
    └── workflows/
        ├── checks.yml       ← develop branch
        └── release.yml      ← main branch
```

---

### 2.2 Dockerfile (Multi-Stage)

**Task:** Create `Dockerfile` at repo root.

```dockerfile
# Stage 1 — dependencies
FROM python:3.12-slim AS deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2 — final image
FROM python:3.12-slim AS final
WORKDIR /app

# Non-root user
RUN addgroup --system app && adduser --system --group app

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY ./app ./app

USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### 2.3 pyproject.toml Config

**Task:** Configure ruff and pytest in `pyproject.toml`.

```toml
[tool.ruff]
line-length = 88
select = ["E", "F", "I", "N", "W"]

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=app --cov-report=term-missing --cov-fail-under=80"
```

---

### 2.4 GitHub Actions — `checks.yml`

**Task:** Create `.github/workflows/checks.yml`

Trigger: push and pull_request to `develop`

```yaml
name: Checks

on:
  push:
    branches: [develop]
  pull_request:
    branches: [develop]

jobs:
  secret-scan:
    name: Trivy Secret Scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Trivy secret scanner
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: fs
          scan-ref: .
          scanners: secret
          exit-code: 1           # fail pipeline on secrets found
          severity: HIGH,CRITICAL

  lint:
    name: Ruff Lint + Format
    runs-on: ubuntu-latest
    needs: secret-scan           # only lint if no secrets found
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff
      - run: ruff check .
      - run: ruff format --check .

  test:
    name: Pytest + Coverage
    runs-on: ubuntu-latest
    needs: lint                  # only test if lint passes
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest
      - name: Upload coverage report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: coverage-report
          path: htmlcov/
```

**Job execution order:**
```
secret-scan → lint → test
     │            │       │
   blocks       blocks  uploads
   lint if      test     coverage
   secrets      if lint  artifact
   found        fails
```

---

### 2.5 GitHub Actions — `release.yml`

**Task:** Create `.github/workflows/release.yml`

Trigger: push to `main` only

```yaml
name: Release

on:
  push:
    branches: [main]

permissions:
  id-token: write    # required for OIDC
  contents: read

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: fastapi-app

jobs:
  build-and-push:
    name: Build + Push to ECR
    runs-on: ubuntu-latest
    outputs:
      image-tag: ${{ steps.meta.outputs.tag }}

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Set image tag
        id: meta
        run: |
          SHORT_SHA=$(echo $GITHUB_SHA | cut -c1-7)
          echo "tag=$SHORT_SHA" >> $GITHUB_OUTPUT

      - name: Build and push
        env:
          REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          TAG: ${{ steps.meta.outputs.tag }}
        run: |
          docker build -t $REGISTRY/$ECR_REPOSITORY:$TAG .
          docker tag $REGISTRY/$ECR_REPOSITORY:$TAG \
                     $REGISTRY/$ECR_REPOSITORY:latest
          docker push $REGISTRY/$ECR_REPOSITORY:$TAG
          docker push $REGISTRY/$ECR_REPOSITORY:latest

  trigger-deploy:
    name: Update Deploy Repo
    runs-on: ubuntu-latest
    needs: build-and-push

    steps:
      - name: Checkout deploy repo
        uses: actions/checkout@v4
        with:
          repository: YOUR_ORG/fastapi-deploy
          token: ${{ secrets.DEPLOY_REPO_PAT }}  # PAT with repo write access
          path: deploy-repo

      - name: Update staging image tag
        run: |
          cd deploy-repo
          # Update the image tag in staging overlay
          sed -i "s|newTag:.*|newTag: ${{ needs.build-and-push.outputs.image-tag }}|" \
            apps/fastapi-app/overlays/staging/kustomization.yaml
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "chore: update staging image to ${{ needs.build-and-push.outputs.image-tag }}"
          git push
```

---

### 2.6 Branch Protection Rules

**Task:** Configure in GitHub → Settings → Branches

For `develop`:
- Require PR before merging
- Require status checks: `secret-scan`, `lint`, `test`
- Require branches to be up to date before merging
- Block direct pushes

For `main`:
- Require PR before merging
- Only allow merges from `develop`
- Block direct pushes
- No status checks needed (main only receives tested code)

---

### 2.7 GitHub Secrets (Code Repo)

**Task:** Add these under Settings → Secrets → Actions

| Secret | Value |
|---|---|
| `AWS_ROLE_TO_ASSUME` | ARN of `github-actions-ecr-push` IAM role |
| `DEPLOY_REPO_PAT` | GitHub PAT with `repo` write scope for deploy repo |

---

## PART 3 — DEPLOY REPO (`fastapi-deploy`)

### 3.1 Repository Structure

```
fastapi-deploy/
├── apps/
│   └── fastapi-app/
│       ├── base/
│       │   ├── kustomization.yaml
│       │   ├── deployment.yaml
│       │   ├── service.yaml
│       │   ├── ingress.yaml
│       │   └── hpa.yaml
│       └── overlays/
│           ├── staging/
│           │   ├── kustomization.yaml     ← image tag lives here
│           │   └── patch-replicas.yaml
│           └── prod/
│               ├── kustomization.yaml     ← image tag lives here
│               └── patch-replicas.yaml
├── argocd/
│   ├── staging-app.yaml
│   └── prod-app.yaml
└── .github/
    └── workflows/
        └── promote.yml                   ← staging → prod promotion
```

---

### 3.2 Base Kubernetes Manifests

**Task:** Create `apps/fastapi-app/base/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: fastapi-app
  template:
    metadata:
      labels:
        app: fastapi-app
    spec:
      containers:
        - name: fastapi-app
          image: fastapi-app        # Kustomize will replace this
          ports:
            - containerPort: 8000
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
```

**Task:** Create `apps/fastapi-app/base/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: fastapi-app
spec:
  selector:
    app: fastapi-app
  ports:
    - port: 80
      targetPort: 8000
  type: ClusterIP
```

**Task:** Create `apps/fastapi-app/base/ingress.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: fastapi-app
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/healthcheck-path: /health
spec:
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: fastapi-app
                port:
                  number: 80
```

**Task:** Create `apps/fastapi-app/base/hpa.yaml`

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: fastapi-app
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: fastapi-app
  minReplicas: 1
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Task:** Create `apps/fastapi-app/base/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
  - ingress.yaml
  - hpa.yaml
```

---

### 3.3 Kustomize Overlays

**Task:** Create `apps/fastapi-app/overlays/staging/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: staging
resources:
  - ../../base
images:
  - name: fastapi-app
    newName: ACCOUNT.dkr.ecr.REGION.amazonaws.com/fastapi-app
    newTag: latest     # release.yml updates this value via sed
```

**Task:** Create `apps/fastapi-app/overlays/prod/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: prod
resources:
  - ../../base
images:
  - name: fastapi-app
    newName: ACCOUNT.dkr.ecr.REGION.amazonaws.com/fastapi-app
    newTag: latest     # promote.yml updates this value
```

---

### 3.4 Staging → Prod Promotion Workflow

**Task:** Create `.github/workflows/promote.yml`

Trigger: manual (`workflow_dispatch`) with tag input

```yaml
name: Promote to Prod

on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: "Image tag to promote to prod"
        required: true

jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Update prod image tag
        run: |
          sed -i "s|newTag:.*|newTag: ${{ inputs.image_tag }}|" \
            apps/fastapi-app/overlays/prod/kustomization.yaml
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "chore: promote ${{ inputs.image_tag }} to prod"
          git push
```

**Promotion flow:**
```
Staging verified ✅
     │
     ▼
Run promote.yml (manual trigger)
Enter image tag: abc123
     │
     ▼
prod/kustomization.yaml updated
     │
     ▼
ArgoCD detects change → syncs prod
```

---

## PART 4 — ARGOCD IMPLEMENTATION

### 4.1 Install ArgoCD into EKS

**Task:** Bootstrap ArgoCD via Helm in Terraform.

```hcl
# infra/eks/argocd.tf
resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  namespace        = "argocd"
  create_namespace = true
  version          = "6.7.0"    # pin version

  values = [
    <<-EOT
    server:
      ingress:
        enabled: true
        annotations:
          kubernetes.io/ingress.class: alb
          alb.ingress.kubernetes.io/scheme: internet-facing
          alb.ingress.kubernetes.io/target-type: ip
        hosts:
          - argocd.yourdomain.com
    configs:
      params:
        server.insecure: true    # TLS terminated at ALB
    EOT
  ]
}
```

---

### 4.2 ArgoCD Application Manifests

**Task:** Create `argocd/staging-app.yaml` in deploy repo.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: fastapi-staging
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io   # cleanup on delete
spec:
  project: default

  source:
    repoURL: https://github.com/YOUR_ORG/fastapi-deploy
    targetRevision: HEAD
    path: apps/fastapi-app/overlays/staging

  destination:
    server: https://kubernetes.default.svc
    namespace: staging

  syncPolicy:
    automated:
      prune: true       # delete resources removed from git
      selfHeal: true    # revert manual kubectl changes
    syncOptions:
      - CreateNamespace=true
    retry:
      limit: 3
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

**Task:** Create `argocd/prod-app.yaml` in deploy repo.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: fastapi-prod
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default

  source:
    repoURL: https://github.com/YOUR_ORG/fastapi-deploy
    targetRevision: HEAD
    path: apps/fastapi-app/overlays/prod

  destination:
    server: https://kubernetes.default.svc
    namespace: prod

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
    retry:
      limit: 3
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

---

### 4.3 Bootstrap ArgoCD with App-of-Apps

**Task:** Apply ArgoCD Application manifests after install.

```bash
# One-time bootstrap — after Terraform runs
kubectl apply -f argocd/staging-app.yaml
kubectl apply -f argocd/prod-app.yaml
```

After this, ArgoCD manages itself. No further kubectl commands needed for deploys.

---

### 4.4 Connect Deploy Repo to ArgoCD

**Task:** Add deploy repo as ArgoCD repository (private repos need credentials).

```bash
argocd repo add https://github.com/YOUR_ORG/fastapi-deploy \
  --username git \
  --password YOUR_GITHUB_PAT
```

Or via Kubernetes secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: fastapi-deploy-repo
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: https://github.com/YOUR_ORG/fastapi-deploy
  password: YOUR_GITHUB_PAT
  username: git
```

---

### 4.5 ArgoCD Sync Behaviour

| Setting | Staging | Prod |
|---|---|---|
| Auto sync | ✅ Yes | ✅ Yes |
| Self-heal | ✅ Yes | ✅ Yes |
| Prune | ✅ Yes | ✅ Yes |
| Promotion trigger | Automatic (release.yml) | Manual (promote.yml) |

**Self-heal** means: if someone runs `kubectl set image` directly,
ArgoCD will revert it within 3 minutes. Git is always the truth.

---

### 4.6 Rollback Procedure

No kubectl required. Rollback is a git operation:

```bash
# Find the previous good commit
git log --oneline apps/fastapi-app/overlays/prod/kustomization.yaml

# Revert
git revert HEAD
git push

# ArgoCD detects the change and rolls back automatically
```

---

### 4.7 ArgoCD Notifications (Optional)

**Task:** Install ArgoCD Notifications to Slack/email on sync failures.

```yaml
# values for helm release
notifications:
  enabled: true
  secret:
    create: true
  cm:
    create: true
```

Configure triggers for:
- `on-sync-failed` → Slack alert
- `on-health-degraded` → Slack alert
- `on-deployed` → Slack confirmation

---

## END-TO-END FLOW SUMMARY

```
Developer
   │
   ├── pushes to feature branch
   │       └── no pipeline triggered
   │
   ├── opens PR → develop
   │       └── checks.yml triggers:
   │               trivy (secrets scan)
   │               └── ruff (lint + format)
   │                   └── pytest (tests + coverage ≥ 80%)
   │
   ├── PR merged → develop
   │       └── checks.yml runs again on push
   │
   ├── PR opened: develop → main
   │       └── no workflow (code already tested)
   │
   └── PR merged → main
           └── release.yml triggers:
                   build Docker image
                   push to ECR (tag: abc1234 + latest)
                   └── update staging/kustomization.yaml in deploy repo
                           └── ArgoCD detects git change
                               sync staging namespace
                               new pod starts, health check passes
                               old pod terminated ✅

Staging verified by team
   └── trigger promote.yml (manual)
           input: image tag abc1234
           └── update prod/kustomization.yaml
                   └── ArgoCD detects git change
                       sync prod namespace
                       rolling deploy ✅
```

---

## IMPLEMENTATION ORDER FOR CLAUDE CODE

```
Phase 1 — AWS Foundation
  [ ] 1. Terraform S3 + DynamoDB backend bootstrap
  [ ] 2. Terraform VPC
  [ ] 3. Terraform IAM (OIDC, ECR push role)
  [ ] 4. Terraform ECR repository + lifecycle policy
  [ ] 5. Terraform EKS cluster + Fargate profiles
  [ ] 6. Terraform ALB controller Helm release
  [ ] 7. Terraform ArgoCD Helm release

Phase 2 — Code Repo
  [ ] 8.  Dockerfile (multi-stage)
  [ ] 9.  pyproject.toml (ruff + pytest config)
  [ ] 10. .dockerignore
  [ ] 11. checks.yml (trivy → ruff → pytest)
  [ ] 12. release.yml (build + push + update deploy repo)
  [ ] 13. GitHub branch protection rules (manual, via UI)
  [ ] 14. GitHub Secrets: AWS_ROLE_TO_ASSUME, DEPLOY_REPO_PAT

Phase 3 — Deploy Repo
  [ ] 15. Base manifests: deployment, service, ingress, hpa, kustomization
  [ ] 16. Overlay: staging/kustomization.yaml
  [ ] 17. Overlay: prod/kustomization.yaml
  [ ] 18. promote.yml workflow

Phase 4 — ArgoCD
  [ ] 19. argocd/staging-app.yaml
  [ ] 20. argocd/prod-app.yaml
  [ ] 21. Bootstrap: kubectl apply ArgoCD Application manifests
  [ ] 22. Connect deploy repo to ArgoCD (GitHub PAT secret)
  [ ] 23. Verify ArgoCD dashboard shows both apps Synced + Healthy
```
