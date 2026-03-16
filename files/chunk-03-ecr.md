# Chunk 3 — ECR Repository
> Status: Complete

---

## What Was Done

Created the ECR repository using Terraform with remote state. Verified by
manually building and pushing the FastAPI app image from local machine.

---

## Resources Created

| Resource | Name |
|---|---|
| ECR Repository | `sample-api-ecr` |
| Lifecycle Policy | Keep last 5 images |

### Repository Configuration
- Image tag mutability: `MUTABLE` — allows overwriting `latest` tag
- Scan on push: enabled — free vulnerability scan on every push
- Lifecycle policy: auto-expires images beyond the last 5 — controls storage cost

---

## Repo Structure

```
sample-api-infra/
├── bootstrap/
│   └── main.tf
└── ecr/
    └── main.tf
```

---

## Remote State

```
bucket: sample-api-tfstate-{account_id}
key:    ecr/terraform.tfstate
```

---

## Repository URL

```
YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/sample-api-ecr
```

Save this — used in every Docker push command and Kubernetes manifest going forward.

---

## Manual Image Push — Verified

```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS \
    --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# Build — platform flag required on M1 Mac
docker build --platform linux/amd64 -t sample-api-ecr .

# Tag
docker tag sample-api-ecr:latest \
  YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/sample-api-ecr:manual-test

# Push
docker push \
  YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/sample-api-ecr:manual-test
```

---

## M1 Mac — Platform Note

EKS Fargate runs `linux/amd64`. Always build with `--platform linux/amd64`
on M1 otherwise the pushed image will be `arm64` and pods will fail to start.

```bash
docker build --platform linux/amd64 -t sample-api-ecr .
```

### Dockerfile — Pending Update
The `FROM` line in the Dockerfile has not yet been updated to pin the platform.
To do before Chunk 6 (manual app deploy to EKS):

```dockerfile
# Add --platform flag to FROM line
FROM --platform=linux/amd64 python:3.12-slim
```

---

## Verify

```bash
# CLI
aws ecr list-images --repository-name sample-api-ecr

# Detail view
aws ecr describe-images --repository-name sample-api-ecr \
  --query 'imageDetails[*].{Tag:imageTags[0],Size:imageSizeInBytes,Pushed:imagePushedAt}' \
  --output table

# Scan results
aws ecr describe-image-scan-findings \
  --repository-name sample-api-ecr \
  --image-id imageTag=manual-test \
  --query 'imageScanFindings.findingSeverityCounts'
```

Console: `ECR → Repositories → sample-api-ecr → Images` (ensure region is `us-east-1`)

---

## Cost

| Resource | Monthly Cost |
|---|---|
| Storage (5 images ~50MB each) | ~$0.01 |
| Image scanning | Free (basic scanning) |
| **Total** | **~$0.01/mo** |
