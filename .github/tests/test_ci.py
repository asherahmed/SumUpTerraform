"""Regression tests for the actual inline workflow code; no AWS credentials needed.

Keeping orchestration in YAML is intentional. These tests extract and execute its
validator and change detector, so they do not maintain a second implementation.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


def document(path):
    return yaml.safe_load((ROOT / path).read_text())


CI = document(".github/workflows/terraform.yml")
DEPLOY = document(".github/workflows/deploy.yml")
ACTION = document(".github/actions/validate-config/action.yml")
validator_source = next(s["run"] for s in ACTION["runs"]["steps"] if s.get("id") == "contract")
namespace = {"__name__": "regression_test"}
exec(compile(validator_source, "validate-config/action.yml", "exec"), namespace)
validate_repository = namespace["validate_repository"]


class DeclarationContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "teams").mkdir()
        (self.root / "platform").mkdir()
        (self.root / "platform/dev.tfvars").write_text((ROOT / "platform/dev.tfvars").read_text())
        self.path = self.root / "teams/payments.tfvars"
        self.original = (ROOT / "teams/payments.tfvars").read_text()
        self.path.write_text(self.original)

    def test_real_repository_declarations(self):
        # Adding team 301 must not require updating a hardcoded expected team list.
        self.assertTrue(validate_repository(ROOT))

    def test_valid_team(self):
        self.assertEqual(validate_repository(self.root), ["payments"])

    def test_identity_cannot_target_another_teams_resources(self):
        self.path.write_text(self.original.replace('team_name = "payments"', 'team_name = "fraud"'))
        with self.assertRaisesRegex(ValueError, "must equal filename"):
            validate_repository(self.root)

    def test_platform_overrides_rejected_even_after_multiline_comment(self):
        for field, value in (("account_id", "999999999999"), ("namespace", "other-dev"), ("aws_region", "us-east-1")):
            with self.subTest(field=field):
                self.path.write_text(self.original + f'\n/* harmless comment */\n{field} = "{value}"\n')
                with self.assertRaisesRegex(ValueError, "platform overrides are forbidden"):
                    validate_repository(self.root)

    def test_comments_do_not_count_as_assignments(self):
        self.path.write_text(self.original + '\n# account_id = "999999999999"\n')
        self.assertEqual(validate_repository(self.root), ["payments"])

    def test_unknown_bucket_fields_rejected(self):
        self.path.write_text(self.original.replace('visibility = "private"', 'visibility = "private"\n    account_id = "999999999999"'))
        with self.assertRaisesRegex(ValueError, "visibility only"):
            validate_repository(self.root)

    def test_missing_null_invalid_visibility_rejected(self):
        for value in ("", "visibility = null", 'visibility = "internal"'):
            with self.subTest(value=value):
                self.path.write_text(self.original.replace('visibility = "private"', value))
                with self.assertRaises(ValueError):
                    validate_repository(self.root)

    def test_wildcard_trust_rejected(self):
        self.path.write_text(self.original.replace("role/payments-workload", "role/*"))
        with self.assertRaisesRegex(ValueError, "explicit IAM role"):
            validate_repository(self.root)

    def test_filename_cannot_escape_team_directory(self):
        nested = self.root / "teams/nested"
        nested.mkdir()
        self.path.rename(nested / "payments.tfvars")
        with self.assertRaisesRegex(ValueError, "invalid team filename"):
            validate_repository(self.root)

    def test_symbolic_link_rejected(self):
        target = self.root / "payments.tfvars"
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "regular files"):
            validate_repository(self.root)

    def test_empty_repository_rejected(self):
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "At least one team"):
            validate_repository(self.root)

    def test_new_team_requires_no_code_changes(self):
        (self.root / "teams/identity.tfvars").write_text(self.original.replace("payments", "identity"))
        self.assertEqual(validate_repository(self.root), ["identity", "payments"])


class ChangeDetection(unittest.TestCase):
    def detect(self, changed=(), deleted=(), files=None, event="pull_request", base="previous"):
        step = next(s for s in CI["jobs"]["detect"]["steps"] if s.get("id") == "teams")
        payload = {
            "source": step["with"]["script"], "changed": list(changed), "deleted": list(deleted),
            "files": files or ["teams/fraud.tfvars", "teams/payments.tfvars"],
            "event": event, "base": base,
        }
        # Mock only Git I/O and GitHub's context. Execute the workflow's JS unchanged.
        harness = r'''
        const fs = require('node:fs');
        const input = JSON.parse(fs.readFileSync(0, 'utf8'));
        const outputs = {};
        const mockRequire = name => {
          if (name !== 'node:child_process') throw new Error(name);
          return {execFileSync: (cmd, args) => {
            if (cmd !== 'git') throw new Error(cmd);
            const data = args[0] === 'ls-files' ? input.files
              : args.includes('--diff-filter=D') ? input.deleted : input.changed;
            return data.join('\0');
          }};
        };
        const context = {eventName: input.event, payload: {
          before: input.base, pull_request: {base: {sha: input.base}}
        }};
        try {
          new Function('require', 'context', 'core', input.source)(
            mockRequire, context, {setOutput: (k,v) => {outputs[k] = v;}}
          );
          console.log(JSON.stringify(outputs));
        } catch (error) { console.error(error.message); process.exit(1); }
        '''
        result = subprocess.run(["node", "-e", harness], input=json.dumps(payload), text=True, capture_output=True)
        if result.returncode:
            raise ValueError(result.stderr)
        return json.loads(result.stdout)

    def selected(self, **kwargs):
        result = self.detect(**kwargs)
        matrix = json.loads(result["matrix"])
        return sorted(t for batch in matrix["include"] for t in batch["teams"])

    def test_one_team_change(self):
        self.assertEqual(self.selected(changed=["teams/payments.tfvars"]), ["payments"])

    def test_shared_changes_select_all_teams(self):
        for path in ("platform/dev.tfvars", "live/main.tf", "modules/team-resources/main.tf", ".github/actions/validate-config/action.yml", ".github/tests/test_ci.py"):
            with self.subTest(path=path):
                self.assertEqual(self.selected(changed=[path]), ["fraud", "payments"])

    def test_readme_only_selects_no_teams(self):
        result = self.detect(changed=["README.md"])
        self.assertEqual(result["has_changes"], "false")
        self.assertEqual(json.loads(result["matrix"]), {"include": []})

    def test_dispatch_and_first_push_select_all(self):
        self.assertEqual(self.selected(event="workflow_dispatch"), ["fraud", "payments"])
        self.assertEqual(self.selected(event="push", base="0" * 40), ["fraud", "payments"])

    def test_deletion_and_rename_require_offboarding(self):
        with self.assertRaisesRegex(ValueError, "offboarding"):
            self.detect(deleted=["teams/payments.tfvars"])

    def test_301_teams_all_appear_once(self):
        files = [f"teams/team-{i:03d}.tfvars" for i in range(301)]
        result = self.detect(files=files, changed=["modules/team-resources/main.tf"])
        batches = json.loads(result["matrix"])["include"]
        teams = [t for batch in batches for t in batch["teams"]]
        self.assertLessEqual(len(batches), 20)
        self.assertEqual(len(teams), 301)
        self.assertEqual(len(set(teams)), 301)


class DeploymentBoundaries(unittest.TestCase):
    """Static wiring checks catch regressions that mock Terraform cannot observe."""
    def test_deployment_is_opt_in_and_main_only_for_both_jobs(self):
        for name in ("plan", "apply"):
            gate = DEPLOY["jobs"][name]["if"]
            self.assertIn("vars.TERRAFORM_DEPLOY_ENABLED == 'true'", gate)
            self.assertIn("github.ref == 'refs/heads/main'", gate)

    def test_whole_run_serialized_and_every_team_reconciled(self):
        self.assertIs(DEPLOY["concurrency"]["cancel-in-progress"], False)
        for job in DEPLOY["jobs"].values():
            self.assertNotIn("concurrency", job)
            self.assertNotIn("strategy", job)
            code = "\n".join(s.get("run", "") for s in job["steps"])
            self.assertIn("for file in teams/*.tfvars", code)
            self.assertIn('key=teams/$team/terraform.tfstate', code)

    def test_feature_dispatch_cannot_replace_pending_main_deployment(self):
        self.assertIn("github.ref", DEPLOY["concurrency"]["group"])

    def test_plan_artifact_exists_before_apply_approval(self):
        plan, apply = DEPLOY["jobs"]["plan"], DEPLOY["jobs"]["apply"]
        self.assertEqual(apply["needs"], "plan")
        self.assertEqual(apply["environment"], "terraform-production")
        self.assertNotEqual(plan["environment"], apply["environment"])
        self.assertTrue(any(s.get("uses", "").startswith("actions/upload-artifact@") for s in plan["steps"]))
        download = next(s for s in apply["steps"] if s.get("uses", "").startswith("actions/download-artifact@"))
        self.assertIn("needs.plan.outputs.artifact_id", download["with"]["artifact-ids"])
        code = "\n".join(s.get("run", "") for s in apply["steps"])
        self.assertNotIn("terraform -chdir=live plan", code)
        self.assertIn('apply -lock-timeout=5m "$RUNNER_TEMP/team-plans/$team.tfplan"', code)
        self.assertIn("git ls-remote origin refs/heads/main", code)
        self.assertIn("manifest.json", code)

    def test_ci_has_no_oidc_permission(self):
        self.assertNotIn("id-token", CI["permissions"])

    def test_platform_file_has_final_precedence(self):
        for workflow in (CI, DEPLOY):
            for job in workflow["jobs"].values():
                for step in job.get("steps", []):
                    code = step.get("run", "").replace("\\\n", " ")
                    for line in code.splitlines():
                        if "terraform -chdir=live test" in line or "terraform -chdir=live plan " in line:
                            self.assertGreater(line.rindex('-var-file="$PLATFORM_CONFIG"'), line.index('-var-file="../'))


if __name__ == "__main__":
    unittest.main()
