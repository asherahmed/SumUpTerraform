resource "aws_iam_role" "team" {
  name = "${var.namespace}-${var.team_name}-s3"
  tags = local.tags
  # Trust answers WHO may assume the role; the separate policy below answers WHAT
  # the assumed role may do. The approved workload principal must already exist.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = var.trusted_role_arn }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "s3" {
  name = "team-bucket-access"
  role = aws_iam_role.team.id
  policy = jsonencode({
    Version = "2012-10-17"
    # Bucket actions need bucket ARNs; object actions need bucket ARN + /*.
    # Explicit resources keep the granted permissions inside this team's scope.
    Statement = [
      {
        Sid      = "BucketAccess"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = values(local.arns)
      },
      {
        Sid      = "ObjectAccess"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [for arn in values(local.arns) : "${arn}/*"]
      }
    ]
  })
}
