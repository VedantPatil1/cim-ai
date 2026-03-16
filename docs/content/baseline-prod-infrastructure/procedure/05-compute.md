# Step 5 — Compute

**Session resource — destroy at end of each session. Always destroy before VPC.**

Creates the EKS cluster, Fargate profiles, cluster add-ons, OIDC provider, and CloudWatch log group. Depends on VPC remote state.

---

## Apply

```bash
export AWS_PROFILE=sample-api-terraform

cd sample-backend-api-app-dep/eks
terraform init
terraform apply
```

This takes 15–20 minutes on first apply. The Fargate profiles and CoreDNS addon are the slowest components.

---

## What Gets Created

| Resource | Detail |
|---|---|
| EKS Cluster | `sample-api-cluster` — Kubernetes 1.30 |
| Fargate Profile | `sample-api-kube-system` → `kube-system` namespace |
| Fargate Profile | `sample-api-argocd` → `argocd` namespace |
| Fargate Profile | `sample-api-staging` → `staging` namespace |
| Fargate Profile | `sample-api-prod` → `prod` namespace |
| IAM Roles | One per Fargate profile (auto-generated) |
| OIDC Provider | `oidc.eks.us-east-1.amazonaws.com/id/...` |
| CloudWatch Log Group | `/aws/eks/sample-api-cluster/cluster` |
| Add-on: CoreDNS | Runs on Fargate (`computeType: Fargate`) |
| Add-on: kube-proxy | Required for network rules |
| Add-on: vpc-cni | Assigns VPC IPs directly to pods |
| IAM Policy | `sample-api-alb-controller-policy` |
| IAM Role | `sample-api-alb-controller-role` (IRSA) |

---

## Configure kubectl

After apply, update the local kubeconfig. This must be run every session after recreating the cluster (the cluster endpoint changes each time):

```bash
aws eks update-kubeconfig \
  --name sample-api-cluster \
  --region us-east-1 \
  --profile sample-api-terraform
```

---

## Verify Cluster

```bash
# Nodes — each Fargate pod appears as a node
kubectl get nodes
# NAME                                 STATUS   ROLES    AGE
# fargate-ip-10-0-1-15.ec2.internal    Ready    <none>   7m27s
# fargate-ip-10-0-1-216.ec2.internal   Ready    <none>   7m27s

# CoreDNS running on Fargate
kubectl get pods -n kube-system
# NAME                       READY   STATUS    RESTARTS
# coredns-7566cd8fc7-mc7g9   1/1     Running   0
# coredns-7566cd8fc7-tvnk4   1/1     Running   0

# All four Fargate profiles present
aws eks list-fargate-profiles \
  --cluster-name sample-api-cluster \
  --profile sample-api-terraform
```

---

## IAM Issues Encountered During Initial Setup

These errors occurred during the first apply and required policy updates. They are documented here so they do not need to be re-discovered:

| Error | Root Cause | Fix Applied |
|---|---|---|
| `kms:TagResource` denied | EKS module creates KMS key, requires tag permissions | Added `KMS` statement to executor policy |
| `logs:CreateLogGroup` denied | Cluster logging requires CloudWatch log group | Added `CloudWatchLogs` statement |
| OIDC provider ARN mismatch | Policy scoped to wrong OIDC path | Fixed to `oidc.eks.us-east-1.amazonaws.com/*` |
| `iam:CreateServiceLinkedRole` denied | Wrong service path in policy | Fixed path to `eks-fargate.amazonaws.com` |
| `kubectl` credentials error | EKS v2 requires explicit access entry | Added `access_entries` block in `main.tf` |
| Policy exceeded 6144 char limit | Verbose action lists | Consolidated using service wildcards |

All fixes are already incorporated into the executor policy in [Step 1](01-account.md) and the Terraform code in the repository. These errors will not occur on a fresh setup following this guide.

---

## Destroy

```bash
cd sample-backend-api-app-dep/eks
terraform destroy
```

Always destroy EKS before VPC. After EKS destroy, proceed immediately to VPC destroy.

---

## Cost

| Resource | Hourly | Daily | Monthly |
|---|---|---|---|
| EKS control plane | $0.10 | $2.40 | ~$73 |
| CoreDNS Fargate pods (x2) | ~$0.001 | ~$0.02 | ~$0.60 |
| CloudWatch Logs | — | minimal | ~$0.50 |
