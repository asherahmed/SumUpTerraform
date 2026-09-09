locals {
  # Stable map keys become Terraform addresses. Avoid list indexes: inserting a
  # bucket should not rename or replace unrelated buckets.
  names = { for key, bucket in var.buckets : key => "${var.namespace}-${var.team_name}-${key}-${var.account_id}" }
  arns  = { for key, name in local.names : key => "arn:aws:s3:::${name}" }
  tags = {
    Team      = var.team_name
    Namespace = var.namespace
    ManagedBy = "Terraform"
  }
}

resource "aws_s3_bucket" "this" {
  for_each = var.buckets
  bucket   = local.names[each.key]
  # Offboarding must explicitly handle objects and versions before deletion.
  force_destroy = false
  tags          = merge(local.tags, { Purpose = each.key })
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = var.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = var.buckets
  bucket   = aws_s3_bucket.this[each.key].id

  # Even public buckets use a narrow bucket policy, never public ACLs.
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = each.value.visibility == "private"
  restrict_public_buckets = each.value.visibility == "private"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = var.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = var.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "this" {
  for_each = var.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    # Every bucket denies HTTP. Only explicitly public buckets append a GET allow.
    Statement = concat([
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [local.arns[each.key], "${local.arns[each.key]}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
      ], each.value.visibility == "public" ? [
      {
        Sid       = "PublicObjectRead"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${local.arns[each.key]}/*"
      }
    ] : [])
  })
  # Set ownership and public-policy controls before AWS receives the bucket policy.
  depends_on = [aws_s3_bucket_public_access_block.this, aws_s3_bucket_ownership_controls.this]
}
