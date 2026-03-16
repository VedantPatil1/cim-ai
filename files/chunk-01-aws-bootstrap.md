# Chunk 1 — AWS Account Bootstrap
> Status: Complete

---

## What Was Done

### Root Account
- MFA enabled on root
- No root access keys created
- Root not used after initial setup

### Personal Admin User
- Name: `vedant-admin`
- Console access + MFA enabled
- AdministratorAccess policy attached
- No access keys — console only

---

## IAM Resources Created

### CLI User — `sample-api-cli-user`
- No console access
- No direct AWS permissions
- Inline policy: `sample-api-assume-executor-policy`

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AssumeOnlyTerraformExecutorRole",
    "Effect": "Allow",
    "Action": "sts:AssumeRole",
    "Resource": "arn:aws:iam::ACCOUNT_ID:role/sample-api-terraform-executor-role"
  }]
}
```

### Terraform Role — `sample-api-terraform-executor-role`
- Assumed by `sample-api-cli-user` only
- No console access
- Trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "AWS": "arn:aws:iam::ACCOUNT_ID:user/sample-api-cli-user"
    },
    "Action": "sts:AssumeRole"
  }]
}
```

### Terraform Policy — `sample-api-terraform-executor-policy`
Attached to the executor role. Custom policy — no AWS managed policies used.

| Statement | Resource Scope |
|---|---|
| EC2 / VPC | `*` |
| EKS | `*` |
| ECR | `*` |
| ELB | `*` |
| S3 | `sample-api-tfstate-*` only |
| DynamoDB | `sample-api-*` only |
| Secrets Manager | `sample-api-*` only |
| IAM Role actions | `sample-api-*` roles only |
| IAM Policy actions | `sample-api-*` policies only |
| `iam:PassRole` | `sample-api-*` roles + `PassedToService` condition (eks, ec2, elb) |
| `iam:CreateServiceLinkedRole` | eks, elasticloadbalancing, fargate paths only |
| OIDC | GitHub Actions provider ARN only |

---

## Local Profile Config

```ini
# ~/.aws/config
[profile sample-api-cli]
region = us-east-1

[profile sample-api-terraform]
role_arn       = arn:aws:iam::ACCOUNT_ID:role/sample-api-terraform-executor-role
source_profile = sample-api-cli
region         = us-east-1
```

---

## Verification

```bash
# Confirms user credentials work
aws sts get-caller-identity --profile sample-api-cli

# Confirms role assumption works
aws sts get-caller-identity --profile sample-api-terraform
# Must return: assumed-role/sample-api-terraform-executor-role/...
```

---

## Naming Convention Established

Pattern: `sample-api-{component}-{type}`

All future IAM roles and policies must follow `sample-api-*` prefix
or they will be denied by the executor policy scoping.
