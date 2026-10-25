# EKS LaunchBridge

A runnable preparation agent for moving reviewed Linux HTTP applications from EC2 instances to EKS, using **separate application and infrastructure repositories**, Azure DevOps and Helm.

Infrastructure is prepared independently. **No application branch is created until the container builds and passes runtime health checks.** If it fails, application work is marked blocked for the application team. A successful application pipeline automatically supplies its immutable image artifact to the infrastructure release pipeline. Staging runs automatically; production requires an **Ops/DevOps approval**.

This is a tested migration starter, not proof that an arbitrary VM can be automatically converted or that an untested customer migration is production-ready. No customer VM, subscription, pipeline or production traffic was changed to develop it.

## Try it locally

Requirements: Python 3.9+, Git with author identity configured, Docker Engine/Desktop running. No Python packages are required to run the agent. macOS, Linux and Windows with Linux containers are intended; local validation used macOS.

```sh
git clone https://github.com/THEJANAIDU/eks-launchbridge.git
cd eks-launchbridge
python3 eks_migrate.py demo --destination ../eks-launchbridge-demo
```

Windows: use `py` in place of `python3`. The demo creates two disposable customer repositories, infrastructure assets on an infrastructure branch, and an application branch **after** building and testing the supplied application. Original branches and the illustrative VM pipeline remain unchanged. It does not log in to AWS or provision paid services.

## Use your two repositories

Copy `examples/migration.example.json` **outside both customer checkouts**, fill in your real values, and review every assessment answer. Null answers block application preparation. `container_tested` is derived from the actual runtime check, not trusted as a substitute for it.

```sh
python3 eks_migrate.py prepare \
  --app-repo /path/to/application \
  --infra-repo /path/to/infrastructure \
  --config /path/to/migration.json \
  --app-base origin/master \
  --infra-base origin/master \
  --refresh
```

Use `origin/main` if appropriate. Omit base flags only when the remote default is configured or exactly one local main/master exists. Branches start from the resolved base commit. Source checkouts must be clean. Generated files are committed in new sibling worktrees; the source checkout is not switched. Nothing is pushed unless you add `--push`. Use your existing Git authentication; never put a PAT into the configuration.

Infrastructure can also be prepared alone:

```sh
python3 eks_migrate.py prepare-infra --repo /path/to/infrastructure --config /path/to/migration.json --base origin/master
```

After the application team resolves blockers, retry only the application:

```sh
python3 eks_migrate.py prepare-app --repo /path/to/application --config /path/to/migration.json --base origin/master
```

Existing branch/worktree destinations and migration files are never overwritten. Standalone commands accept `--branch` and `--worktree` for a new attempt. Reports and private build logs are written outside the application checkout by default; do not publish logs without reviewing them for secrets.

## What it generates

| Application repository | Infrastructure repository |
|---|---|
| `.eks-migration/config.json`, runtime assessment, checklist and standalone agent | `.eks-platform/infra/` private EKS/ECR Terraform reference |
| New `.azure-pipelines/eks-image.yml` | Helm chart, staging/production values, restricted namespaces and quotas |
| Existing VM pipeline preserved | New platform planning/apply and artifact-driven release pipelines |
| Build → runtime test → vulnerability scan → ECR digest artifact | Triggering artifact → staging → Ops approval → same digest to production |

For classic Azure DevOps releases, `source.vm_pipeline` can point to a committed reference document instead of YAML; the external classic release is not changed.

The existing workload must have a Dockerfile and an HTTP readiness endpoint. The adapter checks non-root UID 10001, read-only root filesystem, dropped capabilities, bounded memory/CPU and two HTTP health responses. It uses committed files from the selected revision, not dirty working files. Unknown language packaging, Windows containers, local databases/disks, in-memory sessions, privileged agents and background-job coordination require application-owner remediation; the agent does not guess data conversions.

## Azure DevOps handoff for AWS

1. Prepare the infrastructure branch and review its Terraform/network/cost plan. An existing compliant EKS/ECR platform can be used instead.
2. Configure three least-privilege AWS OIDC-federated service connections: registry build, application deployment, and platform provisioning.
3. Import the generated application image pipeline in Azure DevOps. Import the infrastructure platform and release pipelines from the **other** repository.
4. Set the application pipeline name, Azure DevOps project, allowed branch, agent pool and Ops group in the migration configuration before generation.
5. Merge reviewed generated YAML into the relevant repositories' default branches. Configure pipeline permissions and default branches. A successful application Package stage on the allowed branch automatically triggers release.
6. Configure production Environment approvals to require your actual Ops/DevOps group, disable self-approval, and restrict who can administer checks. YAML also contains an Ops-scoped ManualValidation task.
7. Staging and production consume the **same triggering run's digest**, never a mutable `latest` tag or whatever finishes while approval is pending.

[AWS setup and permission matrix](docs/AWS_SETUP.md) · [Operator runbook](docs/RUNBOOK.md) · [Cutover/data/rollback checklist](docs/CUTOVER.md) · [Verification and limitations](docs/VERIFICATION.md)

## Read-only VM inventory

```sh
python3 eks_migrate.py inventory --account-id YOUR_12_DIGIT_ACCOUNT --region us-east-1 --output inventory.json
```

Requires an already authenticated AWS CLI and read permission. It reads instance ID/OS/type only. No remote commands, disk copying, private configuration or secret collection occurs. Metadata inventory does not discover application dependencies or prove container readiness.

## Test

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
# Include Docker build/runtime gate tests:
RUN_DOCKER_TESTS=1 python -m pytest -q
# Helm 3 must be installed:
helm lint templates/chart --set-string image.digest=sha256:$(printf '0%.0s' {1..64})
# AWS CLI/Terraform compile, no AWS deployment:
terraform -chdir=templates/infra init -backend=false
terraform -chdir=templates/infra validate
```

Before a production migration, customers must validate identities, private DNS, networking, capacity, compliance, application semantics, data synchronization, load/soak tests, restoration and controlled traffic cutover in their own AWS environment. The kit never shuts down VMs or changes DNS automatically.

## AWS-specific scope

Uses AWS Toolkit AWSShellScript tasks with OIDC service connections, ECR digest artifacts, Terraform plan/approval/apply, EKS access entries and optional IRSA. See AWS_SETUP.md for existing VPC/private routing, state backend, KMS, IAM, add-on and hardening prerequisites. Supported AWS partition: commercial aws. It does not copy EC2 disks, migrate databases or change production traffic automatically.
