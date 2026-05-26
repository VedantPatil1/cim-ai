terraform {
  required_version = ">= 1.0"

  required_providers {
    http = {
      source  = "hashicorp/http"
      version = "~> 3.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    bucket         = "sample-api-tfstate-065571033838"
    key            = "eks/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "sample-api-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-1"
  assume_role {
    role_arn = "arn:aws:iam::065571033838:role/sample-api-terraform-executor-role"
  }
}

# Read VPC outputs from remote state — no hardcoded subnet IDs
data "terraform_remote_state" "vpc" {
  backend = "s3"
  config = {
    bucket = "sample-api-tfstate-065571033838"
    key    = "vpc/terraform.tfstate"
    region = "us-east-1"
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "sample-api-cluster"
  cluster_version = "1.30"

  vpc_id     = data.terraform_remote_state.vpc.outputs.vpc_id
  subnet_ids = data.terraform_remote_state.vpc.outputs.private_subnet_ids

  cluster_endpoint_public_access = true

  fargate_profiles = {
    kube_system = {
      name      = "sample-api-kube-system"
      selectors = [{ namespace = "kube-system" }]
      tags      = { Profile = "sample-api-kube-system" }
    }
    argocd = {
      name      = "sample-api-argocd"
      selectors = [{ namespace = "argocd" }]
      tags      = { Profile = "sample-api-argocd" }
    }
    staging = {
      name      = "sample-api-staging"
      selectors = [{ namespace = "staging" }]
      tags      = { Profile = "sample-api-staging" }
    }
  }

  cluster_addons = {
    coredns = {
      most_recent          = true
      configuration_values = jsonencode({ computeType = "Fargate" })
    }
    kube-proxy = { most_recent = true }
    vpc-cni    = { most_recent = true }
  }

  access_entries = {
    terraform_executor = {
      principal_arn = "arn:aws:iam::065571033838:role/sample-api-terraform-executor-role"
      policy_associations = {
        admin = {
          policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = { type = "cluster" }
        }
      }
    }
    # ArgoCD cluster agent — created by `argocd cluster add` after provisioning.
    # Add its IAM principal here to grant cluster-admin access for GitOps sync.
    # argocd_agent = {
    #   principal_arn = "arn:aws:iam::065571033838:role/argocd-cluster-agent"
    #   policy_associations = {
    #     admin = {
    #       policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
    #       access_scope = { type = "cluster" }
    #     }
    #   }
    # }
  }

  tags = {
    Project = "sample-api"
  }
}

output "cluster_name" {
  value       = module.eks.cluster_name
  description = "EKS cluster name — use with: aws eks update-kubeconfig --name <value>"
}

output "cluster_endpoint" {
  value       = module.eks.cluster_endpoint
  description = "EKS API endpoint — used in argocd/app-aws.yaml destination.server"
}

output "cluster_certificate_authority_data" {
  value       = module.eks.cluster_certificate_authority_data
  description = "Base64 CA cert for kubeconfig"
}

output "oidc_provider_arn" {
  value       = module.eks.oidc_provider_arn
  description = "OIDC provider ARN — used in IRSA trust policies"
}
