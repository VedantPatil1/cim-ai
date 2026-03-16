# Chunk 2 — Terraform Remote State
> Status: Complete

---

## What Was Done

Created the S3 bucket and DynamoDB table that all future Terraform modules
use to store and lock state. Run once using local state — never run again.

---

## Resources Created

| Resource | Name |
|---|---|
| S3 Bucket | `sample-api-tfstate-{account_id}` |
| DynamoDB Table | `sample-api-tfstate-lock` |

### S3 Bucket Configuration
- Versioning enabled — full history of every state change
- AES256 server-side encryption
- Public access fully blocked
- `prevent_destroy` lifecycle rule — cannot be accidentally deleted by Terraform

### DynamoDB Table Configuration
- Billing: `PAY_PER_REQUEST` — no idle cost
- Hash key: `LockID`
- Prevents two simultaneous `terraform apply` runs conflicting

---

## Repo Structure

```
sample-api-infra/        ← private GitHub repo
├── .gitignore           ← excludes .terraform/, *.tfstate, *.tfvars
└── bootstrap/
    └── main.tf
```

### .gitignore covers
```
.terraform/
*.tfstate
*.tfstate.backup
*.tfvars
.terraform.lock.hcl
crash.log
```

---

## Why Bootstrap Uses Local State

The bootstrap module creates the S3 bucket and DynamoDB table that remote
state depends on. Remote state cannot exist before those resources are created
— so bootstrap runs with local state exactly once.

The local `bootstrap/terraform.tfstate` file tracks only two resources and
never changes after initial apply. Do not delete it from your local machine.
If lost, both resources can be reimported:

```bash
terraform import aws_s3_bucket.tfstate sample-api-tfstate-ACCOUNT_ID
terraform import aws_dynamodb_table.tflock sample-api-tfstate-lock
```

---

## Backend Block for All Future Modules

Every module from Chunk 3 onwards includes this block — only the `key` changes:

```hcl
terraform {
  backend "s3" {
    bucket         = "sample-api-tfstate-YOUR_ACCOUNT_ID"
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

## Cost

| Resource | Monthly Cost |
|---|---|
| S3 storage (state files) | ~$0.00 |
| S3 requests | ~$0.00 |
| DynamoDB operations | ~$0.07 |
| **Total** | **< $0.10/mo** |

These resources should stay up permanently — no reason to ever destroy them.

---

## Verification

```bash
aws s3 ls | grep sample-api-tfstate
aws dynamodb list-tables --query "TableNames" --output table
```
