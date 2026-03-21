# Step 3 — Container Registry

**Permanent — do not destroy between sessions.**

Creates the ECR repository that stores all application images.

---

## Apply

```bash
export AWS_PROFILE=sample-api-terraform

cd sample-backend-api-app-dep/ecr
terraform init
terraform apply
```

Outputs:

```
repository_url = "065571033838.dkr.ecr.us-east-1.amazonaws.com/sample-api-ecr"
```

Save the repository URL — it is used in every Docker push and Kubernetes manifest.

---

## Manual Image Push (Verification)

After creating the repository, verify it works by building and pushing the application image.

### Authenticate Docker to ECR

```bash
aws ecr get-login-password --region us-east-1 --profile sample-api-terraform \
  | docker login --username AWS \
    --password-stdin ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
```

### Build the Image

```bash
cd sample-backend-api-app

# --platform flag is required on Apple Silicon (M1/M2/M3)
# EKS Fargate runs linux/amd64 only
docker build --platform linux/amd64 -f Dockerfile.python -t sample-api-ecr .
```

!!! warning "Apple Silicon"
    Always pass `--platform linux/amd64` when building on M1/M2/M3 Mac. Without it, Docker builds a native `arm64` image. EKS Fargate runs `linux/amd64` nodes — an `arm64` image will fail to start with `exec format error`. The `Dockerfile.python` also pins the base image with `FROM --platform=linux/amd64` for the same reason.

### Tag and Push

```bash
docker tag sample-api-ecr:latest \
  ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/sample-api-ecr:v2

docker push \
  ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/sample-api-ecr:v2
```

---

## Verify in AWS

```bash
# List images in the repository
aws ecr describe-images \
  --repository-name sample-api-ecr \
  --query 'imageDetails[*].{Tag:imageTags[0],Pushed:imagePushedAt}' \
  --output table \
  --profile sample-api-terraform

# View scan results for a specific tag
aws ecr describe-image-scan-findings \
  --repository-name sample-api-ecr \
  --image-id imageTag=v2 \
  --query 'imageScanFindings.findingSeverityCounts' \
  --profile sample-api-terraform
```
