# Chunk 4 — VPC
> Status: Complete

---

## What Was Done

Created the VPC network layer using Terraform. Verified full apply and destroy
cycle works cleanly. Remote state tracked all 19 resources correctly.

---

## Resources Created (19 total)

| Resource | Detail |
|---|---|
| VPC | `sample-api-vpc` — `10.0.0.0/16` |
| Private subnets | `10.0.1.0/24` (us-east-1a), `10.0.2.0/24` (us-east-1b) |
| Public subnets | `10.0.101.0/24` (us-east-1a), `10.0.102.0/24` (us-east-1b) |
| Internet Gateway | Inbound traffic to ALB |
| NAT Gateway | Single — us-east-1a, outbound traffic from pods |
| Elastic IP | Attached to NAT Gateway |
| Route tables | Public + private with appropriate routes |

---

## Design Decisions

| Decision | Detail |
|---|---|
| 2 AZs | Pod placement resilience — subnets cost nothing |
| Single NAT Gateway | Cost saving — ~$32/mo vs ~$64/mo for NAT per AZ |
| Private subnets | EKS Fargate pods run here |
| Public subnets | ALB lives here |

---

## Outputs

```
vpc_id             = "vpc-081c0bb37c1322e40"
private_subnet_ids = ["subnet-044ffee5fd9054200", "subnet-01f465b780a1d1873"]
public_subnet_ids  = ["subnet-0e246eb20070f71d3", "subnet-0876ac3961fca7d60"]
```

Note: subnet IDs change on each recreate. EKS module reads them from
remote state directly so hardcoding is never needed.

---

## Remote State

```
bucket: sample-api-tfstate-{account_id}
key:    vpc/terraform.tfstate
```

---

## Repo Structure

```
sample-api-infra/
├── bootstrap/
├── ecr/
└── vpc/
    └── main.tf
```

---

## Required Subnet Tags

These tags are set on subnets so EKS and the ALB controller can
discover them automatically:

```hcl
private_subnet_tags = {
  "kubernetes.io/role/internal-elb" = "1"
}
public_subnet_tags = {
  "kubernetes.io/role/elb" = "1"
}
```

---

## Cost

| Resource | Hourly | Daily | Monthly |
|---|---|---|---|
| NAT Gateway | $0.045/hr | ~$1.08 | ~$32 |
| Subnets, VPC, IGW, Route tables | free | free | free |
| NAT data processing | $0.045/GB | minimal | minimal |
| **Total** | | **~$1.08/day** | **~$32/mo** |

---

## Development Pattern

Destroy VPC at end of each session to avoid idle NAT Gateway cost.
Recreate takes ~2-3 minutes. Always recreate VPC before EKS.

```bash
# End of day
cd sample-api-infra/vpc && terraform destroy

# Next session — recreate VPC first, then EKS
cd sample-api-infra/vpc && terraform apply
cd sample-api-infra/eks  && terraform apply
```
