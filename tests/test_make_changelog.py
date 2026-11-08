"""scripts/make_changelog.py 的行为测试。"""

from __future__ import annotations

from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "scripts" / "init_project.py"
CHANGELOG_TOOL = ROOT / "scripts" / "make_changelog.py"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

MERGED_OWNER = "李四，2026-11-07。"

CHANGE_LINES = [
    "- 改动：修复登录后跳到错误页面的问题。",
    "- 原因：会话过期时重定向地址算错。",
    "- 关联需求、缺陷或外部 issue：BUG-001。",
]
VERIFY_ROWS = [
    "| 命令或操作 | 结果 | 代码版本 | 时间 | 未运行原因与影响 |",
    "| --- | --- | --- | --- | --- |",
    "| pytest tests/test_login.py | 通过 | abc1234 | 2026-11-07 | 无 |",
]


def task_document(
    task_id: str,
    title: str,
    *,
    owner: str = MERGED_OWNER,
) -> str:
    return "\n".join(
        [
            "---",
            f'id: "{task_id}"',
            "type: task-change",
            f'title: "{title}"',
            "document_status: 现行",
            'owner: "张三"',
            'updated_at: "2026-11-07"',
            "related_tasks: []",
            'replaces: ""',
            "---",
            "",
            f"# {title}",
            "",
            "## 改动与原因",
            "",
            *CHANGE_LINES,
            "",
            "## 文档影响判断",
            "",
            "| 文档类型或具体文件 | 结论（已更新／检查后无需更新） | 链接或无需更新的理由 |",
            "| --- | --- | --- |",
            "| 接口 | 已更新 | docs/interfaces/login.md |",
            "",
            "## 验证",
            "",
            *VERIFY_ROWS,
            "",
            "## 合并检查",
            "",
            "- 相关文档冲突：无。",
            "- 未完成的必要验证及后续任务：无。",
            f"- 合并负责人及确认时间：{owner}",
            "",
        ]
    )


class MakeChangelogTest(unittest.TestCase):
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

    def write_doc(self, relative: str, content: str) -> Path:
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def changelog_bytes(self) -> bytes:
        return (self.project / "docs/CHANGELOG.md").read_bytes()

    def run_tool(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHANGELOG_TOOL), str(self.project), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_merged_candidate_is_included_verbatim(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md", task_document("TASK-001", "登录修复")
        )

        result = self.run_tool()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        for expected in (
            "TASK-001",
            "登录修复",
            "docs/tasks/TASK-001.md",
            *CHANGE_LINES,
            VERIFY_ROWS[2],
        ):
            self.assertIn(expected, result.stdout)
        self.assertIn("候选 1 条", result.stderr)

    def test_unmerged_task_is_skipped_with_reason(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-002.md",
            task_document("TASK-002", "未确认", owner="待填写。"),
        )

        result = self.run_tool()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("TASK-002", result.stdout)
        self.assertIn("跳过", result.stderr)
        self.assertIn("合并负责人", result.stderr)
        self.assertIn("候选 0 条", result.stderr)

    def test_task_already_in_changelog_is_skipped(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-003.md", task_document("TASK-003", "已收录")
        )
        changelog = self.project / "docs/CHANGELOG.md"
        changelog.write_text(
            changelog.read_text(encoding="utf-8") + "\n- TASK-003 登录修复\n",
            encoding="utf-8",
        )

        result = self.run_tool()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("TASK-003", result.stdout)
        self.assertIn("已在 docs/CHANGELOG.md", result.stderr)

    def test_task_id_boundary_is_respected(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-0010.md", task_document("TASK-0010", "边界任务")
        )
        changelog = self.project / "docs/CHANGELOG.md"
        changelog.write_text(
            changelog.read_text(encoding="utf-8") + "\n- TASK-001 登录修复\n",
            encoding="utf-8",
        )

        result = self.run_tool()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("TASK-0010", result.stdout)

    def test_changelog_is_never_modified(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md", task_document("TASK-001", "登录修复")
        )
        before = self.changelog_bytes()

        result = self.run_tool()

        self.assertEqual(result.returncode, 0, self.stdout_stderr(result))
        self.assertEqual(self.changelog_bytes(), before)

    def stdout_stderr(self, result: subprocess.CompletedProcess[str]) -> str:
        return result.stdout + result.stderr

    def test_output_file_written_and_existing_file_not_overwritten(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md", task_document("TASK-001", "登录修复")
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "candidates.md"

            first = self.run_tool("--output", str(target))

            self.assertEqual(first.returncode, 0, self.stdout_stderr(first))
            self.assertTrue(target.is_file())
            content = target.read_text(encoding="utf-8")
            self.assertIn("TASK-001", content)
            self.assertIn("改动原文", content)

            second = self.run_tool("--output", str(target))

            self.assertEqual(second.returncode, 1, self.stdout_stderr(second))
            self.assertIn("已存在", self.stdout_stderr(second))
            self.assertEqual(target.read_text(encoding="utf-8"), content)

    def test_output_to_changelog_is_refused(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md", task_document("TASK-001", "登录修复")
        )
        before = self.changelog_bytes()

        result = self.run_tool(
            "--output", str(self.project / "docs/CHANGELOG.md")
        )

        output = self.stdout_stderr(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("不允许写入", output)
        self.assertEqual(self.changelog_bytes(), before)

    def test_uninitialized_project_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(
                ["git", "init", "-q", str(target)],
                check=True,
                capture_output=True,
            )

            result = subprocess.run(
                [sys.executable, str(CHANGELOG_TOOL), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )

        output = self.stdout_stderr(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("未初始化", output)

    def test_no_candidates_message(self) -> None:
        result = self.run_tool()

        output = self.stdout_stderr(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("没有符合条件的新候选", result.stdout)

    def test_drafts_and_underscore_files_are_skipped(self) -> None:
        self.write_doc(
            "docs/tasks/drafts/TASK-004.md",
            task_document("TASK-004", "草稿任务"),
        )
        self.write_doc(
            "docs/tasks/_TASK-005.md", task_document("TASK-005", "下划线任务")
        )

        result = self.run_tool()

        output = self.stdout_stderr(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("TASK-004", result.stdout)
        self.assertNotIn("TASK-005", result.stdout)
        self.assertIn("没有符合条件的新候选", result.stdout)


if __name__ == "__main__":
    unittest.main()
