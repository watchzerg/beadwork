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

    def test_controller_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for name, raw in (
            ("duplicate", '{"repository_root":"x","repository_root":"y"}'),
            ("nonfinite", '{"repository_root":NaN}'),
        ):
            with self.subTest(name=name):
                path = self.root / (name + ".json")
                path.write_text(raw)
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(SCRIPT),
                        "controller",
                        "prepare",
                        "preflight",
                        "--input",
                        str(path),
                    ],
                    cwd=self.root,
                    env=self.env,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "重复 JSON key" if name == "duplicate" else "无效 JSON 数值", result.stderr
                )

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
            "required_boundary_gates": ["gate-browser"],
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
            plan["boundary_gates"] = d["required_boundary_gates"]
            pr.update(
                parent={"id": "test", "status": "open"},
                expected_children=[d["ticket_id"]],
                execution_plan=value,
                tickets=[{"id": d["ticket_id"], "status": "open", "test_plan": plan}],
                linked_spec=d["linked_spec"],
                boundary_gates=d["required_boundary_gates"],
                gate_plan={
                    "core": "gate-core",
                    "full": ["gate-core", *d["required_boundary_gates"]],
                    "defer_to_final": [],
                },
                workspace={
                    "primary_worktree": str(self.primary),
                    "implementation_worktree": str(self.wt),
                    "branch": "implement/test",
                    "observed_head": self.h.head,
                    "clean": True,
                },
            )
            gate_plan_path = pd.parent / "gate-plan.json"
            self.put(gate_plan_path, pr["gate_plan"])
            pr["gate_plan_source"] = evidence.binding(gate_plan_path)
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
            sync_result["gate_plan"] = pr["gate_plan"]
            sync_result["recipes"] = [
                "check-toolchain",
                "install",
                "typecheck",
                "test",
                "gate-plan",
                "gate-core",
                "gate-full",
                "env-facts",
                "fmt",
                *d["required_boundary_gates"],
            ]
            command = sync_path.parent / "command-gate-plan"
            command.mkdir()
            argv = ["just", "--one", "--", "gate-plan"]
            self.put(command / "started.json", {"argv": argv, "head": sync_result["head"]})
            (command / "output.log").write_text("")
            (command / "stdout.log").write_text(json.dumps(pr["gate_plan"]))
            self.put(
                command / "result.json",
                {
                    "argv": argv,
                    "started_sha256": evidence.digest(command / "started.json"),
                    "exit_code": 0,
                    "interrupted": False,
                    "process_group_gone": True,
                    "recorder_error": None,
                    "log_sha256": evidence.digest(command / "output.log"),
                    "stdout": evidence.binding(command / "stdout.log"),
                },
            )
            sync_result["commands"] = [evidence.binding(command / "result.json")]
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
            self.d.get("workflow_contract_version") == 4
            and self.d.get("role") == "finalizer"
            and self.d.get("attempt_id")
        ) or self.d.get("preflight_acceptance"):
            import handoff

            closure = handoff.close(
                str(self.dispatch),
                str(self.report),
                {
                    "task_id": "fixture-task",
                    "stopped": json.loads(self.report.read_text()).get("stopped_tasks", True),
                    "observed_at": "2026-09-16T00:00:00Z",
                    "evidence": "临时 CLI 已退出",
                    "unresolved": [],
                },
            )
            cp = self.dispatch.parent / f"closure-source-{self.counter}.json"
            self.put(cp, closure["closure_source"])
            extra = ["--closure", cp]
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

    def test_finalizer_filters_only_covered_common_gates(self):
        self.prepare(
            "finalizer",
            required_boundary_gates=[
                "gate-core",
                "gate-browser",
                "gate-full",
                "gate-postgres",
                "gate-browser",
            ],
        )
        self.assertEqual(self.d["required_boundary_gates"], ["gate-browser", "gate-postgres"])
        self.prepare("finalizer", required_boundary_gates=["gate-core", "gate-full"])
        self.assertEqual(self.d["required_boundary_gates"], [])

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

    def test_prepare_new_records_current_head(self):
        self.prepare(mode="new")
        self.assertEqual(self.d["base_commit"], self.h.head)

    def test_dispatch_schema_paths_are_consumable_from_another_directory(self):
        for role in ("preflight", "executor", "finalizer"):
            with self.subTest(role=role):
                result = self.prepare(role)
                # 接收方仅凭 dispatch 路径，在不同 cwd 读取两份 schema。
                consumer = "import json,sys;from pathlib import Path;d=json.loads(Path(sys.argv[1]).read_text());print(json.dumps([json.loads(Path(d[k]).read_text()) for k in ('report_schema_path','receipt_schema_path')]))"
                raw = subprocess.check_output(
                    [sys.executable, "-B", "-c", consumer, str(self.dispatch)],
                    cwd=self.primary,
                    env=self.env,
                    text=True,
                )
                schemas = json.loads(raw)
                self.assertEqual(len(schemas), 2)
                for key, flag, schema in zip(
                    ("report_schema_path", "receipt_schema_path"),
                    ("--schema", "--receipt-schema"),
                    schemas,
                    strict=True,
                ):
                    self.assertEqual(self.d[key], result[key])
                    arguments = (
                        ["verify", "ticket", flag]
                        if role == "executor"
                        else ["verify", "phase", flag, role]
                    )
                    expected = subprocess.check_output(
                        [sys.executable, "-B", str(SCRIPT), *arguments],
                        env=self.env,
                        text=True,
                    )
                    self.assertEqual(schema, json.loads(expected))

    def test_prepare_resume_requires_explicit_base(self):
        data = {
            "repository_root": str(self.primary),
            "parent_id": "test",
            "mode": "resume",
            "ticket_id": "test-1",
        }
        self.call(
            "prepare", "executor", "--input", self.put(self.root / "input.json", data), ok=False
        )

    def test_prepare_new_rejects_dirty_worktree(self):
        (self.wt / "behavior.txt").write_text("unfinished")
        data = {
            "repository_root": str(self.primary),
            "parent_id": "test",
            "mode": "new",
            "ticket_id": "test-1",
        }
        self.call(
            "prepare", "executor", "--input", self.put(self.root / "input.json", data), ok=False
        )
        self.assertEqual((self.wt / "behavior.txt").read_text(), "unfinished")

    def test_executor_accept_and_comment_preserve_smell(self):
        self.prepare()
        r = self.h.report
        smell = {
            "axis": "standards",
            "kind": "smell",
            "blocking": False,
            "title": "名称建议",
            "evidence": "具体来源",
        }
        r["review"]["final"]["standards"]["findings"] = [smell]
        r["verification"] += [
            {"command": f"historic-command-{index}", "result": "已由后续结果覆盖"}
            for index in range(60)
        ]
        self.deliver(r)
        self.accept()
        output = self.dispatch.parent / "completion.md"
        result = self.call(
            "comment", "--acceptance", self.acceptance, "--summary", "功能完成", "--output", output
        )
        self.assertEqual(result["comment_source"], evidence.binding(output))
        self.assertIn(
            json.dumps(smell, ensure_ascii=False, indent=2).splitlines()[1].strip(),
            output.read_text(),
        )
        self.assertIn(self.h.base + ".." + self.h.head, output.read_text())
        self.assertNotIn("historic-command", output.read_text())
        self.assertNotIn("验证记录：", output.read_text())
        self.assertLess(output.stat().st_size, 10_000)
        metadata = result["metadata"]
        self.assertEqual(metadata["acceptance_source"], evidence.binding(self.acceptance))
        self.assertEqual(metadata["report_source"], evidence.binding(self.report))

    def test_receipt_tamper_rejected(self):
        self.prepare()
        self.deliver(self.h.report)
        r = json.loads(self.receipt.read_text())
        r["report_sha256"] = "0" * 64
        self.put(self.receipt, r)
        self.accept(ok=False)
        self.assertFalse(self.acceptance.exists())

    def test_report_outside_dispatch_rejected(self):
        self.prepare()
        self.deliver(self.h.report)
        self.report = Path(self.put(self.root / "outside.json", self.h.report))
        self.accept(ok=False)

    def test_non_done_null_head_and_dirty_resume(self):
        self.prepare()
        r = dict(
            self.h.report,
            status="NEEDS_CONTEXT",
            head_commit=None,
            test_plan=None,
            review=None,
            requested_context=["缺少事实"],
            acceptance=[],
        )
        (self.wt / "behavior.txt").write_text("unfinished")
        self.deliver(r)
        self.accept()
        self.call(
            "comment",
            "--acceptance",
            self.acceptance,
            "--summary",
            "不能完成",
            "--output",
            self.root / "bad.md",
            ok=False,
        )

    def test_removed_push_entrypoint_cannot_publish(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "controller", "push", "--input", "unused.json"],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.h.git(self.primary, "rev-parse", "HEAD"), self.h.base)
        self.assertTrue(self.wt.exists())

    def test_acceptance_output_outside_evidence_rejected(self):
        self.prepare()
        self.deliver(self.h.report)
        self.call(
            "accept",
            "--dispatch",
            self.dispatch,
            "--report",
            self.report,
            "--receipt",
            self.receipt,
            "--output",
            self.root / "outside.json",
            ok=False,
        )
        self.assertFalse((self.root / "outside.json").exists())

    def test_accepted_report_change_blocks_comment(self):
        self.prepare()
        self.deliver(self.h.report)
        self.accept()
        self.report.write_text(self.report.read_text() + "\n")
        self.call(
            "comment",
            "--acceptance",
            self.acceptance,
            "--summary",
            "摘要",
            "--output",
            self.dispatch.parent / "bad.md",
            ok=False,
        )

    def test_preflight_prepare_and_accept(self):
        self.prepare("preflight")
        r = phase_fixture.PhaseValidatorTests().preflight("BLOCKED")
        self.deliver(r)
        self.accept()

    def test_dirty_primary_prepare_ignores_removed_snapshot_input(self):
        (self.primary / "manual.txt").write_text("手工编辑")
        self.prepare(primary_snapshot_path="/missing/old-snapshot")
        self.assertNotIn("primary_snapshot_path", self.d)
        self.assertEqual(self.d["base_commit"], self.h.base)
        self.assertEqual(self.d["stage"], 0)
        self.deliver(self.h.report)
        self.accept()
        comment = self.dispatch.parent / "completion.md"
        self.call(
            "comment", "--acceptance", self.acceptance, "--summary", "完成", "--output", comment
        )
        self.assertTrue(comment.exists())

    def test_finalizer_uses_supplied_main_after_primary_moves(self):
        (self.primary / "later.txt").write_text("后续提交")
        self.h.git(self.primary, "add", "later.txt")
        self.h.git(self.primary, "commit", "-m", "later")
        self.prepare("finalizer", reviewed_main=self.h.base)
        self.assertEqual(self.d["reviewed_main"], self.h.base)
        data = json.loads((self.root / "input.json").read_text())
        data["reviewed_main"] = self.h.git(self.primary, "rev-parse", "HEAD")
        self.call(
            "prepare", "finalizer", "--input", self.put(self.root / "invalid.json", data), ok=False
        )
        del data["reviewed_main"]
        self.call(
            "prepare", "finalizer", "--input", self.put(self.root / "missing.json", data), ok=False
        )

    def test_update_main_boundary_and_fetch_fallback(self):
        self.h.git(self.primary, "update-ref", "refs/remotes/origin/main", self.h.head)
        dirty = self.primary / "manual.txt"
        dirty.write_text("手工编辑")
        self.call("update-main", "--repository-root", self.primary, ok=False)
        self.assertEqual(self.h.git(self.primary, "rev-parse", "HEAD"), self.h.base)
        dirty.unlink()
        marker = self.primary / ".git" / "CHERRY_PICK_HEAD"
        marker.write_text(self.h.head)
        self.call("update-main", "--repository-root", self.primary, ok=False)
        marker.unlink()
        result = self.call("update-main", "--repository-root", self.primary)
        self.assertTrue(result["fetch_failed"])
        self.assertEqual(result["main_commit"], self.h.head)

    def test_update_main_fetch_local_remote_and_non_ff(self):
        self.h.git(self.primary, "remote", "add", "origin", str(self.primary))
        result = self.call("update-main", "--repository-root", self.primary)
        self.assertFalse(result["fetch_failed"])
        self.h.git(self.primary, "remote", "remove", "origin")
        self.h.git(self.primary, "update-ref", "refs/remotes/origin/main", self.h.head)
        (self.primary / "later.txt").write_text("手工提交")
        self.h.git(self.primary, "add", ".")
        self.h.git(self.primary, "commit", "-m", "later")
        before = self.h.git(self.primary, "rev-parse", "HEAD")
        self.call("update-main", "--repository-root", self.primary, ok=False)
        self.assertEqual(self.h.git(self.primary, "rev-parse", "HEAD"), before)

    def test_update_main_missing_remote_ref_fails(self):
        self.call("update-main", "--repository-root", self.primary, ok=False)
        self.assertEqual(self.h.git(self.primary, "rev-parse", "HEAD"), self.h.base)


if __name__ == "__main__":
    unittest.main()
