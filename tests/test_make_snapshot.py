"""scripts/make_snapshot.py 的行为测试。"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "scripts" / "init_project.py"
SNAPSHOT = ROOT / "scripts" / "make_snapshot.py"
CHECK = ROOT / "scripts" / "check_task.py"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def field(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


class MakeSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)
        subprocess.run(
            ["git", "init", "-q", str(self.project)],
            check=True,
            capture_output=True,
        )
        init = subprocess.run(
            [sys.executable, str(INIT), str(self.project), "--name", "示例项目"],
            capture_output=True,
            text=True,
            check=False,
        )
        if init.returncode != 0:
            self.fail(f"初始化临时项目失败：{init.stderr}")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "baseline")

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "git",
                "-C",
                str(self.project),
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=test",
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    def head_sha(self) -> str:
        return self.git("rev-parse", "--short", "HEAD").stdout.strip()

    def run_snapshot(
        self, *arguments: str, project: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SNAPSHOT),
                str(project or self.project),
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def output(self, result: subprocess.CompletedProcess[str]) -> str:
        return result.stdout + result.stderr

    def test_work_snapshot_fills_only_machine_known_fields(self) -> None:
        result = self.run_snapshot("--kind", "work", "--task", "TASK-001")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        target = self.project / "docs/tasks/TASK-001-work-snapshot.md"
        self.assertTrue(target.is_file(), output)
        text = target.read_text(encoding="utf-8")
        self.assertEqual(field(text, "type"), "work-snapshot")
        self.assertEqual(unquote(field(text, "id")), "WS-TASK-001")
        self.assertEqual(field(text, "document_status"), "草稿")
        self.assertEqual(field(text, "task_status"), "进行中")
        self.assertEqual(unquote(field(text, "owner")), "待填写")
        self.assertIn('related_tasks: ["TASK-001"]', text)
        self.assertFalse(field(text, "updated_at") == "")
        self.assertIn(self.head_sha(), text)
        self.assertIn("未提交改动：无。", text)
        self.assertIn("快照时间：", text)
        self.assertNotIn("document_status: 现行", text)
        self.assertNotIn("警告：", output)
        self.assertIn("- 已完成：待填写。", text)
        self.assertIn("- 已验证：", text)
        self.assertIn("下一步：待填写。", text)

    def test_work_snapshot_requires_task(self) -> None:
        result = self.run_snapshot("--kind", "work")

        output = self.output(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("--task", output)

    def test_work_snapshot_rejects_unsafe_task_id(self) -> None:
        result = self.run_snapshot("--kind", "work", "--task", "../evil")

        output = self.output(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("任务编号", output)

    def test_project_snapshot_has_code_revision_and_empty_verified_at(self) -> None:
        sha = self.head_sha()

        result = self.run_snapshot("--kind", "project")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        target = self.project / f"docs/snapshots/{sha}-project-snapshot.md"
        self.assertTrue(target.is_file(), output)
        text = target.read_text(encoding="utf-8")
        self.assertEqual(field(text, "type"), "project-snapshot")
        self.assertEqual(unquote(field(text, "id")), f"PS-{sha}")
        self.assertEqual(field(text, "document_status"), "草稿")
        self.assertEqual(unquote(field(text, "code_revision")), sha)
        self.assertNotEqual(unquote(field(text, "generated_at")), "")
        self.assertEqual(unquote(field(text, "verified_at")), "")
        self.assertIn(f"代码版本与分支：{sha}", text)
        self.assertIn("快照生成时间：", text)
        self.assertIn("- 已验证：待填写", text)
        self.assertIn("未提交改动：无。", text)
        self.assertNotIn("警告：", output)
        self.assertIn("保存原因", text)
        self.assertIn("待填写", text)

    def test_existing_snapshot_is_not_overwritten(self) -> None:
        first = self.run_snapshot("--kind", "work", "--task", "TASK-001")
        self.assertEqual(first.returncode, 0, self.output(first))
        target = self.project / "docs/tasks/TASK-001-work-snapshot.md"
        before = target.read_text(encoding="utf-8")

        second = self.run_snapshot("--kind", "work", "--task", "TASK-001")

        output = self.output(second)
        self.assertEqual(second.returncode, 1, output)
        self.assertIn("已存在", output)
        self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_uncommitted_changes_are_recorded(self) -> None:
        readme = self.project / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\n改动。\n", encoding="utf-8"
        )
        (self.project / "src").mkdir()
        (self.project / "src/app.py").write_text("value = 1\n", encoding="utf-8")

        result = self.run_snapshot("--kind", "work", "--task", "TASK-001")

        self.assertEqual(result.returncode, 0, self.output(result))
        text = (
            self.project / "docs/tasks/TASK-001-work-snapshot.md"
        ).read_text(encoding="utf-8")
        self.assertIn("未提交改动：有", text)
        self.assertIn("README.md（M）", text)
        self.assertIn("src/app.py（??）", text)

    def test_uninitialized_project_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(
                ["git", "init", "-q", str(target)],
                check=True,
                capture_output=True,
            )

            result = self.run_snapshot(
                "--kind", "project", project=target
            )

        output = self.output(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("未初始化", output)

    def test_not_git_root_exits_2(self) -> None:
        result = self.run_snapshot(
            "--kind", "project", project=self.project / "docs"
        )

        output = self.output(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("Git 根目录", output)

    def test_generated_snapshot_passes_full_check(self) -> None:
        work = self.run_snapshot("--kind", "work", "--task", "TASK-001")
        self.assertEqual(work.returncode, 0, self.output(work))

        result = subprocess.run(
            [sys.executable, str(CHECK), str(self.project)],
            capture_output=True,
            text=True,
            check=False,
        )

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("错误：", output)


    def test_template_drift_still_writes_draft_status(self) -> None:
        template = self.project / "docs/_templates/work-snapshot.md"
        content = template.read_text(encoding="utf-8")
        content = content.replace("document_status: 草稿", "document_status: 现行")
        content = content.replace("task_status: 进行中", "task_status: 已结束")
        content = content.replace("type: work-snapshot", "type: task-change")
        template.write_text(content, encoding="utf-8")

        result = self.run_snapshot("--kind", "work", "--task", "TASK-001")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("警告：", output)
        self.assertIn("草稿", output)
        self.assertIn("现行", output)
        self.assertIn("task_status", output)
        self.assertIn("模板副本的 type", output)
        text = (
            self.project / "docs/tasks/TASK-001-work-snapshot.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(field(text, "document_status"), "草稿")
        self.assertEqual(field(text, "task_status"), "进行中")
        self.assertEqual(field(text, "type"), "work-snapshot")
        self.assertNotIn("document_status: 现行", text)

    def test_project_template_status_drift_still_writes_draft(self) -> None:
        template = self.project / "docs/_templates/project-snapshot.md"
        content = template.read_text(encoding="utf-8")
        content = content.replace("document_status: 草稿", "document_status: 现行")
        template.write_text(content, encoding="utf-8")

        result = self.run_snapshot("--kind", "project")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("警告：", output)
        self.assertIn("现行", output)
        sha = self.head_sha()
        text = (
            self.project / f"docs/snapshots/{sha}-project-snapshot.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(field(text, "document_status"), "草稿")

    def test_broken_empty_placeholder_exits_2(self) -> None:
        template = self.project / "docs/_templates/project-snapshot.md"
        content = template.read_text(encoding="utf-8")
        content = content.replace('code_revision: ""', "code_revision: ''")
        template.write_text(content, encoding="utf-8")

        result = self.run_snapshot("--kind", "project")

        output = self.output(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("模板", output)
        self.assertFalse(
            list((self.project / "docs/snapshots").glob("*-project-snapshot.md"))
        )

    def test_missing_frontmatter_field_exits_2(self) -> None:
        template = self.project / "docs/_templates/work-snapshot.md"
        content = template.read_text(encoding="utf-8")
        content = content.replace("related_tasks: []\n", "")
        template.write_text(content, encoding="utf-8")

        result = self.run_snapshot("--kind", "work", "--task", "TASK-001")

        output = self.output(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("related_tasks", output)

    def test_unreplaced_body_placeholder_exits_2(self) -> None:
        template = self.project / "docs/_templates/work-snapshot.md"
        content = template.read_text(encoding="utf-8")
        content = content.replace("# {{TITLE}}", "# {{ TITLE }}")
        template.write_text(content, encoding="utf-8")

        result = self.run_snapshot("--kind", "work", "--task", "TASK-001")

        output = self.output(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("占位符", output)

    def test_project_snapshot_does_not_count_itself_as_change(self) -> None:
        readme = self.project / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\n改动。\n", encoding="utf-8"
        )
        sha = self.head_sha()

        result = self.run_snapshot("--kind", "project")

        self.assertEqual(result.returncode, 0, self.output(result))
        target = self.project / f"docs/snapshots/{sha}-project-snapshot.md"
        text = target.read_text(encoding="utf-8")
        line = next(
            item for item in text.splitlines() if item.startswith("- 未提交改动：")
        )
        self.assertIn("README.md", line)
        self.assertNotIn(f"{sha}-project-snapshot.md", line)

if __name__ == "__main__":
    unittest.main()
