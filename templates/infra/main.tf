terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  backend "s3" {}
}
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
  default_tags { tags = { ManagedBy = "EKS-LaunchBridge" } }
}
variable "region" { type = string }
variable "account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Use your 12-digit AWS account ID."
  }
}
variable "cluster_name" { type = string }
variable "kubernetes_version" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" {
  type = list(string)
  validation {
    condition     = length(var.private_subnet_ids) >= 2
    error_message = "Use private subnets in at least two availability zones."
  }
}
variable "agent_security_group_id" { type = string }
variable "ecr_repository" { type = string }
variable "secrets_kms_key_arn" { type = string }
variable "admin_role_arns" {
  type = set(string)
  validation {
    condition     = length(var.admin_role_arns) > 0
    error_message = "An explicit platform administrator role is required."
  }
}
variable "deployment_role_arn" { type = string }
variable "vpc_cni_version" { type = string }
variable "app_name" { type = string }
variable "instance_types" {
  type    = list(string)
  default = ["m6i.large"]
}

data "aws_subnet" "selected" {
  for_each = toset(var.private_subnet_ids)
  id       = each.value
}
resource "aws_iam_role" "cluster" {
  name               = "${var.cluster_name}-control"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "eks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}
resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.cluster_name}/cluster"
  retention_in_days = 30
}
resource "aws_eks_cluster" "this" {
  name                      = var.cluster_name
  role_arn                  = aws_iam_role.cluster.arn
  version                   = var.kubernetes_version
  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = false
  }
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }
  encryption_config {
    resources = ["secrets"]
    provider { key_arn = var.secrets_kms_key_arn }
  }
  lifecycle {
    precondition {
      condition     = alltrue([for s in data.aws_subnet.selected : s.vpc_id == var.vpc_id && !s.map_public_ip_on_launch]) && length(toset([for s in data.aws_subnet.selected : s.availability_zone])) >= 2
      error_message = "Subnets must belong to the target VPC, disable automatic public IPs and span at least two AZs. Review route tables separately."
    }
  }
  depends_on = [aws_iam_role_policy_attachment.cluster, aws_cloudwatch_log_group.cluster]
}
resource "aws_vpc_security_group_ingress_rule" "agent" {
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = var.agent_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_iam_role" "node" {
  name               = "${var.cluster_name}-nodes"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy_attachment" "node" {
  for_each   = toset(["AmazonEKSWorkerNodePolicy", "AmazonEC2ContainerRegistryPullOnly", "AmazonEKS_CNI_Policy"])
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/${each.value}"
}
resource "aws_launch_template" "node" {
  name_prefix = "${var.cluster_name}-"
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
}
resource "aws_eks_node_group" "this" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "system"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids
  instance_types  = var.instance_types
  ami_type        = "AL2023_x86_64_STANDARD"
  scaling_config {
    desired_size = 3
    min_size     = 3
    max_size     = 6
  }
  update_config { max_unavailable = 1 }
  launch_template {
    id      = aws_launch_template.node.id
    version = aws_launch_template.node.latest_version
  }
  depends_on = [aws_iam_role_policy_attachment.node]
}
resource "aws_eks_addon" "cni" {
  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = "vpc-cni"
  addon_version               = var.vpc_cni_version
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
  configuration_values        = jsonencode({ enableNetworkPolicy = "true" })
  depends_on                  = [aws_eks_node_group.this]
}
resource "aws_eks_access_entry" "admins" {
  for_each      = var.admin_role_arns
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  type          = "STANDARD"
}
resource "aws_eks_access_policy_association" "admins" {
  for_each      = var.admin_role_arns
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_eks_access_entry.admins[each.value].principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
}
resource "aws_eks_access_entry" "deploy" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = var.deployment_role_arn
  type          = "STANDARD"
}
resource "aws_eks_access_policy_association" "deploy" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_eks_access_entry.deploy.principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"
  access_scope {
    type       = "namespace"
    namespaces = ["${var.app_name}-staging", "${var.app_name}-production"]
  }
}
resource "aws_ecr_repository" "this" {
  name                 = var.ecr_repository
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.secrets_kms_key_arn
  }
  image_scanning_configuration { scan_on_push = true }
}
output "cluster_name" { value = aws_eks_cluster.this.name }
output "repository_url" { value = aws_ecr_repository.this.repository_url }
output "oidc_issuer" { value = aws_eks_cluster.this.identity[0].oidc[0].issuer }
