# Step 1 — Account Bootstrap

**Run once. Never repeat.**

This step establishes the AWS account security model: root account hardening, a console admin user, a programmatic CLI user, and the Terraform executor role with its scoped policy.

---

## Root Account

1. Log in to the AWS console as root
2. Enable MFA on the root account (IAM → Security credentials → MFA)
3. Do not create access keys for root
4. Do not use root again after this step

---

## Admin User — vedant-admin

Create a personal admin user for ongoing console access.

In the AWS console (IAM → Users → Create user):

| Setting | Value |
|---|---|
| Username | `vedant-admin` |
| Console access | Yes |
| Password | Set strong password |
| Permissions | Attach `AdministratorAccess` directly |

After creation, enable MFA for `vedant-admin`.

This user is for console access only. Do not generate access keys.

---

## CLI User — sample-api-cli-user

Create the programmatic user that Terraform runs as.

In the AWS console (IAM → Users → Create user):

| Setting | Value |
|---|---|
| Username | `sample-api-cli-user` |
| Console access | No |
| Permissions | None — do not attach any policy yet |

After creation:

1. Go to the user → Security credentials → Create access key
2. Select "Command Line Interface (CLI)"
3. Save the access key ID and secret — these are the only long-lived credentials in the system

Add the following inline policy to `sample-api-cli-user` (IAM → Users → sample-api-cli-user → Add permissions → Create inline policy):

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

Name the policy `sample-api-assume-executor-policy`.

---

## Executor Role — sample-api-terraform-executor-role

Create the role that holds all Terraform permissions.

In the AWS console (IAM → Roles → Create role):

| Setting | Value |
|---|---|
| Trusted entity type | AWS account |
| Account | This account |
| Role name | `sample-api-terraform-executor-role` |

After creation, edit the trust policy to restrict assumption to only `sample-api-cli-user`:

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

---

## Executor Policy — sample-api-terraform-executor-policy

Create the custom policy that will be attached to the executor role.

In the AWS console (IAM → Policies → Create policy → JSON):

Paste the following policy, replacing `ACCOUNT_ID` with your 12-digit account ID:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2andVPC",
      "Effect": "Allow",
      "Action": [
        "ec2:Allocate*", "ec2:Associate*", "ec2:Attach*", "ec2:Authorize*",
        "ec2:Create*", "ec2:Delete*", "ec2:Describe*", "ec2:Detach*",
        "ec2:Disassociate*", "ec2:Modify*", "ec2:Release*", "ec2:Revoke*"
      ],
      "Resource": "*"
    },
    { "Sid": "EKS", "Effect": "Allow", "Action": "eks:*", "Resource": "*" },
    { "Sid": "ECR", "Effect": "Allow", "Action": "ecr:*", "Resource": "*" },
    { "Sid": "ELB", "Effect": "Allow", "Action": "elasticloadbalancing:*", "Resource": "*" },
    { "Sid": "KMS", "Effect": "Allow", "Action": "kms:*", "Resource": "*" },
    { "Sid": "CloudWatchLogs", "Effect": "Allow", "Action": "logs:*", "Resource": "*" },
    {
      "Sid": "S3TerraformStateBucket",
      "Effect": "Allow",
      "Action": ["s3:*Bucket*", "s3:ListBucket", "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration"],
      "Resource": "arn:aws:s3:::sample-api-tfstate-*"
    },
    {
      "Sid": "S3TerraformStateObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::sample-api-tfstate-*/*"
    },
    {
      "Sid": "DynamoDBTerraformLock",
      "Effect": "Allow",
      "Action": [
        "dynamodb:CreateTable", "dynamodb:DeleteTable", "dynamodb:DescribeTable",
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
        "dynamodb:TagResource", "dynamodb:UntagResource", "dynamodb:ListTagsOfResource"
      ],
      "Resource": "arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/sample-api-*"
    },
    {
      "Sid": "SecretsManager",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:CreateSecret", "secretsmanager:DeleteSecret",
        "secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue",
        "secretsmanager:PutSecretValue", "secretsmanager:TagResource", "secretsmanager:UntagResource"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:sample-api-*"
    },
    {
      "Sid": "IAMRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole", "iam:DeleteRole", "iam:GetRole",
        "iam:AttachRolePolicy", "iam:DetachRolePolicy",
        "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
        "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
        "iam:TagRole", "iam:UntagRole", "iam:UpdateAssumeRolePolicy",
        "iam:ListInstanceProfilesForRole"
      ],
      "Resource": "arn:aws:iam::ACCOUNT_ID:role/sample-api-*"
    },
    {
      "Sid": "IAMPolicies",
      "Effect": "Allow",
      "Action": [
        "iam:CreatePolicy", "iam:DeletePolicy", "iam:GetPolicy",
        "iam:GetPolicyVersion", "iam:ListPolicyVersions",
        "iam:CreatePolicyVersion", "iam:DeletePolicyVersion",
        "iam:TagPolicy", "iam:UntagPolicy"
      ],
      "Resource": "arn:aws:iam::ACCOUNT_ID:policy/sample-api-*"
    },
    {
      "Sid": "IAMPassRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::ACCOUNT_ID:role/sample-api-*",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": ["eks.amazonaws.com", "ec2.amazonaws.com", "elasticloadbalancing.amazonaws.com"]
        }
      }
    },
    {
      "Sid": "IAMServiceLinkedRoles",
      "Effect": "Allow",
      "Action": "iam:CreateServiceLinkedRole",
      "Resource": [
        "arn:aws:iam::ACCOUNT_ID:role/aws-service-role/eks.amazonaws.com/*",
        "arn:aws:iam::ACCOUNT_ID:role/aws-service-role/eks-fargate.amazonaws.com/*",
        "arn:aws:iam::ACCOUNT_ID:role/aws-service-role/elasticloadbalancing.amazonaws.com/*"
      ]
    },
    {
      "Sid": "OIDC",
      "Effect": "Allow",
      "Action": [
        "iam:CreateOpenIDConnectProvider", "iam:DeleteOpenIDConnectProvider",
        "iam:GetOpenIDConnectProvider", "iam:TagOpenIDConnectProvider", "iam:UntagOpenIDConnectProvider"
      ],
      "Resource": [
        "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com",
        "arn:aws:iam::ACCOUNT_ID:oidc-provider/oidc.eks.us-east-1.amazonaws.com/*"
      ]
    }
  ]
}
```

Name the policy `sample-api-terraform-executor-policy`.

Attach it to `sample-api-terraform-executor-role` (IAM → Roles → sample-api-terraform-executor-role → Add permissions → Attach policies).

---

## Configure Local AWS Profiles

```ini
# ~/.aws/config
[profile sample-api-cli]
region = us-east-1

[profile sample-api-terraform]
role_arn       = arn:aws:iam::ACCOUNT_ID:role/sample-api-terraform-executor-role
source_profile = sample-api-cli
region         = us-east-1
```

```ini
# ~/.aws/credentials
[sample-api-cli]
aws_access_key_id     = <access-key-id>
aws_secret_access_key = <secret-access-key>
```

## Verification

```bash
# CLI user credentials work
aws sts get-caller-identity --profile sample-api-cli
# Returns: sample-api-cli-user ARN

# Role assumption works
aws sts get-caller-identity --profile sample-api-terraform
# Returns: assumed-role/sample-api-terraform-executor-role/...
```
