# Terraform team platform

A Terraform take-home implementation for self-service team S3 resources. A reusable module creates resources for one team at a time; each team owns a declaration file; production deployments use one remote Terraform state object per team.

## Architecture

```text
teams/payments.tfvars  ─┐
platform/dev.tfvars    ─┼─> live/ root ─> modules/team-resources
CI state key            ─┘
```

`modules/team-resources/` is the reusable platform module. It creates a team IAM role and the S3 buckets requested by one team.

`live/` is the Terraform root configuration. A CI run invokes it once for each selected team.

`teams/<team>.tfvars` is owned by the team and declares its identity, approved workload role, and buckets. `platform/dev.tfvars` holds centrally managed account-wide values such as namespace, account ID, and AWS region.

The CI workflow derives the team ID from the filename only to find the declaration and build the state key. For example:

```text
teams/payments.tfvars -> team ID: payments -> state key: teams/payments/terraform.tfstate
```

This is deliberately not an all-team Terraform `for_each`: one Terraform execution manages one team and one state file.

## Repository layout

```text
.github/workflows/terraform.yml       CI: tests, detection, isolated deployment
modules/team-resources/               Reusable S3 and IAM module
  tests/team.tftest.hcl               Module contract tests with mocked AWS
live/                                 Root configuration for one team execution
  tests/team.tftest.hcl               Reusable per-team root wiring test
platform/dev.tfvars                   Platform-owned environment configuration
teams/payments.tfvars                 Payments resource declaration
teams/fraud.tfvars                    Fraud resource declaration
```

## Team declaration

Example `teams/payments.tfvars`:

```hcl
team_name = "payments"

trusted_role_arn = "arn:aws:iam::123456789012:role/payments-workload"

buckets = {
  receipts = {
    visibility = "private"
  }

  assets = {
    visibility = "public"
  }
}
```

Every bucket must explicitly declare `visibility = "public"` or `visibility = "private"`; there is no default. The `buckets` map must contain at least one bucket. Each map key is a stable resource identity, so renaming a key can cause Terraform to replace that bucket.

Example `platform/dev.tfvars`:

```hcl
namespace  = "demo-dev"
account_id = "123456789012"
aws_region = "eu-central-1"
```

The module enforces bucket names in this form:

```text
<namespace>-<team>-<purpose>-<account-id>
```

For example, `payments` and `receipts` produces:

```text
demo-dev-payments-receipts-123456789012
```

AWS remains the authority on global S3 bucket-name availability.

`trusted_role_arn` is an existing workload identity allowed to assume the new generated team S3 role. It could be an EKS IRSA role, ECS task role, Lambda execution role, or another approved application identity. The module does not trust an AWS-account wildcard principal.

## Local prerequisites and mock tests

On macOS:

```bash
brew install git jq
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
terraform version
```

CI uses Terraform 1.9.8 and AWS provider 5.x. Keep `.terraform-version` and the workflow pin aligned.

Run from the repository root:

```bash
terraform fmt -check -recursive

terraform -chdir=modules/team-resources init -backend=false
terraform -chdir=modules/team-resources validate
terraform -chdir=modules/team-resources test

terraform -chdir=live init -backend=false
terraform -chdir=live validate

terraform -chdir=live test \
  -var-file=../platform/dev.tfvars \
  -var-file=../teams/payments.tfvars

terraform -chdir=live test \
  -var-file=../platform/dev.tfvars \
  -var-file=../teams/fraud.tfvars
```

Terraform downloads the AWS provider during `init`, but these tests need no AWS credentials and create no AWS resources. Tests use Terraform's `mock_provider "aws" {}` capability.

## Testing strategy

The module test uses fixed representative inputs for Payments. This lets it assert exact resource names, policy JSON, tags, encryption, versioning, public/private settings, and IAM permissions. It is a module contract test, not a test for a specific live team.

The root test is parameterized. CI runs the same test file using each changed team's actual `.tfvars` file. It verifies the root can instantiate the module from that declaration and that every requested bucket appears in the module output.

Mock tests cover:

- Resource count, deterministic names, and ownership tags.
- Empty bucket maps, invalid bucket keys, invalid team names, and invalid visibility values.
- Bucket-owner-enforced object ownership, default AES256 encryption, HTTPS-only policies, versioning, and `force_destroy = false`.
- Private bucket public-access blocking.
- Public bucket anonymous object reads only, with no anonymous writes or listing.
- Exact least-privilege IAM bucket/object permissions and the configured trust principal.

Mock tests do not prove AWS API acceptance, effective IAM authorization, account-level public-access controls, global name availability, backend locking, or real idempotency. A protected sandbox integration suite should deploy two teams, verify each role can access only its own private bucket, test public HTTPS reads, verify denied anonymous writes/listing, re-plan for no changes, and test state locking.

