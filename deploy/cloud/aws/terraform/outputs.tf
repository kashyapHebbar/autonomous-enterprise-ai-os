output "aws_region" {
  description = "AWS region used for deployment."
  value       = var.aws_region
}

output "eks_cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.main.name
}

output "eks_update_kubeconfig_command" {
  description = "Command to configure kubectl for the provisioned cluster."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${aws_eks_cluster.main.name}"
}

output "artifact_bucket_name" {
  description = "S3 artifact bucket name."
  value       = aws_s3_bucket.artifacts.bucket
}

output "database_endpoint" {
  description = "RDS Postgres endpoint."
  value       = aws_db_instance.postgres.address
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint."
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "runtime_secret_name" {
  description = "AWS Secrets Manager secret containing runtime values."
  value       = aws_secretsmanager_secret.aeai_runtime.name
}

output "container_image_repository" {
  description = "Container image repository expected by Kubernetes overlays."
  value       = var.github_container_registry
}

output "waf_web_acl_arn" {
  description = "WAFv2 web ACL ARN to attach to the production ALB ingress."
  value       = aws_wafv2_web_acl.public_api.arn
}
