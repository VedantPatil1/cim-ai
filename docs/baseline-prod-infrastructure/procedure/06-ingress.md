# Step 6 — ALB Controller

The AWS Load Balancer Controller is installed via Helm into the `kube-system` namespace. It watches for `Ingress` resources and provisions ALBs in the public subnets automatically. The IAM role and policy for the controller were already created by the EKS Terraform module in the previous step.

---

## Add the Helm Repository

```bash
helm repo add eks https://aws.github.io/eks-charts
helm repo update
```

---

## Get the VPC ID

The ALB Controller needs the VPC ID passed explicitly. Fargate pods cannot access EC2 instance metadata, so the controller cannot discover the VPC ID on its own.

```bash
VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=sample-api-vpc" \
  --query 'Vpcs[0].VpcId' \
  --output text \
  --profile sample-api-terraform)

echo $VPC_ID
```

---

## Get the ALB Controller Role ARN

```bash
ALB_ROLE_ARN=$(aws iam get-role \
  --role-name sample-api-alb-controller-role \
  --query 'Role.Arn' \
  --output text \
  --profile sample-api-terraform)

echo $ALB_ROLE_ARN
```

---

## Install via Helm

```bash
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=sample-api-cluster \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set "serviceAccount.annotations.eks\.amazonaws\.com/role-arn=${ALB_ROLE_ARN}" \
  --set vpcId=${VPC_ID}
```

---

## Verify

```bash
# Controller pod running
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller
# NAME                                           READY   STATUS
# aws-load-balancer-controller-xxxxxxxxx-xxxxx   1/1     Running

# Service account has IRSA annotation
kubectl get serviceaccount aws-load-balancer-controller -n kube-system -o yaml \
  | grep eks.amazonaws.com/role-arn
```

Once the controller is running, any `Ingress` resource with `kubernetes.io/ingress.class: alb` will trigger ALB provisioning automatically.
