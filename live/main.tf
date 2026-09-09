# One invocation manages one team. Iterating all teams here would share one state.
module "team" {
  source           = "../modules/team-resources"
  team_name        = var.team_name
  namespace        = var.namespace
  account_id       = var.account_id
  trusted_role_arn = var.trusted_role_arn
  buckets          = var.buckets
}
