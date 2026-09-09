variable "team_name" {
  type        = string
  description = "Team identifier declared in the team file; CI verifies it matches the filename."
  nullable    = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,14}[a-z0-9]$", var.team_name))
    error_message = "Team names must be 2-16 lowercase letters, digits or hyphens; start with a letter and end alphanumeric."
  }
}

variable "namespace" {
  type        = string
  description = "Platform-managed namespace; include environment, for example demo-dev."
  nullable    = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,8}[a-z0-9]$", var.namespace))
    error_message = "Namespace must be 2-10 lowercase letters, digits or hyphens."
  }
}

variable "account_id" {
  type        = string
  description = "Target commercial AWS account ID."
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Provide a 12-digit AWS account ID."
  }
}

variable "trusted_role_arn" {
  type        = string
  description = "Platform-approved existing workload role that may assume this team's role."
  nullable    = false
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/.+$", var.trusted_role_arn))
    error_message = "Use an explicit commercial AWS IAM role ARN, not a wildcard or account root."
  }
}

variable "buckets" {
  type = map(object({
    visibility = string
  }))
  description = "Buckets keyed by stable purpose; visibility is mandatory."
  nullable    = false
  validation {
    condition     = length(var.buckets) > 0
    error_message = "Each team must declare at least one bucket."
  }
  validation {
    condition     = alltrue([for k, v in var.buckets : can(regex("^[a-z][a-z0-9-]{0,14}[a-z0-9]$", k))])
    error_message = "Bucket keys must be 2-16 lowercase letters, digits or hyphens."
  }
  validation {
    condition     = alltrue([for b in var.buckets : try(contains(["public", "private"], b.visibility), false)])
    error_message = "Every bucket must explicitly declare public or private visibility."
  }
}

variable "aws_region" {
  type    = string
  default = "eu-central-1"
}
