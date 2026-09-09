# CI requires team_name to match this filename, tying resources to the state key.

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
