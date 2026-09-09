# CI reuses this test with each selected team's declaration and platform values.
# Detailed security-policy assertions live in the module's fixed-fixture tests.
mock_provider "aws" {}

run "team_declaration" {
  command = plan
  assert {
    condition     = toset(keys(output.bucket_names)) == toset(keys(var.buckets))
    error_message = "The root must preserve the exact declared bucket keys, not just their count."
  }
  assert {
    condition     = alltrue([for key, name in output.bucket_names : name == "${var.namespace}-${var.team_name}-${key}-${var.account_id}"])
    error_message = "Every bucket must use the selected team's identity and platform namespace/account."
  }
}
