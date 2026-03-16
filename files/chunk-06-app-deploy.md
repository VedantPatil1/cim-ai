# Chunk 6 — ALB Controller + Manual App Deploy
> Status: Complete

---

## What Was Done

Installed the AWS Load Balancer Controller into the EKS cluster, fixed
several IAM permission issues, updated the FastAPI Dockerfile, pushed a
corrected image to ECR, and deployed the app manually to the staging
namespace. Verified the app is reachable from the internet via ALB.

---

## Resources Created

| Resource | Detail |
|---|---|
| IAM Policy | `sample-api-alb-controller-policy` |
| IAM Role | `sample-api-alb-controller-role` |
| ALB Controller | Installed via Helm in `kube-system` |
| Kubernetes Namespace | `staging` |
| Kubernetes Deployment | `sample-api` in `staging` |
| Kubernetes Service | `sample-api` in `staging` (ClusterIP) |
| Kubernetes Ingress | `sample-api` in `staging` |
| AWS ALB | `k8s-staging-sampleap-3a9034c3f5` (internet-facing) |

---

## Terraform Changes

New file added: `sample-api-infra/eks/alb-controller.tf`

```
eks/
├── main.tf
└── alb-controller.tf    ← IAM role + policy for ALB controller
```

Required providers added to `eks/main.tf`:
```hcl
http = { source = "hashicorp/http", version = "~> 3.0" }
helm = { source = "hashicorp/helm",  version = "~> 2.0" }
```

---

## Dockerfile Fixes

Several issues found and fixed in the FastAPI app Dockerfile:

| Issue | Fix |
|---|---|
| No CMD instruction | Added `CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]` |
| Wrong Python version (`3.14.3-alpine` — doesn't exist) | Changed to `python:3.12-slim` |
| Typo `PUTHONUNBUFFERED` | Fixed to `PYTHONUNBUFFERED` |
| No platform pin | Added `FROM --platform=linux/amd64` |
| HEALTHCHECK in Dockerfile | Removed — handled by Kubernetes probes instead |

---

## Final Dockerfile

```dockerfile
FROM --platform=linux/amd64 python:3.12-slim
LABEL maintainer="vedantpatil.w.1@gmail.com"

ENV PYTHONUNBUFFERED=1

COPY ./requirements.txt /tmp/requirements.txt
COPY ./requirements.dev.txt /tmp/requirements.dev.txt
COPY ./src /src

WORKDIR /src

EXPOSE 8000

ARG DEV=false
RUN python -m venv /py && \
    /py/bin/pip install --upgrade pip && \
    /py/bin/pip install --no-cache-dir -r /tmp/requirements.txt && \
    if [ "$DEV" = "true" ]; \
        then /py/bin/pip install --no-cache-dir -r /tmp/requirements.dev.txt ; \
    fi && \
    rm -rf /tmp && \
    adduser \
        --disabled-password \
        --no-create-home \
        app-user

ENV PATH="/py/bin:$PATH"

USER app-user

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Image Tags in ECR

| Tag | Detail |
|---|---|
| `manual-test` | First test push from Chunk 3 (old Dockerfile) |
| `v1` | First push with fixed Dockerfile — missing SECRET_KEY |
| `v2` | Final working image — correct CMD + platform |

`v2` is the image deployed to staging.

---

## App Configuration

The app requires a `SECRET_KEY` environment variable. For this manual
deploy it is set directly in the manifest. This will move to AWS Secrets
Manager in a later chunk.

---

## Final Deployment Manifest

Location: `sample-api-infra/k8s-manual-test/deployment.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: staging
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sample-api
  namespace: staging
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sample-api
  template:
    metadata:
      labels:
        app: sample-api
    spec:
      containers:
        - name: sample-api
          image: 065571033838.dkr.ecr.us-east-1.amazonaws.com/sample-api-ecr:v2
          ports:
            - containerPort: 8000
          env:
            - name: SECRET_KEY
              value: "topsecretkey"
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 30
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
---
apiVersion: v1
kind: Service
metadata:
  name: sample-api
  namespace: staging
spec:
  selector:
    app: sample-api
  ports:
    - port: 80
      targetPort: 8000
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: sample-api
  namespace: staging
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/healthcheck-path: /health
spec:
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: sample-api
                port:
                  number: 80
```

---

## IAM Issues Fixed During This Chunk

The ALB controller role needed additional permissions not present in the
downloaded policy:

| Missing Action | Fix |
|---|---|
| `ec2:GetSecurityGroupsForVpc` | Added to ALB controller policy |
| `elasticloadbalancing:DescribeListenerAttributes` | Added to ALB controller policy |

The Terraform `data.http` resource cached the old policy — fix was applied
manually in the console and reflected in `alb-controller.tf`.

---

## ALB Controller — Fargate Specific Fix

Fargate pods cannot access EC2 instance metadata. VPC ID must be passed
explicitly to the Helm release:

```bash
helm upgrade aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=sample-api-cluster \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set "serviceAccount.annotations.eks\.amazonaws\.com/role-arn=arn:aws:iam::065571033838:role/sample-api-alb-controller-role" \
  --set vpcId=YOUR_VPC_ID
```

This is captured in `alb-controller.tf` via `data.terraform_remote_state.vpc`.

---

## Verification

```bash
# Pod running
kubectl get pods -n staging
# NAME                          READY   STATUS    RESTARTS   AGE
# sample-api-5dc54d68fc-wlffq   1/1     Running   0          30m

# ALB address assigned
kubectl get ingress -n staging
# ADDRESS: k8s-staging-sampleap-3a9034c3f5-439640156.us-east-1.elb.amazonaws.com

# App reachable
curl http://k8s-staging-sampleap-3a9034c3f5-439640156.us-east-1.elb.amazonaws.com/health
# {"status":"ok"}
```

---

## Cleanup — Important Order

ALB must be deleted before EKS/VPC destroy otherwise it is left dangling:

```bash
# 1. Delete k8s resources first (triggers ALB deletion)
kubectl delete -f sample-api-infra/k8s-manual-test/deployment.yaml

# 2. Wait for ALB to be deleted
kubectl get ingress -n staging   # wait until ADDRESS disappears

# 3. Destroy EKS
cd sample-api-infra/eks && terraform destroy

# 4. Destroy VPC
cd sample-api-infra/vpc && terraform destroy
```

---

## Cost

| Resource | Hourly | Daily |
|---|---|---|
| ALB | ~$0.022/hr | ~$0.53 |
| Fargate pod (0.25vCPU/256MB) | ~$0.01/hr | ~$0.24 |
| Combined with EKS+VPC | ~$0.17/hr | ~$4.00 |
