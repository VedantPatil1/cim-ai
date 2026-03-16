# FastAPI → EKS GitOps — Phased Implementation Plan
> Starting point: Fresh AWS account · Docker + Terraform installed · FastAPI app exists

---

## Ground Rules

- Each chunk is independently completable and verifiable
- Never move to the next chunk until the current one has a passing verification step
- Terraform is always run manually (`terraform apply`) — no automation touches infra
- GitHub Actions only automates app code (image build, image push, deploy repo update)
- Cost is called out explicitly at each chunk

---

## Chunk 0 — Local Tooling Baseline
**Cost: $0 | Time: ~1 hour**

### Goal
Get every CLI tool working and verified before touching AWS.

### Tasks

**Install AWS CLI**
```bash
# macOS
brew install awscli

# Linux
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install
```

**Install kubectl**
```bash
# macOS
brew install kubectl

# Linux
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

**Install ArgoCD CLI**
```bash
# macOS
brew install argocd

# Linux
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
```

**Install Helm**
```bash
# macOS
brew install helm

# Linux
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### Verify
```bash
aws --version          # aws-cli/2.x.x
terraform --version    # Terraform v1.x.x
kubectl version        # Client Version: v1.x.x
docker --version       # Docker version 2x.x
helm version           # version.BuildInfo{Version:"v3.x.x"
argocd version         # argocd: v2.x.x
```

### Exit State
All 6 commands return versions without errors.

---

## Chunk 1 — AWS Account Bootstrap
**Cost: $0 | Time: ~1 hour**

### Goal
Configure AWS access securely. Never use root. Never use long-lived keys in CI.

### Tasks

**Step 1: Secure the root account**
- Go to AWS Console → IAM → root account
- Enable MFA on root (mandatory)
- Do not create root access keys
- Log out of root after this step

**Step 2: Create an admin IAM user for your own access**
```
IAM → Users → Create user
  Username:     your-name-admin
  Access type:  Programmatic + Console
  Permissions:  AdministratorAccess (managed policy)
  MFA:          Enable immediately after creation
```

Save the access key ID and secret — shown only once.

**Step 3: Configure AWS CLI profile**
```bash
aws configure --profile fastapi-admin
# AWS Access Key ID:     YOUR_KEY
# AWS Secret Access Key: YOUR_SECRET
# Default region:        us-east-1
# Default output format: json

# Set as default for your session
export AWS_PROFILE=fastapi-admin

# Verify identity
aws sts get-caller-identity
```

Expected output:
```json
{
  "UserId": "AIDAXXXXXXXXXXXXXXXXX",
  "Account": "123456789012",
  "Arn": "arn:aws:iam::123456789012:user/your-name-admin"
}
```

**Step 4: Note your account ID**
```bash
aws sts get-caller-identity --query Account --output text
# Save this — you'll need it throughout
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

### Exit State
`aws sts get-caller-identity` returns your account ID and user ARN. No root keys exist.

---

## Chunk 2 — Terraform Remote State
**Cost: ~$0.50/mo | Time: ~30 mins**

### Goal
Before any Terraform can run, it needs a place to store state. This is a one-time
manual bootstrap using local state, then everything else uses remote state.

### Why This First
If you store Terraform state locally and your laptop dies, you lose track of
what AWS thinks exists. Remote state in S3 is the safety net.

### Repo Structure to Create
```
fastapi-infra/
├── bootstrap/        ← run once, local state only
│   └── main.tf
├── vpc/
├── ecr/
├── eks/
└── argocd/
```

### Tasks

**Create `fastapi-infra/bootstrap/main.tf`**
```hcl
provider "aws" {
  region = "us-east-1"
}

