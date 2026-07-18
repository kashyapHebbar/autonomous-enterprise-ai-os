variable "aws_region" {
  description = "AWS region for the first cloud deployment path."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name used for tagging and resource names."
  type        = string
  default     = "staging"
}

variable "project_name" {
  description = "Short project slug used in resource names."
  type        = string
  default     = "aeai-os"
}

variable "vpc_cidr" {
  description = "CIDR block for the EKS VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs for EKS nodes, RDS, and Redis."
  type        = list(string)
  default     = ["10.42.10.0/24", "10.42.11.0/24"]
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs for load balancers and NAT."
  type        = list(string)
  default     = ["10.42.0.0/24", "10.42.1.0/24"]
}

variable "kubernetes_version" {
  description = "EKS control plane Kubernetes version."
  type        = string
  default     = "1.30"
}

variable "node_instance_types" {
  description = "EC2 instance types for the managed EKS node group."
  type        = list(string)
  default     = ["t3.large"]
}

variable "node_desired_size" {
  description = "Desired managed node count."
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Minimum managed node count."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum managed node count."
  type        = number
  default     = 4
}

variable "database_name" {
  description = "RDS database name."
  type        = string
  default     = "aeai_os"
}

variable "database_username" {
  description = "RDS master username."
  type        = string
  default     = "aeai"
}

variable "database_instance_class" {
  description = "RDS Postgres instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "database_allocated_storage_gb" {
  description = "RDS allocated storage in GiB."
  type        = number
  default     = 50
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type."
  type        = string
  default     = "cache.t4g.small"
}

variable "admin_cidr_blocks" {
  description = "CIDR blocks allowed to reach the EKS public API endpoint."
  type        = list(string)
  default     = []
}

variable "github_container_registry" {
  description = "Container image repository used by Kubernetes overlays."
  type        = string
  default     = "ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os"
}
