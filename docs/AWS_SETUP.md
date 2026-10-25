# AWS and Azure DevOps setup

EKS LaunchBridge targets commercial AWS regions with EC2-backed Linux managed node groups. Application and infrastructure repositories remain separate; Azure DevOps orchestrates both. Install AWS Toolkit for Azure DevOps (with its OIDC-capable AWS service connections), not the Azure Resource Manager task for AWS deployment.

## Identity and access

Use three distinct federated AWS service connections: ECR build/push, namespace-scoped EKS deployment, and platform provisioning. Configure OIDC federation following [AWS's Azure DevOps federation guide](https://aws.amazon.com/blogs/modernizing-with-aws/how-to-federate-into-aws-from-azure-devops-using-openid-connect/). Restrict issuer, audience, subject, allowed project/service connection and IAM permissions. Never insert static access keys or personal tokens in repository files.

- Build role: ECR authentication plus push/read for the intended repository; no EKS administration or EC2 write.
- Deploy role: EKS DescribeCluster plus an EKS access entry with namespace-scoped edit permissions for only the two target namespaces. The namespace-policy preflight needs namespace metadata read, granted narrowly by a platform administrator. Do not use cluster-admin as a workaround.
- Platform role: narrowly scoped EKS, IAM/PassRole, EC2 network/security-group, ECR, KMS and log provisioning permissions, plus access to the private Terraform backend. It must be explicitly included in the configured administrator roles to bootstrap namespaces.

Every generated AWS step verifies that the authenticated account matches the configured account. AWS Toolkit supplies short-lived credentials to AWS CLI and kubectl's EKS token helper. The kit does not create the OIDC provider, identity trust or Azure DevOps service connections automatically.

## Infrastructure contract

The optional Terraform reference creates a private-only EKS API, managed Linux nodes with IMDSv2, explicit EKS access entries, control-plane audit logs, encrypted Kubernetes Secrets, and encrypted ECR with immutable tags. It uses an existing VPC, private subnets across at least two AZs, private agent security group and reviewed KMS key. Supply a supported regional Kubernetes version and compatible VPC CNI add-on version. VPC CNI network-policy support is enabled; verify effective enforcement in the target cluster.

Route tables, private DNS, NAT or VPC endpoints for ECR API/DKR, S3 image layers, STS, EKS, CloudWatch and other application dependencies are existing landing-zone responsibilities. A subnet with public IP assignment disabled does not prove its route table is private. No VPC is created or assumed safe from its name alone. Self-hosted agents must reach the private API and ECR, and have Python 3, AWS CLI v2, Docker, Helm 3, Terraform >=1.10, Trivy and kubectl installed.

The reference initially attaches the standard VPC CNI policy to the node role for bootstrap compatibility. Before a hardened production release, move CNI permissions to a narrowly scoped dedicated Pod Identity/IRSA role and validate this change. Plan and manage CoreDNS/kube-proxy/other add-ons explicitly. The reference is not a complete enterprise landing zone or an unconditional production certification.

Create a private, encrypted, versioned S3 Terraform-state bucket and appropriate KMS policy before the platform pipeline. Copy `backend.hcl.example` to `backend.hcl` and `terraform.tfvars.example` to `terraform.tfvars`, review/replace all placeholders, and upload the completed files to Azure DevOps Library Secure Files as `<app>-eks.tfvars` and `<app>-eks-backend.hcl` (for the sample: `orders-eks.tfvars` and `orders-eks-backend.hcl`). Authorize only the platform pipeline to download them; the generated pipeline retrieves them at runtime and verifies that the backend config matches the approved plan. Keep actual state/config/plan files private. Terraform native S3 locking requires a compatible Terraform version and lock-object permissions. Commit the provider lock file for repeatable subsequent changes. The platform pipeline publishes a **sensitive** saved plan and lock file, pauses for Ops approval, and applies that exact plan; restrict artifact access/retention. A saved plan is tied to the source, state and provider versions, not transferable to an unrelated checkout.

## Artifact handoff and Ops gate

Import the application image pipeline from the application repo and the platform/release pipelines from the infrastructure repo. Set the real source application pipeline name/project, allowed branch, service connections and pool in configuration. Merge reviewed YAML into the default branches and configure Azure DevOps repository, pipeline-resource and cross-project artifact permissions. Set pipeline default branches correctly, including refs/heads prefixes for cross-project completion triggers.

A successful Package stage on the allowed branch automatically starts the release. The release downloads that triggering run's artifact, verifies ECR repository/account/region, immutable digest, source commit and build ID, then deploys staging. Production requires the configured Ops/DevOps group via ManualValidation and independent Azure DevOps production Environment approvals. Disable self-approval and restrict check administration. Do not approve superseded waiting runs blindly.

## Workload identity and secrets

An optional workload identity role ARN adds an IRSA annotation only. You must create the EKS OIDC provider, a role trust constrained to the exact namespace/service account and least-privilege data policies, and use an IRSA-compatible AWS SDK. Alternatively adapt to EKS Pod Identity using its agent and associations; an annotation alone does not configure Pod Identity. Never place business credentials in images, Helm values, build arguments or Pipeline Artifacts.

The chart's default-deny egress permits DNS and explicitly reviewed CIDR/port rules. IAM token services, data stores and telemetry need a validated egress design; do not guess AWS service IPs. Private endpoints, FQDN-aware controls or approved egress gateways may be necessary. Verify DNS labels/NodeLocal DNS behavior and actual network-policy enforcement.

References: [EKS access entries](https://docs.aws.amazon.com/eks/latest/userguide/access-entries.html), [EKS identity guidance](https://docs.aws.amazon.com/eks/latest/best-practices/identity-and-access-management.html), [Azure DevOps Environment checks](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/approvals?view=azure-devops).

Build on linux/amd64 agents for the supplied x86_64 node-group AMI, or change the build target and node architecture together. A successful local Apple-silicon runtime test does not prove x86 image compatibility.

Install and validate metrics-server before using the chart HPA. Managed node-group min/max bounds do not install cluster autoscaling; add and scope your approved Cluster Autoscaler/Karpenter design if node elasticity is required.
