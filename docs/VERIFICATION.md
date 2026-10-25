# Verification and limits

Local checks cover the shared containerization/branch gate with AWS-specific configuration, separate infrastructure/application assets, ECR digest artifact validation, Azure DevOps completion-trigger and Ops approval structure, and Helm rendering/security constraints. Real Docker startup success and health failure paths are tested. Failed containerization creates no application branch. Terraform 1.12.2 initialized the AWS provider and validated the infrastructure reference without AWS credentials or a deployment.

The local first full run had one Helm process killed by the host after 13 tests passed; rerunning the chart/security and pipeline checks passed. The local full suite reproduced the host-killed Helm process while all other 13 tests passed; the isolated Helm and pipeline tests passed. GitHub Actions on Linux is the final full-suite acceptance signal; consult Actions for the exact source revision. GitHub Actions runs real Docker tests, Helm checks and Terraform validation.

Not live-tested: AWS OIDC trust/service connections, ECR push/pull and Trivy execution, private API/DNS/routing, Terraform plan/apply against a customer account, KMS policies, EKS access-entry permissions, add-on/network-policy enforcement, IRSA, Azure DevOps automatic triggers/group membership, application business/data migration, traffic cutover or production rollback. Windows/GovCloud/China partitions are outside this initial validation scope.

This adapter requires a committed Linux Dockerfile, HTTP readiness endpoint and resolved owner assessments. It does not automatically rewrite arbitrary EC2 software or move databases/disks. The infrastructure is a production-oriented reference requiring customer-specific validation and hardening, including dedicated CNI identity, add-on management, egress, backups, identity, load/soak and rollback tests. It is not an unconditional production-readiness certification.

No cloud resources, source EC2 instances, DNS records or production traffic were changed while developing this kit.
