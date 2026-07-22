from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AWS_ROOT = ROOT / "deploy" / "cloud" / "aws"
TERRAFORM_ROOT = AWS_ROOT / "terraform"

REQUIRED_FILES = {
    AWS_ROOT / "README.md",
    TERRAFORM_ROOT / "versions.tf",
    TERRAFORM_ROOT / "variables.tf",
    TERRAFORM_ROOT / "main.tf",
    TERRAFORM_ROOT / "outputs.tf",
    TERRAFORM_ROOT / "terraform.tfvars.example",
}

REQUIRED_TERRAFORM_TOKENS = {
    "aws_eks_cluster",
    "aws_eks_node_group",
    "aws_db_instance",
    "aws_elasticache_replication_group",
    "aws_s3_bucket",
    "aws_s3_bucket_public_access_block",
    "aws_secretsmanager_secret",
    "aws_wafv2_web_acl",
    "aws_iam_access_key",
    "aws_vpc",
    "aws_subnet",
}

REQUIRED_DOC_TOKENS = {
    "EKS",
    "RDS",
    "ElastiCache",
    "S3",
    "Secrets Manager",
    "terraform plan",
    "terraform apply",
    "python scripts/release_operations.py deploy",
    "AWS WAFv2",
    "/health",
    "/app",
    "/app/admin",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate cloud deployment scaffolding.")
    parser.add_argument(
        "--target",
        choices=["aws"],
        default="aws",
        help="Cloud target to validate.",
    )
    args = parser.parse_args(argv)

    errors = validate_cloud_deployment(args.target)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Cloud deployment validation passed: {args.target}")
    return 0


def validate_cloud_deployment(target: str = "aws") -> list[str]:
    if target != "aws":
        return [f"Unsupported cloud target: {target}"]

    errors: list[str] = []
    for path in sorted(REQUIRED_FILES):
        if not path.exists():
            errors.append(f"Missing required cloud deployment file: {path.relative_to(ROOT)}")

    main_tf = _read(TERRAFORM_ROOT / "main.tf")
    for token in sorted(REQUIRED_TERRAFORM_TOKENS):
        if token not in main_tf:
            errors.append(f"Terraform main.tf missing resource token: {token}")

    versions_tf = _read(TERRAFORM_ROOT / "versions.tf")
    for provider in ['source  = "hashicorp/aws"', 'source  = "hashicorp/random"']:
        if provider not in versions_tf:
            errors.append(f"Terraform versions.tf missing provider: {provider}")

    outputs_tf = _read(TERRAFORM_ROOT / "outputs.tf")
    for output_name in [
        "eks_update_kubeconfig_command",
        "artifact_bucket_name",
        "runtime_secret_name",
        "waf_web_acl_arn",
    ]:
        if output_name not in outputs_tf:
            errors.append(f"Terraform outputs.tf missing output: {output_name}")

    docs = _read(AWS_ROOT / "README.md")
    for token in sorted(REQUIRED_DOC_TOKENS):
        if token not in docs:
            errors.append(f"AWS deployment README missing required documentation: {token}")

    return errors


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
