"""Execute the actual comment job against mocked GitHub and artifact APIs."""
import json
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/terraform.yml").read_text())
JOB = WORKFLOW["jobs"]["comment_plan"]
SOURCE = JOB["steps"][-1]["with"]["script"]


class PlanComment(unittest.TestCase):
    def execute(self, files=None, previous=False, stale=False, changes="true", detection="success"):
        fixture = dict(files=files or {}, previous=previous, stale=stale)
        harness = r"""
const fixture = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const source = process.argv[1];
const writes = [];
const context = {serverUrl:'https://github.com',repo:{owner:'example',repo:'repo'},runId:123,
  issue:{number:1},payload:{pull_request:{head:{sha:'current'}}}};
const fs = {existsSync:()=>true,readdirSync:()=>Object.keys(fixture.files),
  readFileSync:path=>fixture.files[path.split('/').pop()]};
const github = {rest:{pulls:{get:async()=>({data:{head:{sha:fixture.stale?'newer':'current'}}})},
  issues:{listComments:()=>{},updateComment:async x=>writes.push({kind:'update',...x}),
    createComment:async x=>writes.push({kind:'create',...x})}},
  paginate:async()=>fixture.previous?[{id:42,user:{login:'github-actions[bot]'},
    body:'<!-- terraform-team-platform-mock-plan --> old'}]:[]};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('require','context','github','core',source)(()=>fs,context,github,{info:()=>{}})
  .then(()=>process.stdout.write(JSON.stringify(writes))).catch(e=>{console.error(e);process.exit(1)});
"""
        import os
        env = dict(os.environ, HAS_CHANGES=changes, DETECTION_RESULT=detection,
                   TEST_RESULT="success", MOCK_RESULT="failure")
        result = subprocess.run(["node", "-e", harness, SOURCE], input=json.dumps(fixture),
                                env=env, check=True, text=True, capture_output=True)
        return json.loads(result.stdout)

    def test_creates_labelled_escaped_preview(self):
        result = self.execute({"payments.txt": "Plan: 1 to add. <script>bad</script>"})[0]
        self.assertEqual(result["kind"], "create")
        self.assertIn("not a live, state-aware AWS plan", result["body"])
        self.assertIn("&lt;script&gt;", result["body"])
        self.assertIn("mock plans: failure", result["body"])

    def test_updates_existing_comment(self):
        result = self.execute(previous=True)[0]
        self.assertEqual(result["kind"], "update")
        self.assertEqual(result["comment_id"], 42)

    def test_skips_superseded_commit(self):
        self.assertEqual(self.execute(stale=True), [])

    def test_large_batch_is_bounded(self):
        result = self.execute({f"team-{i}.txt": "x" * 20000 for i in range(301)})[0]
        self.assertLess(len(result["body"]), 60000)
        self.assertIn("additional team previews", result["body"])

    def test_no_changes_replaces_stale_preview(self):
        self.assertIn("No team or shared", self.execute(changes="false")[0]["body"])

    def test_missing_artifacts_and_detection_failure(self):
        self.assertIn("No preview artifacts", self.execute()[0]["body"])
        self.assertIn("Team detection failed", self.execute(detection="failure")[0]["body"])

    def test_write_permission_is_only_in_comment_job(self):
        self.assertEqual(JOB["permissions"], {"contents": "read", "pull-requests": "write"})
        self.assertIn("head.repo.full_name == github.repository", JOB["if"])
        self.assertFalse(any("checkout" in step.get("uses", "") for step in JOB["steps"]))
