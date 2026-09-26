"""controller 行为回归：真实临时 Git worktrees，Beads 使用只读 fixture。"""

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

import evidence
import execution_plan
import test_verify_phase as phase_fixture
import test_verify_ticket as ticket_fixture
import workflow_contract

SCRIPT = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"

pytestmark = pytest.mark.integration


class ControllerTests(unittest.TestCase):
    utility_fixture = True

    def setUp(self):
        self.h = ticket_fixture.TicketAcceptanceTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.root, self.primary = self.h.root.resolve(), self.h.primary.resolve()
        self.wt = self.primary / ".worktrees" / "test"
        self.wt.parent.mkdir()
        self.h.git(self.primary, "worktree", "move", str(self.h.worktree), str(self.wt))
        (self.primary / ".git/info/exclude").write_text(".worktrees/\n")
        self.env = self.h.env.copy()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "bd"
        fake.write_text(
            "#!"
            + sys.executable
            + "\nimport json,os,sys\nfrom pathlib import Path\na=sys.argv[1:]\nassert a[0] in ('show','comments'), a\nprint(Path(os.environ['BD_FIXTURE_'+a[0].upper()]).read_text())\n"
        )
        fake.chmod(0o755)
        self.env.update(
            PATH=str(bin_dir) + os.pathsep + self.env["PATH"],
            BD_FIXTURE_SHOW=str(self.root / "parent.json"),
            BD_FIXTURE_COMMENTS=str(self.root / "comments.json"),
        )
        self.put(self.root / "parent.json", [{"id": "test", "status": "closed"}])
        self.put(self.root / "comments.json", [])
        self.counter = 0

    def put(self, path, value):
        Path(path).write_text(json.dumps(value, ensure_ascii=False))
        return str(path)

    def test_update_main_uses_local_main_without_contacting_origin(self):
        self.h.git(self.primary, "remote", "add", "origin", "/nonexistent/beadwork-remote")
        main = self.h.git(self.primary, "rev-parse", "refs/heads/main")

        result = self.call("update-main", "--repository-root", self.primary)

        self.assertEqual(result, {"repository_root": str(self.primary), "main_commit": main})
        self.assertEqual(self.h.git(self.primary, "rev-parse", "refs/heads/main"), main)
        self.assertFalse((self.primary / ".git/refs/remotes/origin/main").exists())

    def call(self, *args, ok=True):
        argv = [sys.executable, "-B", str(SCRIPT), "controller", *map(str, args)]
        if getattr(self, "utility_fixture", True) and args[:2] == ("prepare", "executor"):
            code = "import sys,json;sys.path[:0]=sys.argv[1:3];from fixture_support import prepare_utility_stage;\ntry: print(json.dumps(prepare_utility_stage(json.load(open(sys.argv[3])))))\nexcept Exception as e: print(json.dumps({'error':str(e)}),file=sys.stderr);sys.exit(1)"
            argv = [
                sys.executable,
                "-B",
                "-c",
                code,
                str(Path(__file__).parent),
                str(SCRIPT.parent),
                str(args[-1]),
            ]
        result = subprocess.run(argv, cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def prepare(self, role="executor", **extra):
        d = {
            "repository_root": str(self.primary),
            "parent_id": "test",
            "ticket_id": "test-1",
            "mode": "resume",
            "base_commit": self.h.base,
            "test_mode": "TDD",
            "approved_seams": ["S1"],
            "rules_paths": [],
            "testing_seams_doc": "/rules/testing-seams.md",
            "linked_spec": "spec",
            "expected_children": ["test-1"],
            "ticket_evidence": [],
            "prior_finalization": None,
            "reviewed_main": self.h.base,
            **extra,
        }
        if role == "executor" and d["mode"] == "new":
            import uuid

            folder = self.primary / ".worktrees/.evidence/test/main-sync" / uuid.uuid4().hex
            folder.mkdir(parents=True)
            intent = dict(
                repository_root=str(self.primary),
                worktree=str(self.wt),
                branch="implement/test",
                parent_id="test",
                target_main=self.h.git(self.primary, "rev-parse", "HEAD"),
                before=self.h.git(self.wt, "rev-parse", "HEAD"),
                install_inputs=[],
                expected_children=[d["ticket_id"]],
            )
            self.put(folder / "intent.json", intent)
            d["sync_result"] = self.put(
                folder / "ready.json",
                {
                    "head": self.h.git(self.wt, "rev-parse", "HEAD"),
                    "commands": [],
                    "intent_sha256": hashlib.sha256(
                        (folder / "intent.json").read_bytes()
                    ).hexdigest(),
                },
            )
        if role == "executor" and d["mode"] == "new" and not getattr(self, "utility_fixture", True):
            # 用公开 prepare/accept 构造已核实的准入来源，不以字符串模拟来源绑定。
            value = {"ticket_order": [d["ticket_id"]]}
            self.put(
                self.root / "parent.json",
                [
                    {
                        "id": "test",
                        "status": "open",
                        "description": execution_plan.replace("", value),
                    }
                ],
            )
            self.put(
                self.root / "children.json",
                [{"id": d["ticket_id"], "status": "open", "labels": ["ready-for-agent"]}],
            )
            fake = self.root / "bin/bd"
            fake.write_text(
                "#!"
                + sys.executable
                + "\n"
                + """import json,os,sys
from pathlib import Path
a=sys.argv[1:];root=Path(os.environ['BD_FIXTURE_SHOW']).parent
if a[0]=='dep': print('[]')
elif a[0] in ('list','ready'): print((root/'children.json').read_text())
else: print(Path(os.environ['BD_FIXTURE_'+a[0].upper()]).read_text())
"""
            )
            fake.chmod(0o755)
            prepared = self.call(
                "prepare",
                "preflight",
                "--input",
                self.put(
                    self.root / "preflight-input.json",
                    {"repository_root": str(self.primary), "parent_id": "test", "rules_paths": []},
                ),
            )
            pd = Path(prepared["dispatch_path"])
            pr = phase_fixture.PhaseValidatorTests().preflight()
            plan = phase_fixture.PhaseValidatorTests().plan(d["test_mode"])
            plan["approved_seams"] = d["approved_seams"]
            pr.update(
                parent={"id": "test", "status": "open"},
                expected_children=[d["ticket_id"]],
                execution_plan=value,
                tickets=[{"id": d["ticket_id"], "status": "open", "test_plan": plan}],
                linked_spec=d["linked_spec"],
                workspace={
                    "primary_worktree": str(self.primary),
                    "implementation_worktree": str(self.wt),
                    "branch": "implement/test",
                    "observed_head": self.h.head,
                    "clean": True,
                },
            )
            rp = pd.parent / "report.json"
            self.put(rp, pr)
            rr = pd.parent / "receipt.json"
            self.put(
                rr,
                {
                    "status": "READY",
                    "report_path": str(rp),
                    "report_sha256": hashlib.sha256(rp.read_bytes()).hexdigest(),
                },
            )
            ap = pd.parent / "accepted.json"
            self.call("accept", "--dispatch", pd, "--report", rp, "--receipt", rr, "--output", ap)
            d["preflight_acceptance"] = {
                "path": str(ap),
                "sha256": hashlib.sha256(ap.read_bytes()).hexdigest(),
            }
            sync_path = Path(d["sync_result"])
            sync_intent = json.loads((sync_path.parent / "intent.json").read_text())
            sync_intent["execution_plan_source"] = execution_plan.selected(
                str(self.primary), "test"
            )
            self.put(sync_path.parent / "intent.json", sync_intent)
            sync_result = json.loads(sync_path.read_text())
            sync_result["intent_sha256"] = evidence.digest(sync_path.parent / "intent.json")
            self.put(sync_path, sync_result)
        result = self.call("prepare", role, "--input", self.put(self.root / "input.json", d))
        self.dispatch = Path(result["dispatch_path"])
        self.d = json.loads(self.dispatch.read_text())
        launch = {"fork_turns": "none", "required": True}
        self.assertEqual(result["launch_context"], launch)
        self.assertEqual(self.d["launch_context"], launch)
        return result

    def final_report(self):
        r = phase_fixture.PhaseValidatorTests().finalizer()
        r.update(
            parent_id="test",
            expected_children=["test-1"],
            reviewed_main=self.h.base,
            start_head=self.h.head,
            head_commit=self.h.head,
        )
        r["workspace"].update(branch="implement/test", observed_head=self.h.head)
        r["review_rounds"] = [self.h.pair(self.h.head)]
        for v in r["verification"]:
            v["head_commit"] = self.h.head
        return r

    def deliver(self, report):
        if self.d["role"] == "executor" and "stage" not in report:
            # 普通批处理 executor 报告没有单票 stage 身份。
            for key in ("stage", "models", "prior_reviews"):
                self.d.pop(key, None)
            self.put(self.dispatch, self.d)
        self.report = Path(self.d["report_path"])
        self.put(self.report, report)
        self.receipt = self.report.parent / "receipt.json"
        self.put(
            self.receipt,
            {
                "status": report["status"],
                "report_path": str(self.report),
                "report_sha256": hashlib.sha256(self.report.read_bytes()).hexdigest(),
            },
        )

    def accept(self, ok=True):
        self.counter += 1
        self.acceptance = self.dispatch.parent / f"acceptance-{self.counter}.json"
        extra = []
        if (
            self.d.get("workflow_contract_version") == workflow_contract.VERSION
            and self.d.get("role") == "finalizer"
            and self.d.get("attempt_id")
        ) or self.d.get("preflight_acceptance"):
            from fixture_support import stop_observation

            observation = self.dispatch.parent / f"observation-{self.counter}.json"
            self.put(observation, stop_observation(self.report))
            extra = ["--observation", observation]
        return self.call(
            "accept",
            "--dispatch",
            self.dispatch,
            "--report",
            self.report,
            "--receipt",
            self.receipt,
            "--output",
            self.acceptance,
            *extra,
            ok=ok,
        )

    def ready(self):
        self.prepare("finalizer")
        self.deliver(self.final_report())
        self.accept()
        comment = self.dispatch.parent / "integration.md"
        self.call(
            "comment",
            "--acceptance",
            self.acceptance,
            "--summary",
            "批次已完成",
            "--output",
            comment,
        )
        self.put(self.root / "comments.json", [{"id": 7, "text": comment.read_text()}])
        self.merge_record = self.dispatch.parent / "merge.json"

    def merge(self, ok=True):
        return self.call(
            "merge",
            "--acceptance",
            self.acceptance,
            "--comment-id",
            "7",
            "--output",
            self.merge_record,
            ok=ok,
        )

    def test_prepare_resume_preserves_base_and_unique_evidence(self):
        first = self.prepare()
        second = self.prepare()
        self.assertNotEqual(first["dispatch_path"], second["dispatch_path"])
        self.assertEqual(self.d["base_commit"], self.h.base)
        self.assertEqual(self.h.git(self.wt, "rev-parse", "HEAD"), self.h.head)
        for p in (first["report_schema_path"], first["receipt_schema_path"]):
            self.assertIsInstance(json.loads(Path(p).read_text()), dict)

    def upstream_beads_merge(self, tamper=False):
        folder = self.primary / ".beads"
        folder.mkdir(exist_ok=True)
        (folder / "config.yaml").write_text("export: false\n")
        self.h.git(self.primary, "add", ".beads")
        self.h.git(self.primary, "commit", "-m", "main config")
        self.h.base = self.h.git(self.primary, "rev-parse", "HEAD")
        self.h.git(self.wt, "merge", "--no-commit", "--no-ff", self.h.base)
        if tamper:
            (self.wt / ".beads/config.yaml").write_text("export: true\n")
            self.h.git(self.wt, "add", ".beads")
        self.h.git(self.wt, "commit", "-m", "merge main")
        self.h.head = self.h.git(self.wt, "rev-parse", "HEAD")


if __name__ == "__main__":
    unittest.main()
