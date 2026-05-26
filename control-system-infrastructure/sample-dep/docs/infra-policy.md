# Infrastructure Policy

Authoritative constraints for all Terraform-managed infrastructure in this repository.
All pull requests that modify `.tf` files must comply with every requirement listed here.

## EKS Cluster

- `cluster_version` must be **1.28 or higher**; downgrading is prohibited without a platform review.
- `cluster_endpoint_public_access` must be `true` for CI/CD connectivity, BUT:
  - `cluster_endpoint_public_access_cidrs` **must not** include `"0.0.0.0/0"` — restrict to known office/CI CIDR ranges.
  - If no CIDR list is specified, Kubernetes defaults to `0.0.0.0/0` — this is prohibited.
- Control-plane logging must enable all types: `api`, `audit`, `authenticator`, `controllerManager`, `scheduler`.
- KMS encryption must be enabled for cluster secrets (`cluster_encryption_config`).
- `bootstrap_self_managed_addons` must be `false` to prevent forced cluster replacement.

## Fargate Profiles

- Only approved namespaces may have Fargate profiles: `kube-system`, `argocd`, `staging`.
- Adding a `prod` namespace profile requires a separate platform review — not auto-approved.
- New namespaces must not be added to Fargate profiles without a documented justification.

## IAM Access Entries

- `AmazonEKSClusterAdminPolicy` may only be granted to: `terraform-executor-role` and the designated ArgoCD agent role.
- No wildcard (`*`) resource in IAM policy statements is permitted.
- CI/CD roles must use namespace-scoped access, not cluster-admin, unless explicitly justified.

## ECR

- `image_tag_mutability` must be `IMMUTABLE`.
- `scan_on_push` must be `true`.
- The `latest` tag must never be used in production image references.

## State Backend

- All modules must use an S3 backend with `encrypt = true` and a DynamoDB lock table.
- Local state (`terraform.tfstate` in the working directory) is prohibited in production modules.
- State bucket and lock table names must follow the pattern: `sample-api-tfstate-{account_id}` / `sample-api-tfstate-lock`.

## Terraform Hygiene

- `required_version` must pin to `>= 1.0`; no unconstrained version is allowed.
- All provider versions must be pinned to a minor range (e.g., `~> 5.0`); no `latest` constraints.
- Resources must include a `tags` block with at minimum `Project = "sample-api"`.
- Outputs must have `description` fields.
