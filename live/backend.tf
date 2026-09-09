terraform {
  # CI supplies bucket/region/lock table and a unique teams/<team>/terraform.tfstate
  # key during init. Variables cannot be interpolated in this backend block.
  backend "s3" {}
}