# S3 bucket for Terraform state
resource "aws_s3_bucket" "tfstate" {
  bucket = "fastapi-tfstate-${var.account_id}"

  lifecycle {
    prevent_destroy = true   # never accidentally delete state
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"   # keeps history of every state file
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# DynamoDB table for state locking (prevents concurrent applies)
resource "aws_dynamodb_table" "tflock" {
  name         = "fastapi-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

variable "account_id" {
  description = "AWS Account ID — keeps bucket name globally unique"
  type        = string
}

output "state_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}
```

**Run it**
```bash
cd fastapi-infra/bootstrap
terraform init
terraform apply -var="account_id=YOUR_ACCOUNT_ID"
```

Type `yes` when prompted.

**From here on, all other Terraform modules use this backend block**
```hcl
# Add this to every module's main.tf
terraform {
  backend "s3" {
    bucket         = "fastapi-tfstate-YOUR_ACCOUNT_ID"
    key            = "MODULE_NAME/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "fastapi-tfstate-lock"
    encrypt        = true
  }
}
```

### Verify
```bash
aws s3 ls | grep fastapi-tfstate
aws dynamodb list-tables | grep fastapi-tfstate-lock
```

### Exit State
S3 bucket and DynamoDB table exist. All future Terraform modules will write state
there. You will never run the bootstrap again.

---

## Chunk 3 — ECR Repository
**Cost: ~$0.10/mo | Time: ~20 mins**

### Goal
Create the container registry where your Docker images will live.
Verify you can push an image manually before any automation exists.

### Tasks

**Create `fastapi-infra/ecr/main.tf`**
```hcl
terraform {
  backend "s3" {
    bucket         = "fastapi-tfstate-YOUR_ACCOUNT_ID"
    key            = "ecr/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "fastapi-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_ecr_repository" "fastapi" {
  name                 = "fastapi-app"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true   # free Trivy-like scanning on every push
  }
}

resource "aws_ecr_lifecycle_policy" "fastapi" {
  repository = aws_ecr_repository.fastapi.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images only"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

output "repository_url" {
  value = aws_ecr_repository.fastapi.repository_url
}
```

**Apply**
```bash
cd fastapi-infra/ecr
terraform init
terraform apply
```

**Manually build and push your app image**
```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS \
  --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# Build your image
cd path/to/fastapi-app
docker build -t fastapi-app .

# Tag and push
docker tag fastapi-app:latest \
  YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/fastapi-app:manual-test

docker push \
  YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/fastapi-app:manual-test
```

### Verify
```bash
aws ecr list-images --repository-name fastapi-app
# Should show your manual-test tag
```

### Exit State
ECR repository exists. You have manually pushed an image and can see it in the console.
You know your Dockerfile works.

---

## Chunk 4 — VPC
**Cost: ~$32/mo (NAT Gateway) | Time: ~30 mins**

### Goal
Create the network your EKS cluster will live in. Private subnets for pods,
public subnets for the load balancer.

### ⚠️ Cost Note on NAT Gateway
NAT Gateway costs ~$32/mo. This is unavoidable for EKS Fargate — pods in private
subnets need outbound internet to pull images and call AWS APIs.
To minimise: only create this when actively working, destroy when done for the day
during development phase.

### Tasks

**Create `fastapi-infra/vpc/main.tf`**
```hcl
terraform {
  backend "s3" {
    bucket         = "fastapi-tfstate-YOUR_ACCOUNT_ID"
    key            = "vpc/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "fastapi-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-1"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "fastapi-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["us-east-1a", "us-east-1b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway   = true
  single_nat_gateway   = true   # one NAT only — cost saving
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Tags required by EKS and ALB controller
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }

  tags = {
    Project     = "fastapi"
    Environment = "shared"
  }
}

output "vpc_id"             { value = module.vpc.vpc_id }
output "private_subnet_ids" { value = module.vpc.private_subnets }
output "public_subnet_ids"  { value = module.vpc.public_subnets }
```

**Apply**
```bash
cd fastapi-infra/vpc
terraform init
terraform apply
```

### Verify
```bash
aws ec2 describe-vpcs --filters "Name=tag:Project,Values=fastapi" \
  --query "Vpcs[0].VpcId" --output text

aws ec2 describe-subnets \
  --filters "Name=tag:Project,Values=fastapi" \
  --query "Subnets[*].{ID:SubnetId,AZ:AvailabilityZone,Public:MapPublicIpOnLaunch}" \
  --output table
```

### Exit State
VPC exists with 2 private and 2 public subnets across 2 AZs. NAT Gateway running.

---

## Chunk 5 — EKS Cluster + Fargate
**Cost: ~$73/mo (control plane) | Time: ~45 mins**

### Goal
Create the EKS cluster with Fargate profiles only. No EC2 nodes.
Verify kubectl can talk to the cluster before deploying anything.

### ⚠️ Cost Note
The EKS control plane costs $73/mo flat. During development, you can
`terraform destroy` the cluster overnight and `terraform apply` next morning.
ECR and VPC persist — only EKS is destroyed and recreated.

### Tasks

**Create `fastapi-infra/eks/main.tf`**
```hcl
terraform {
  backend "s3" {
    bucket         = "fastapi-tfstate-YOUR_ACCOUNT_ID"
    key            = "eks/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "fastapi-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-1"
}

# Read VPC outputs from remote state
data "terraform_remote_state" "vpc" {
  backend = "s3"
  config = {
    bucket = "fastapi-tfstate-YOUR_ACCOUNT_ID"
    key    = "vpc/terraform.tfstate"
    region = "us-east-1"
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "fastapi-cluster"
  cluster_version = "1.30"

  vpc_id     = data.terraform_remote_state.vpc.outputs.vpc_id
  subnet_ids = data.terraform_remote_state.vpc.outputs.private_subnet_ids

  cluster_endpoint_public_access = true   # allows kubectl from laptop

  fargate_profiles = {
    kube_system = {
      selectors = [{ namespace = "kube-system" }]
    }
    argocd = {
      selectors = [{ namespace = "argocd" }]
    }
    staging = {
      selectors = [{ namespace = "staging" }]
    }
    prod = {
      selectors = [{ namespace = "prod" }]
    }
  }

  cluster_addons = {
    coredns    = { most_recent = true }
    kube-proxy = { most_recent = true }
    vpc-cni    = { most_recent = true }
  }

  tags = {
    Project = "fastapi"
  }
}

output "cluster_name"     { value = module.eks.cluster_name }
output "cluster_endpoint" { value = module.eks.cluster_endpoint }
```

**Apply (takes ~15 mins)**
```bash
cd fastapi-infra/eks
terraform init
terraform apply
```

**Configure kubectl**
```bash
aws eks update-kubeconfig \
  --name fastapi-cluster \
  --region us-east-1

# Test access
kubectl get nodes
kubectl get namespaces
```

### Verify
```bash
kubectl get nodes
# NAME                   STATUS   ROLES    AGE
# fargate-node-xxxxx     Ready    <none>   2m
# (Fargate shows virtual nodes)

kubectl get pods -n kube-system
# CoreDNS and other system pods should be Running
```

### Exit State
EKS cluster exists. `kubectl get nodes` works from your laptop.
You can see system pods running in kube-system.

---

## Chunk 6 — ALB Controller + Deploy App Manually
**Cost: included in above | Time: ~1 hour**

### Goal
Install the AWS Load Balancer Controller so Ingress resources create real ALBs.
Then deploy your FastAPI app manually using kubectl — no GitOps yet.
This proves your container runs correctly in Kubernetes before adding automation.

### Tasks

**Install ALB Controller via Helm**
```bash
# Add the EKS Helm repo
helm repo add eks https://aws.github.io/eks-charts
helm repo update

# Create IAM policy for ALB controller (one-time)
curl -O https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json

aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy \
  --policy-document file://iam_policy.json

# Create service account
eksctl create iamserviceaccount \
  --cluster fastapi-cluster \
  --namespace kube-system \
  --name aws-load-balancer-controller \
  --attach-policy-arn arn:aws:iam::YOUR_ACCOUNT_ID:policy/AWSLoadBalancerControllerIAMPolicy \
  --approve

# Install controller
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=fastapi-cluster \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller
```

**Create namespace**
```bash
kubectl create namespace staging
```

**Write a minimal deployment manifest to test**
```yaml
# manual-test/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-app
  namespace: staging
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
          image: YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/fastapi-app:manual-test
          ports:
            - containerPort: 8000
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: fastapi-app
  namespace: staging
spec:
  selector:
    app: fastapi-app
  ports:
    - port: 80
      targetPort: 8000
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: fastapi-app
  namespace: staging
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
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

```bash
kubectl apply -f manual-test/deployment.yaml

# Watch pod come up
kubectl get pods -n staging -w

# Get ALB address (takes ~2 mins to provision)
kubectl get ingress -n staging
```

### Verify
```bash
# Get the ALB URL
ALB=$(kubectl get ingress fastapi-app -n staging \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

curl http://$ALB/health
# Should return your FastAPI health response
```

### Exit State
FastAPI app is live in Kubernetes, reachable via an ALB URL.
You deployed it entirely by hand. This is your baseline.

---

## Chunk 7 — GitHub Actions CI (Zero AWS Involvement)
**Cost: $0 | Time: ~1 hour**

### Goal
Set up the checks pipeline on the code repo. No AWS, no deployments.
Just automated quality gates on the develop branch.

### Repo Setup

**Create two repos in GitHub**
```
fastapi-app/      ← your existing app code goes here
fastapi-deploy/   ← empty for now, will hold k8s manifests
```

**`fastapi-app` branch structure**
```
main     ← production releases only
develop  ← integration branch, PRs merge here
feature/ ← developer branches
```

**Create `.github/workflows/checks.yml`**
```yaml
name: Checks

on:
  push:
    branches: [develop]
  pull_request:
    branches: [develop]

jobs:

  secret-scan:
    name: Trivy — Secret Scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Trivy secret scan
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: fs
          scan-ref: .
          scanners: secret
          exit-code: 1
          severity: HIGH,CRITICAL

  lint:
    name: Ruff — Lint + Format
    runs-on: ubuntu-latest
    needs: secret-scan
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
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt
      - name: Run tests
        run: pytest
      - name: Upload coverage
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: htmlcov/
```

**`pyproject.toml` additions**
```toml
[tool.ruff]
line-length = 88
select = ["E", "F", "I", "N", "W"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=app --cov-report=term-missing --cov-report=html --cov-fail-under=80"
```

**requirements-dev.txt**
```
pytest
pytest-cov
ruff
httpx          # for FastAPI TestClient
```

### Verify
Push to develop → GitHub Actions runs → all 3 jobs pass green.
Break something intentionally → pipeline goes red.

### Exit State
Every push and PR to develop runs secret scan → lint → tests automatically.
Nothing deploys. No AWS credentials configured yet.

---

## Chunk 8 — GitHub Actions CD (Code Repo → ECR)
**Cost: $0 extra | Time: ~1 hour**

### Goal
Automate the image build and ECR push that you did manually in Chunk 3.
Uses OIDC — no static AWS keys stored in GitHub.

### Tasks

**Create IAM OIDC provider (one-time, via Terraform)**

Add to `fastapi-infra/ecr/main.tf`:
```hcl
# GitHub OIDC provider — allows GitHub Actions to assume AWS roles
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# IAM role that release.yml assumes
resource "aws_iam_role" "github_ecr_push" {
  name = "github-actions-ecr-push"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringLike = {
          # Only your main branch can assume this role
          "token.actions.githubusercontent.com:sub" =
            "repo:YOUR_ORG/fastapi-app:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_ecr_push" {
  role = aws_iam_role.github_ecr_push.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = "*"
      }
    ]
  })
}

output "github_ecr_role_arn" {
  value = aws_iam_role.github_ecr_push.arn
}
```

```bash
cd fastapi-infra/ecr
terraform apply
```

**Create `.github/workflows/release.yml`**
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
  build-push:
    name: Build + Push to ECR
    runs-on: ubuntu-latest
    outputs:
      image-tag: ${{ steps.meta.outputs.tag }}

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials (OIDC — no static keys)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Set image tag (short git SHA)
        id: meta
        run: echo "tag=$(echo $GITHUB_SHA | cut -c1-7)" >> $GITHUB_OUTPUT

      - name: Build and push
        env:
          REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          TAG: ${{ steps.meta.outputs.tag }}
        run: |
          docker build -t $REGISTRY/$ECR_REPOSITORY:$TAG .
          docker tag  $REGISTRY/$ECR_REPOSITORY:$TAG \
                      $REGISTRY/$ECR_REPOSITORY:latest
          docker push $REGISTRY/$ECR_REPOSITORY:$TAG
          docker push $REGISTRY/$ECR_REPOSITORY:latest
          echo "Pushed: $REGISTRY/$ECR_REPOSITORY:$TAG"
```

**Add GitHub Secret (code repo)**
```
Settings → Secrets → Actions → New repository secret
Name:  AWS_ROLE_ARN
Value: arn:aws:iam::YOUR_ACCOUNT_ID:role/github-actions-ecr-push
```

### Verify
```bash
# Merge something to main
# Watch Actions tab — build-push job should go green

# Then check ECR
aws ecr list-images --repository-name fastapi-app
# Should show a new tag matching the git SHA
```

### Exit State
Every merge to main builds a Docker image and pushes it to ECR automatically.
No AWS credentials stored anywhere. OIDC handles auth.

---

## Chunk 9 — Deploy Repo + Kustomize Manifests
**Cost: $0 | Time: ~1 hour**

### Goal
Move your manual manifests from Chunk 6 into the `fastapi-deploy` repo
with proper Kustomize structure. This repo becomes the GitOps source of truth.

### Deploy Repo Structure
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
│           │   └── kustomization.yaml
│           └── prod/
│               └── kustomization.yaml
└── argocd/
    ├── staging-app.yaml
    └── prod-app.yaml
```

Take the manifests from Chunk 6 and split into base + overlays.

**`apps/fastapi-app/overlays/staging/kustomization.yaml`**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: staging
resources:
  - ../../base
images:
  - name: fastapi-app
    newName: YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/fastapi-app
    newTag: latest    # release.yml will update this automatically
```

**Test Kustomize renders correctly before ArgoCD**
```bash
kubectl kustomize apps/fastapi-app/overlays/staging
# Should print the merged YAML — check image tag is correct

# Apply manually to verify
kubectl apply -k apps/fastapi-app/overlays/staging
kubectl get pods -n staging
```

### Exit State
Deploy repo exists. Kustomize renders correct manifests.
You can `kubectl apply -k` manually and your app runs.

---

## Chunk 10 — ArgoCD Install + First GitOps Sync
**Cost: ~$5/mo extra (ArgoCD pods on Fargate) | Time: ~1 hour**

### Goal
Install ArgoCD and connect it to the deploy repo. Watch it sync the cluster
state automatically for the first time. This is the moment GitOps begins.

### Tasks

**Install ArgoCD**
```bash
kubectl create namespace argocd

kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for pods
kubectl wait --for=condition=available deployment \
  --all -n argocd --timeout=300s
```

**Get initial admin password**
```bash
kubectl get secret argocd-initial-admin-secret \
  -n argocd \
  -o jsonpath="{.data.password}" | base64 -d && echo
```

**Port-forward to access UI**
```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Open: https://localhost:8080
# Login: admin / (password above)
# Change password immediately
```

**Connect deploy repo**
```bash
argocd login localhost:8080 --username admin --insecure

argocd repo add https://github.com/YOUR_ORG/fastapi-deploy \
  --username git \
  --password YOUR_GITHUB_PAT
```

**Apply ArgoCD Application manifests**
```bash
kubectl apply -f argocd/staging-app.yaml
```

**Watch the first sync**
```bash
argocd app get fastapi-staging
argocd app sync fastapi-staging   # trigger first sync manually

# Watch it go green
argocd app wait fastapi-staging --health
```

### Verify
```bash
argocd app list
# NAME             STATUS  HEALTH   SYNC
# fastapi-staging  Synced  Healthy  Synced ✅

# Confirm app still reachable
curl http://$ALB/health
```

### Exit State
ArgoCD is running. It synced your app from the deploy repo.
If you change a file in the deploy repo and push — ArgoCD applies it automatically.

---

## Chunk 11 — Close the Loop (Full GitOps Pipeline)
**Cost: $0 extra | Time: ~1 hour**

### Goal
Wire `release.yml` to automatically update the image tag in the deploy repo
after a successful ECR push. This closes the full loop — git push to app repo
results in automatic deployment with zero manual steps.

### Add deploy step to `release.yml`
```yaml
  # Add this job after build-push
  update-deploy-repo:
    name: Update Deploy Repo Image Tag
    runs-on: ubuntu-latest
    needs: build-push

    steps:
      - name: Checkout deploy repo
        uses: actions/checkout@v4
        with:
          repository: YOUR_ORG/fastapi-deploy
          token: ${{ secrets.DEPLOY_REPO_PAT }}

      - name: Update staging image tag
        run: |
          sed -i "s|newTag:.*|newTag: ${{ needs.build-push.outputs.image-tag }}|" \
            apps/fastapi-app/overlays/staging/kustomization.yaml

          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "chore: deploy ${{ needs.build-push.outputs.image-tag }} to staging"
          git push
```

**Add GitHub Secret (code repo)**
```
Name:  DEPLOY_REPO_PAT
Value: GitHub PAT with repo write access to fastapi-deploy
```

### Full Loop Test
```bash
# Make any change to your FastAPI app
echo "# test" >> app/main.py
git add . && git commit -m "test: trigger full pipeline"
git push origin develop

# PR develop → main
# Merge

# Watch in sequence:
# 1. release.yml builds image → pushes to ECR
# 2. release.yml updates staging/kustomization.yaml in deploy repo
# 3. ArgoCD detects the git change
# 4. ArgoCD syncs staging namespace
# 5. New pod comes up, old pod goes down
# 6. curl $ALB/health → still works ✅
```

### Exit State
Full pipeline is working end to end. No manual steps between code push and deployment.

---

## Chunk 12 — Prod Environment + Manual Promotion
**Cost: $0 extra | Time: ~30 mins**

### Goal
Add the prod namespace and ArgoCD app. Introduce a manual promotion gate
so staging is always verified before prod receives a deploy.

### Tasks

**Apply prod ArgoCD application**
```bash
kubectl apply -f argocd/prod-app.yaml
```

**Create `promote.yml` in deploy repo**
```yaml
name: Promote to Prod

on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: "Image tag to promote (e.g. abc1234)"
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

**Promote a build to prod**
```
GitHub → fastapi-deploy → Actions → Promote to Prod
→ Run workflow → input: abc1234
→ ArgoCD syncs prod automatically
```

### Exit State
Staging auto-deploys on every main merge. Prod only deploys via deliberate
manual trigger. Full GitOps. Zero kubectl for routine operations.

---

## Cost Summary by Chunk

| Chunk | What you have | Monthly cost |
|---|---|---|
| 0–1 | Tooling + AWS account | $0 |
| 2 | Terraform state (S3 + DynamoDB) | ~$0.50 |
| 3 | ECR repository | ~$0.10 |
| 4 | VPC + NAT Gateway | ~$32 |
| 5+ | EKS control plane | +$73 |
| 6+ | Fargate pods (your app) | +$5–15 |
| 10+ | ArgoCD pods on Fargate | +$5 |
| **Total running** | | **~$115–130/mo** |

**Development tip:** Destroy EKS + VPC when not working.
ECR and Terraform state cost pennies and should stay up.
```bash
# End of day
cd fastapi-infra/eks && terraform destroy
cd fastapi-infra/vpc && terraform destroy

# Next morning
cd fastapi-infra/vpc && terraform apply
cd fastapi-infra/eks && terraform apply
aws eks update-kubeconfig --name fastapi-cluster --region us-east-1
```

---

## Progress Tracker

```
[ ] Chunk 0  — Local tooling baseline
[ ] Chunk 1  — AWS account bootstrap
[ ] Chunk 2  — Terraform remote state
[ ] Chunk 3  — ECR + manual image push
[ ] Chunk 4  — VPC
[ ] Chunk 5  — EKS cluster + kubectl access
[ ] Chunk 6  — ALB controller + manual app deploy
[ ] Chunk 7  — GitHub Actions CI (checks.yml)
[ ] Chunk 8  — GitHub Actions CD (release.yml → ECR)
[ ] Chunk 9  — Deploy repo + Kustomize manifests
[ ] Chunk 10 — ArgoCD install + first GitOps sync
[ ] Chunk 11 — Close the loop (full automated pipeline)
[ ] Chunk 12 — Prod environment + manual promotion
```
