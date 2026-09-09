mock_provider "aws" {}

run "team_declaration" {
  command = plan
  assert {
    condition     = length(output.bucket_names) == length(var.buckets)
    error_message = "The root must pass every declared bucket to the module."
  }
}