## CI/CD

The workflow has four stages:

1. `test` runs formatting, validation, and module mock tests for every pull request and push.
2. `detect` compares Git changes. A change to `teams/payments.tfvars` selects Payments. A change to shared code under `modules/`, `live/`, `platform/`, or workflow files selects all teams.
3. `mock_team_tests` runs the root mock test for each selected team. This runs on pull requests without AWS credentials.
4. `deploy_changed_teams` runs only after a push to `main` or manual dispatch. It authenticates using GitHub OIDC, then initializes and applies each selected team using that team's unique backend key.

Teams are distributed over a maximum of 20 CI batches, with a maximum of five batches running concurrently. This avoids GitHub Actions' 256-job matrix limit while remaining workable for 300+ teams.

The deployment loop is the state-isolation mechanism:

```bash
terraform -chdir=live init -reconfigure \
  -backend-config="key=teams/$team/terraform.tfstate"
```

Payments and Fraud therefore use different S3 objects and separate DynamoDB lock identities:

```text
teams/payments/terraform.tfstate
teams/fraud/terraform.tfstate
```

The production job uses a protected GitHub Environment and workflow-level concurrency. The Environment should require a reviewer before Terraform applies changes. `cancel-in-progress: false` ensures GitHub does not cancel a running Terraform apply.

## Real AWS prerequisites

The backend is bootstrap infrastructure and must exist before team deployments. It is separate from the team state it stores.

Create or obtain:

- A private, encrypted, versioned S3 state bucket.
- A DynamoDB lock table with a string partition key named `LockID` for Terraform 1.9.8 locking.
- A GitHub OIDC provider in AWS and an AWS deployment role trusted only by this repository, protected environment, and intended branch.
- A deployment role with the needed backend, S3, and IAM permissions. This is separate from each generated team S3 role.

Configure the `terraform-production` GitHub Environment:

| Name | Type | Purpose |
|---|---|---|
| `AWS_REGION` | Variable | Deployment region, for example `eu-central-1` |
| `TF_STATE_BUCKET` | Variable | Existing Terraform-state S3 bucket |
| `TF_LOCK_TABLE` | Variable | Existing DynamoDB lock table |
| `TERRAFORM_DEPLOY_ROLE_ARN` | Secret | AWS role GitHub assumes through OIDC |

In production, restrict deployment identities to the required state prefixes. Separate S3 keys isolate Terraform state operationally, but an over-privileged identity could still read another team's state.

## Security decisions

- Private buckets block public ACLs and public bucket policies.
- Public buckets still disable ACL-based access. Their resource policy permits only anonymous `s3:GetObject` against that bucket's objects; it permits no anonymous write or list action.
- Every bucket denies unencrypted HTTP transport, enables versioning, and configures default AES256 encryption.
- Account-level S3 Block Public Access or an SCP may intentionally reject public bucket policies. Public access therefore requires an approved account posture; a private bucket behind CloudFront is often preferable.
- The generated team role has no IAM administration, bucket-policy administration, or access to other teams' bucket ARNs. It permits only `ListBucket`, `GetBucketLocation`, `GetObject`, `PutObject`, and `DeleteObject` for its own resources.
- Public objects are intentionally accessible by everyone, including other teams. This is incompatible with absolute cross-team denial for those objects.
- The module omits KMS, multipart-upload actions, lifecycle controls, and object-version deletion permissions until a workload needs them.
- A single inline IAM policy is clear for this exercise. Very large bucket counts per team can hit IAM policy-size quotas; production designs may split policies or use approved ABAC patterns.

## Onboarding, ownership, and offboarding

To onboard a normal team, add `teams/<team>.tfvars`, declare a nonempty bucket map, and open a pull request. No module or workflow code changes are required.

Use CODEOWNERS and branch protection in a real organization: require team review for a team's file, platform review for shared module/workflow files, and an approval policy for new public buckets and trusted workload principals. Repository directory boundaries alone are not authorization.

CI blocks deletion or rename of a team declaration. A team is offboarded through a separate, reviewed maintenance process:

1. Stop writers and decide whether data is retained, archived, or deleted.
2. Initialize Terraform with that team's original backend key.
3. Create and review a `terraform plan -destroy` plan using the original team declaration.
4. Empty/archive bucket data only through an approved data-handling process; versioned buckets require handling object versions and delete markers.
5. Apply the approved destroy plan, archive final state/audit evidence, revoke access, then remove the team declaration.

`force_destroy = false` prevents Terraform from silently emptying a nonempty bucket. It does not prevent deletion of an empty bucket, so deployment approval and destructive-plan review remain necessary.

## References

- https://developer.hashicorp.com/terraform/language/tests
- https://developer.hashicorp.com/terraform/language/tests/mocking
- https://developer.hashicorp.com/terraform/language/backend/s3
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html
