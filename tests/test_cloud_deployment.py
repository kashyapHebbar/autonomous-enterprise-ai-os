from __future__ import annotations

from pathlib import Path

from scripts.validate_cloud_deployment import validate_cloud_deployment


def test_aws_cloud_deployment_package_passes_validation():
    assert validate_cloud_deployment("aws") == []


def test_aws_cloud_docs_and_terraform_define_required_runtime_path():
    root = Path("deploy/cloud/aws")
    readme = (root / "README.md").read_text(encoding="utf-8")
    main_tf = (root / "terraform" / "main.tf").read_text(encoding="utf-8")
    outputs_tf = (root / "terraform" / "outputs.tf").read_text(encoding="utf-8")

    assert "EKS" in readme
    assert "RDS" in readme
    assert "ElastiCache" in readme
    assert "Secrets Manager" in readme
    assert "Smoke Test The Deployment" in readme
    assert "kubectl apply -k deploy/kubernetes/overlays/production" in readme
    assert "aws_eks_cluster" in main_tf
    assert "aws_db_instance" in main_tf
    assert "aws_elasticache_replication_group" in main_tf
    assert "aws_s3_bucket" in main_tf
    assert "aws_secretsmanager_secret_version" in main_tf
    assert "runtime_secret_name" in outputs_tf
