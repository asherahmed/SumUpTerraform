mock_provider "aws" {}

variables {
  team_name        = "payments"
  namespace        = "demo-dev"
  account_id       = "123456789012"
  trusted_role_arn = "arn:aws:iam::123456789012:role/payments-workload"
  buckets = {
    receipts = { visibility = "private" }
    assets   = { visibility = "public" }
  }
}

run "resource_contract" {
  command = plan
  assert {
    condition     = length(aws_s3_bucket.this) == 2 && aws_iam_role.team.name == "demo-dev-payments-s3"
    error_message = "Expected two buckets and the correctly named team role."
  }
  assert {
    condition     = aws_s3_bucket.this["receipts"].bucket == "demo-dev-payments-receipts-123456789012"
    error_message = "Bucket naming contract changed."
  }
  assert {
    condition     = alltrue([for b in aws_s3_bucket.this : b.tags.Team == "payments" && b.tags.ManagedBy == "Terraform" && !b.force_destroy])
    error_message = "Ownership tags and nonempty bucket protection are required."
  }
  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.this["receipts"].block_public_acls,
      aws_s3_bucket_public_access_block.this["receipts"].ignore_public_acls,
      aws_s3_bucket_public_access_block.this["receipts"].block_public_policy,
      aws_s3_bucket_public_access_block.this["receipts"].restrict_public_buckets,
      aws_s3_bucket_public_access_block.this["assets"].block_public_acls,
      aws_s3_bucket_public_access_block.this["assets"].ignore_public_acls,
      !aws_s3_bucket_public_access_block.this["assets"].block_public_policy,
      !aws_s3_bucket_public_access_block.this["assets"].restrict_public_buckets
    ])
    error_message = "Visibility controls must match declarations while blocking ACLs."
  }
  assert {
    condition     = alltrue([for c in aws_s3_bucket_ownership_controls.this : one(c.rule).object_ownership == "BucketOwnerEnforced"])
    error_message = "ACLs must be disabled."
  }
  assert {
    condition     = alltrue([for c in aws_s3_bucket_versioning.this : one(c.versioning_configuration).status == "Enabled"])
    error_message = "Versioning must be enabled."
  }
  assert {
    condition     = alltrue([for c in aws_s3_bucket_server_side_encryption_configuration.this : one(one(c.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"])
    error_message = "Default encryption must be configured."
  }
  assert {
    condition     = length(jsondecode(aws_s3_bucket_policy.this["receipts"].policy).Statement) == 1 && jsondecode(aws_s3_bucket_policy.this["receipts"].policy).Statement[0].Effect == "Deny"
    error_message = "Private buckets must have no public allow statement."
  }
  assert {
    condition = jsondecode(aws_s3_bucket_policy.this["assets"].policy).Statement[1] == {
      Sid       = "PublicObjectRead"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "arn:aws:s3:::demo-dev-payments-assets-123456789012/*"
    }
    error_message = "Public access must allow only reads of this bucket's objects."
  }
  assert {
    condition     = alltrue([for p in aws_s3_bucket_policy.this : jsondecode(p.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false" && jsondecode(p.policy).Statement[0].Effect == "Deny"])
    error_message = "Every bucket must deny HTTP access."
  }
  assert {
    condition = jsondecode(aws_iam_role_policy.s3.policy) == {
      Version = "2012-10-17"
      Statement = [
        {
          Sid      = "BucketAccess"
          Effect   = "Allow"
          Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
          Resource = ["arn:aws:s3:::demo-dev-payments-assets-123456789012", "arn:aws:s3:::demo-dev-payments-receipts-123456789012"]
        },
        {
          Sid      = "ObjectAccess"
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
          Resource = ["arn:aws:s3:::demo-dev-payments-assets-123456789012/*", "arn:aws:s3:::demo-dev-payments-receipts-123456789012/*"]
        }
      ]
    }
    error_message = "Team IAM policy must contain only the approved actions and exact team resources."
  }
  assert {
    condition     = jsondecode(aws_iam_role.team.assume_role_policy).Statement[0].Principal.AWS == var.trusted_role_arn
    error_message = "Trust must be restricted to the approved workload role."
  }
}

run "reject_empty_buckets" {
  command = plan
  variables {
    buckets = {}
  }
  expect_failures = [var.buckets]
}

run "reject_invalid_visibility" {
  command = plan
  variables {
    buckets = { receipts = { visibility = "internal" } }
  }
  expect_failures = [var.buckets]
}

run "reject_null_visibility" {
  command = plan
  variables {
    buckets = { receipts = { visibility = null } }
  }
  expect_failures = [var.buckets]
}

run "reject_invalid_team" {
  command = plan
  variables {
    team_name = "Payments!"
  }
  expect_failures = [var.team_name]
}

run "reject_invalid_bucket_key" {
  command = plan
  variables {
    buckets = { Bad_Name = { visibility = "private" } }
  }
  expect_failures = [var.buckets]
}
