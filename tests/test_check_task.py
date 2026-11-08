"""scripts/check_task.py 的行为测试。"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "scripts" / "init_project.py"
CHECK = ROOT / "scripts" / "check_task.py"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

INTERFACE_DOC = """---
id: "IFACE-001"
type: interface
title: "登录接口"
document_status: 现行
owner: "张三"
updated_at: "2026-10-26"
verified_at: "2026-10-26"
related_tasks: []
replaces: ""
---

# 登录接口

使用方为客户端。字段说明待补充。
"""

def typed_doc(doc_type: str, doc_id: str, title: str) -> str:
    return (
        "---\n"
        f'id: "{doc_id}"\n'
        f"type: {doc_type}\n"
        f'title: "{title}"\n'
        "document_status: 现行\n"
        'owner: "张三"\n'
        'updated_at: "2026-10-26"\n'
        "related_tasks: []\n"
        'replaces: ""\n'
        "---\n\n"
        f"# {title}\n"
    )


REQUIREMENT_DOC = """---
id: "REQ-001"
type: requirement
title: "登录需求"
document_status: 现行
owner: "张三"
updated_at: "2026-10-26"
related_tasks: ["TASK-001"]
replaces: ""
---

# 登录需求

要解决的问题：登录失败。
"""


def task_document(
    task_id: str = "TASK-001",
    *,
    title: str = "实现登录修复",
    document_status: str = "现行",
    owner: str | None = "张三",
    updated_at: str = "2026-10-26",
    related_tasks: tuple[str, ...] = (),
    replaces: str = "",
    impact_rows: list[str] | None = None,
    verification_rows: list[str] | None = None,
    merge_lines: list[str] | None = None,
) -> str:
    if impact_rows is None:
        impact_rows = [
            "| docs/interfaces/auth.md | 已更新 | [接口文档](../interfaces/auth.md) |",
            "| 需求 | 检查后无需更新 | 行为未变 |",
        ]
    if verification_rows is None:
        verification_rows = [
            "| python3 -m unittest discover -s tests | 通过 | abc1234 | 2026-10-26 | 无 |",
        ]
    if merge_lines is None:
        merge_lines = [
            "- 相关文档冲突：无。",
            "- 未完成的必要验证及后续任务：无。",
            "- 合并负责人及确认时间：李四，2026-10-26。",
        ]
    related = (
        "[" + ", ".join(f'"{value}"' for value in related_tasks) + "]"
        if related_tasks
        else "[]"
    )
    header = [
        "---",
        f'id: "{task_id}"',
        "type: task-change",
        f'title: "{title}"',
        f"document_status: {document_status}",
    ]
    if owner is not None:
        header.append(f'owner: "{owner}"')
    header += [
        f'updated_at: "{updated_at}"',
        f"related_tasks: {related}",
        f'replaces: "{replaces}"',
        "---",
        "",
    ]
    body = [
        f"# {title}",
        "",
        "## 改动与原因",
        "",
        "- 改动：修复登录接口。",
        "- 原因：登录失败。",
        "- 关联需求、缺陷或外部 issue：BUG-001。",
        "",
        "## 文档影响判断",
        "",
        "| 文档类型或具体文件 | 结论（已更新／检查后无需更新） | 链接或无需更新的理由 |",
        "| --- | --- | --- |",
        *impact_rows,
        "",
        "## 验证",
        "",
        "| 命令或操作 | 结果 | 代码版本 | 时间 | 未运行原因与影响 |",
        "| --- | --- | --- | --- | --- |",
        *verification_rows,
        "",
        "## 合并检查",
        "",
        *merge_lines,
    ]
    return "\n".join(header + body) + "\n"


class CheckTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)
        subprocess.run(
            ["git", "init", "-q", str(self.project)], check=True, capture_output=True
        )
        init = subprocess.run(
            [sys.executable, str(INIT), str(self.project), "--name", "示例项目"],
            capture_output=True,
            text=True,
            check=False,
        )
        if init.returncode != 0:
            self.fail(f"初始化临时项目失败：{init.stderr}")
        self.write_doc("docs/interfaces/auth.md", INTERFACE_DOC)

    def write_doc(self, relative: str, content: str) -> Path:
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_check(
        self, project: Path | None = None, task_id: str = "TASK-001"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECK), str(project or self.project), task_id],
            capture_output=True,
            text=True,
            check=False,
        )

    def run_task(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECK), str(self.project), "TASK-001", *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def run_full(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECK), str(self.project), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def commit_all(self, message: str = "checkpoint") -> None:
        for arguments in (
            ["add", "-A"],
            [
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=test",
                "commit",
                "-q",
                "-m",
                message,
            ],
        ):
            subprocess.run(
                ["git", "-C", str(self.project), *arguments],
                check=True,
                capture_output=True,
            )

    def output(self, result: subprocess.CompletedProcess[str]) -> str:
        return result.stdout + result.stderr

    def test_missing_task_record_is_error(self) -> None:
        result = self.run_check()
        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("错误：", output)
        self.assertIn("TASK-001", output)
        self.assertIn("任务变更记录", output)

    def test_complete_task_passes(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("通过：", output)
        self.assertNotIn("错误：", output)

    def test_invalid_document_status_is_error(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md", task_document(document_status="生效中")
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("document_status", output)

    def test_missing_required_field_is_error(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document(owner=None))

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("owner", output)

    def test_bad_local_link_is_error(self) -> None:
        rows = [
            "| docs/interfaces/auth.md | 已更新 | [接口文档](../interfaces/missing.md) |",
            "| 需求 | 检查后无需更新 | 行为未变 |",
        ]
        self.write_doc("docs/tasks/TASK-001.md", task_document(impact_rows=rows))

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("链接", output)
        self.assertIn("missing.md", output)

    def test_duplicate_id_is_error(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        self.write_doc("docs/tasks/TASK-001-copy.md", task_document())

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("重复", output)

    def test_newer_system_version_only_warns(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        system = self.project / "docs/system.yml"
        content = system.read_text(encoding="utf-8")
        content = re.sub(
            r'system_version:\s*".*?"',
            'system_version: "9.9.9"  # 待升级',
            content,
            count=1,
        )
        system.write_text(content, encoding="utf-8")

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("警告：", output)
        self.assertIn("upgrade_templates.py", output)
        self.assertIn("通过：", output)

    def test_project_that_is_not_git_root_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_check(project=Path(directory))

        self.assertEqual(result.returncode, 2, self.output(result))
        self.assertIn("错误：", self.output(result))

    def test_missing_environment_file_exits_2(self) -> None:
        (self.project / "docs/system.yml").unlink()

        result = self.run_check()

        self.assertEqual(result.returncode, 2, self.output(result))
        self.assertIn("错误：", self.output(result))

    def test_invalid_impact_conclusion_is_error(self) -> None:
        rows = [
            "| 接口文档 | 需要更新 | 待核实 |",
            "| 需求 | 检查后无需更新 | 行为未变 |",
        ]
        self.write_doc("docs/tasks/TASK-001.md", task_document(impact_rows=rows))

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("结论", output)

    def test_impact_table_without_rows_is_error(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document(impact_rows=[]))

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("无数据行", output)

    def test_verification_table_with_only_placeholders_is_error(self) -> None:
        rows = ["| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |"]
        self.write_doc(
            "docs/tasks/TASK-001.md", task_document(verification_rows=rows)
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("无数据行", output)

    def test_replaced_document_requires_existing_target(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(document_status="已取代", replaces=""),
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("replaces", output)

    def test_replaced_document_with_existing_target_passes(self) -> None:
        self.write_doc("docs/requirements/REQ-001.md", REQUIREMENT_DOC)
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(
                document_status="已取代", replaces="../requirements/REQ-001.md"
            ),
        )

        result = self.run_check()

        self.assertEqual(result.returncode, 0, self.output(result))

    def test_untested_verification_without_reason_warns(self) -> None:
        rows = ["| 集成测试 | 待运行 | 待填写 | 2026-10-26 |  |"]
        self.write_doc(
            "docs/tasks/TASK-001.md", task_document(verification_rows=rows)
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("警告：", output)
        self.assertIn("待运行", output)

    def test_empty_merge_check_section_warns(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document(merge_lines=[]))

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("警告：", output)
        self.assertIn("合并检查", output)

    def test_custom_document_type_warns(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        self.write_doc(
            "docs/modules/login.md",
            """---
id: "MODULE-001"
type: module-doc
title: "登录模块"
document_status: 现行
owner: "张三"
updated_at: "2026-10-26"
---

# 登录模块

模块说明。
""",
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("警告：", output)
        self.assertIn("自定义文档类型", output)

    def test_related_document_is_also_checked(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        self.write_doc(
            "docs/requirements/REQ-001.md",
            REQUIREMENT_DOC.replace("document_status: 现行", "document_status: 生效中"),
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("REQ-001.md", output)
        self.assertIn("document_status", output)

    def test_drafts_and_template_copies_are_ignored(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        self.write_doc(
            "docs/tasks/drafts/notes.md",
            task_document(),
        )
        self.write_doc(
            "docs/_templates/extra.md",
            "---\ntype: module-doc\n---\n\n草稿内容。\n",
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("重复", output)
        self.assertNotIn("自定义文档类型", output)

    def test_valid_document_map_does_not_warn(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        self.write_doc(
            "docs/document-map.yml",
            """areas:
  - path: src/login
    docs:
      - docs/interfaces/auth.md  # 登录接口文档
""",
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("document-map", output)

    def test_document_map_missing_document_warns_without_failure(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        self.write_doc(
            "docs/document-map.yml",
            """areas:
  - path: src/login
    docs:
      - docs/interfaces/missing.md
""",
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("document-map", output)
        self.assertIn("missing.md", output)

    def test_unparseable_document_map_warns_and_skips(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        self.write_doc(
            "docs/document-map.yml",
            "areas: {path: src/login, docs: [docs/interfaces/missing.md]}\n",
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("无法解析", output)
        self.assertNotIn("可能影响文档", output)
        self.assertNotIn("未登记", output)
        self.assertNotIn("错误：", output)

    def test_missing_task_section_is_error(self) -> None:
        content = task_document().replace("## 合并检查\n", "")
        self.write_doc("docs/tasks/TASK-001.md", content)

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("缺少", output)
        self.assertIn("合并检查", output)

    def test_usage_missing_project_exits_2(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECK)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, self.output(result))
        self.assertIn("错误：", self.output(result))

    def test_empty_task_id_exits_2(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECK), str(self.project), "  "],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, self.output(result))
        self.assertIn("任务编号不能为空", self.output(result))

    def test_full_scan_passes_on_fresh_project(self) -> None:
        self.assertTrue((self.project / "docs/index.md").exists())

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("全部文档", output)
        self.assertNotIn("错误：", output)

    def test_full_scan_with_valid_task_record_passes(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())

        result = self.run_full()

        self.assertEqual(result.returncode, 0, self.output(result))

    def test_full_scan_reports_missing_frontmatter(self) -> None:
        self.write_doc("docs/modules/notes.md", "# 随手记\n\n临时内容。\n")

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("frontmatter", output)
        self.assertIn("notes.md", output)

    def test_task_scan_reports_missing_frontmatter(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        self.write_doc("docs/modules/notes.md", "# 随手记\n")

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("frontmatter", output)

    def test_unrelated_document_missing_field_is_error(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document())
        self.write_doc(
            "docs/bugs/BUG-002.md",
            """---
id: "BUG-002"
type: bug
title: "登录失败"
document_status: 现行
updated_at: "2026-10-26"
---

# 登录失败
""",
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("BUG-002", output)
        self.assertIn("owner", output)

    def test_full_scan_reports_unrelated_document_missing_field(self) -> None:
        self.write_doc(
            "docs/bugs/BUG-002.md",
            """---
id: "BUG-002"
type: bug
title: "登录失败"
document_status: 现行
updated_at: "2026-10-26"
---

# 登录失败
""",
        )

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("owner", output)


    def test_verification_result_placeholder_is_error(self) -> None:
        rows = ["| 集成测试 | 待填写 | abc1234 | 2026-10-26 |  |"]
        self.write_doc("docs/tasks/TASK-001.md", task_document(verification_rows=rows))

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("验证", output)
        self.assertIn("待填写", output)

    def test_verification_columns_are_read_by_header(self) -> None:
        content = task_document().replace(
            "| 命令或操作 | 结果 | 代码版本 | 时间 | 未运行原因与影响 |",
            "| 命令或操作 | 代码版本 | 结果 | 时间 | 未运行原因与影响 |",
        ).replace(
            "| python3 -m unittest discover -s tests | 通过 | abc1234 | 2026-10-26 | 无 |",
            "| python3 -m unittest discover -s tests | abc1234 | 待填写 | 2026-10-26 | 无 |",
        )
        self.write_doc("docs/tasks/TASK-001.md", content)

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("待填写", output)

    def test_verification_table_without_expected_header_is_error(self) -> None:
        content = task_document().replace(
            "| 命令或操作 | 结果 | 代码版本 | 时间 | 未运行原因与影响 |",
            "| 命令或操作 | 结论 | 代码版本 | 时间 | 未运行原因与影响 |",
        )
        self.write_doc("docs/tasks/TASK-001.md", content)

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("表头", output)
        self.assertIn("结果", output)

    def test_impact_table_columns_are_read_by_header(self) -> None:
        content = task_document(
            impact_rows=[
                "| docs/interfaces/auth.md | [接口文档](../interfaces/auth.md) | 待填写 |",
            ]
        ).replace(
            "| 文档类型或具体文件 | 结论（已更新／检查后无需更新） | 链接或无需更新的理由 |",
            "| 文档类型或具体文件 | 链接或无需更新的理由 | 结论（已更新／检查后无需更新） |",
        )
        self.write_doc("docs/tasks/TASK-001.md", content)

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("待填写", output)

    def test_impact_table_without_expected_header_is_error(self) -> None:
        content = task_document().replace(
            "| 文档类型或具体文件 | 结论（已更新／检查后无需更新） | 链接或无需更新的理由 |",
            "| 文档类型或具体文件 | 判断结果 | 链接或无需更新的理由 |",
        )
        self.write_doc("docs/tasks/TASK-001.md", content)

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("表头", output)
        self.assertIn("结论", output)

    def test_required_field_empty_string_is_error(self) -> None:
        self.write_doc("docs/tasks/TASK-001.md", task_document(owner=""))

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("owner", output)
        self.assertIn("空", output)



    def test_changed_from_hints_directory_area(self) -> None:
        tracked = self.project / "src/login/app.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("value = 1\n", encoding="utf-8")
        self.write_doc(
            "docs/document-map.yml",
            "areas:\n  - path: src/login\n    docs:\n      - docs/interfaces/auth.md\n",
        )
        self.commit_all()
        tracked.write_text("value = 2\n", encoding="utf-8")

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("可能影响文档", output)
        self.assertIn("docs/interfaces/auth.md", output)
        self.assertIn("src/login", output)

    def test_changed_from_hints_glob_area(self) -> None:
        tracked = self.project / "src/core/logic.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("value = 1\n", encoding="utf-8")
        self.write_doc(
            "docs/document-map.yml",
            "areas:\n  - path: \"src/**/*.py\"\n    docs:\n      - docs/interfaces/auth.md\n",
        )
        self.commit_all()
        tracked.write_text("value = 2\n", encoding="utf-8")

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("可能影响文档", output)
        self.assertIn("src/**/*.py", output)

    def test_changed_from_reports_unregistered_change(self) -> None:
        tracked = self.project / "src/login/app.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("value = 1\n", encoding="utf-8")
        self.write_doc(
            "docs/document-map.yml",
            "areas:\n  - path: src/login\n    docs:\n      - docs/interfaces/auth.md\n",
        )
        self.commit_all()
        untracked = self.project / "src/other/new.py"
        untracked.parent.mkdir(parents=True)
        untracked.write_text("new = True\n", encoding="utf-8")

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("未登记", output)
        self.assertIn("src/other/new.py", output)

    def test_directory_area_does_not_match_sibling_prefix(self) -> None:
        tracked = self.project / "src/login/app.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("value = 1\n", encoding="utf-8")
        self.write_doc(
            "docs/document-map.yml",
            "areas:\n  - path: src/login\n    docs:\n      - docs/interfaces/auth.md\n",
        )
        self.commit_all()
        sibling = self.project / "src/login2/extra.py"
        sibling.parent.mkdir(parents=True)
        sibling.write_text("extra = 1\n", encoding="utf-8")

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("可能影响文档", output)
        self.assertIn("未登记", output)

    def test_without_changed_from_no_hints(self) -> None:
        tracked = self.project / "src/login/app.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("value = 1\n", encoding="utf-8")
        self.write_doc(
            "docs/document-map.yml",
            "areas:\n  - path: src/login\n    docs:\n      - docs/interfaces/auth.md\n",
        )
        self.commit_all()
        tracked.write_text("value = 2\n", encoding="utf-8")

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("可能影响文档", output)
        self.assertNotIn("未登记", output)

    def test_changed_from_clean_tree_has_no_hints(self) -> None:
        self.write_doc(
            "docs/document-map.yml",
            "areas:\n  - path: src/login\n    docs:\n      - docs/interfaces/auth.md\n",
        )
        self.commit_all()

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("可能影响文档", output)
        self.assertNotIn("未登记", output)

    def test_malformed_document_map_warns_with_changed_from(self) -> None:
        self.commit_all()
        untracked = self.project / "src/login/app.py"
        untracked.parent.mkdir(parents=True)
        untracked.write_text("value = 1\n", encoding="utf-8")
        self.write_doc(
            "docs/document-map.yml",
            "areas: {path: src/login, docs: [docs/interfaces/auth.md]}\n",
        )

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("无法解析", output)
        self.assertNotIn("可能影响文档", output)
        self.assertNotIn("未登记", output)
        self.assertNotIn("错误：", output)

    def test_unknown_revision_exits_2(self) -> None:
        self.commit_all()

        result = self.run_full("--changed-from", "no-such-revision")

        output = self.output(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("版本", output)

    def test_docs_list_same_indent_parses(self) -> None:
        tracked = self.project / "src/login/app.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("value = 1\n", encoding="utf-8")
        self.write_doc(
            "docs/document-map.yml",
            "areas:\n  - path: src/login\n    docs:\n    - docs/interfaces/auth.md\n",
        )
        self.commit_all()
        tracked.write_text("value = 2\n", encoding="utf-8")

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("可能影响文档", output)
        self.assertIn("docs/interfaces/auth.md", output)

    def test_single_star_does_not_cross_directories(self) -> None:
        tracked = self.project / "src/auth/login.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("value = 1\n", encoding="utf-8")
        self.write_doc(
            "docs/document-map.yml",
            "areas:\n  - path: src/*.py\n    docs:\n      - docs/interfaces/auth.md\n",
        )
        self.commit_all()
        tracked.write_text("value = 2\n", encoding="utf-8")

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("可能影响文档", output)
        self.assertIn("未登记", output)

    def test_double_star_crosses_directories(self) -> None:
        tracked = self.project / "src/auth/login.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("value = 1\n", encoding="utf-8")
        self.write_doc(
            "docs/document-map.yml",
            "areas:\n  - path: src/**\n    docs:\n      - docs/interfaces/auth.md\n",
        )
        self.commit_all()
        tracked.write_text("value = 2\n", encoding="utf-8")

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("可能影响文档", output)
        self.assertNotIn("未登记", output)

    def test_reconcile_updated_path_present_passes(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(
                impact_rows=["| docs/interfaces/auth.md | 已更新 | 已更新 |"]
            ),
        )
        self.commit_all()
        auth = self.project / "docs/interfaces/auth.md"
        auth.write_text(auth.read_text(encoding="utf-8") + "\n补充。\n", encoding="utf-8")

        result = self.run_task("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("错误：", output)

    def test_reconcile_updated_path_missing_is_error(self) -> None:
        self.write_doc(
            "docs/interfaces/other.md",
            INTERFACE_DOC.replace("IFACE-001", "IFACE-002").replace(
                "登录接口", "另一个接口"
            ),
        )
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(
                impact_rows=["| docs/interfaces/other.md | 已更新 | 已更新 |"]
            ),
        )
        self.commit_all()
        auth = self.project / "docs/interfaces/auth.md"
        auth.write_text(auth.read_text(encoding="utf-8") + "\n补充。\n", encoding="utf-8")

        result = self.run_task("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("docs/interfaces/other.md 不在本次改动中", output)
        self.assertIn("ref 选早了会误报", output)

    def test_reconcile_updated_type_without_directory_change_is_error(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(impact_rows=["| 接口 | 已更新 | 已更新 |"]),
        )
        self.commit_all()
        readme = self.project / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\n改动。\n", encoding="utf-8"
        )

        result = self.run_task("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("没有任何「接口」类型的文档", output)

    def test_reconcile_type_name_with_document_suffix_passes(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(impact_rows=["| 接口文档 | 已更新 | 已更新 |"]),
        )
        self.commit_all()
        auth = self.project / "docs/interfaces/auth.md"
        auth.write_text(auth.read_text(encoding="utf-8") + "\n补充。\n", encoding="utf-8")

        result = self.run_task("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)

    def test_reconcile_skips_no_update_needed_rows(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(
                impact_rows=["| 接口 | 检查后无需更新 | 行为未变 |"]
            ),
        )
        self.commit_all()
        readme = self.project / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\n改动。\n", encoding="utf-8"
        )

        result = self.run_task("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("错误：", output)

    def test_reconcile_not_run_without_changed_from(self) -> None:
        self.write_doc(
            "docs/interfaces/other.md",
            INTERFACE_DOC.replace("IFACE-001", "IFACE-002").replace(
                "登录接口", "另一个接口"
            ),
        )
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(
                impact_rows=["| docs/interfaces/other.md | 已更新 | 已更新 |"]
            ),
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)

    def test_reconcile_unknown_target_warns(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(impact_rows=["| 登录相关的东西 | 已更新 | 已更新 |"]),
        )
        self.commit_all()
        readme = self.project / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\n改动。\n", encoding="utf-8"
        )

        result = self.run_task("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("无法核实", output)

    def test_full_scan_with_changed_from_reports_no_reconcile(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(
                impact_rows=["| docs/interfaces/other.md | 已更新 | 已更新 |"]
            ),
        )
        self.commit_all()
        readme = self.project / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\n改动。\n", encoding="utf-8"
        )

        result = self.run_full("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("没有核对影响判断", output)

    def test_reconcile_multi_type_row_checks_each_type(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(impact_rows=["| 需求/缺陷 | 已更新 | 已更新 |"]),
        )
        self.commit_all()
        readme = self.project / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\n改动。\n", encoding="utf-8"
        )

        result = self.run_task("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("「需求」", output)
        self.assertIn("「缺陷」", output)
        self.assertNotIn("不在本次改动中", output)

    def test_reconcile_multi_type_row_passes_when_all_changed(self) -> None:
        self.write_doc(
            "docs/requirements/REQ-001.md",
            typed_doc("requirement", "REQ-001", "登录需求"),
        )
        self.write_doc(
            "docs/bugs/BUG-001.md", typed_doc("bug", "BUG-001", "登录缺陷")
        )
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(impact_rows=["| 需求/缺陷 | 已更新 | 已更新 |"]),
        )
        self.commit_all()
        for relative in ("docs/requirements/REQ-001.md", "docs/bugs/BUG-001.md"):
            path = self.project / relative
            path.write_text(
                path.read_text(encoding="utf-8") + "\n补充。\n", encoding="utf-8"
            )

        result = self.run_task("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("错误：", output)

    def test_reconcile_multi_type_with_unknown_part_warns(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md",
            task_document(impact_rows=["| 需求/登录模块 | 已更新 | 已更新 |"]),
        )
        self.commit_all()
        readme = self.project / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\n改动。\n", encoding="utf-8"
        )

        result = self.run_task("--changed-from", "HEAD")

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("无法核实", output)
        self.assertNotIn("不在本次改动中", output)

    def test_private_key_block_is_error_and_masked(self) -> None:
        block = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEAabcdefghijklmnop\n"
            "-----END RSA PRIVATE KEY-----"
        )
        self.write_doc(
            "docs/modules/notes.md",
            typed_doc("module-doc", "MODULE-001", "随手记") + "\n" + block + "\n",
        )

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("私钥块", output)
        self.assertNotIn("MIIEowIBAAKCAQEAabcdefghijklmnop", output)

    def test_aws_key_is_error_and_masked(self) -> None:
        secret = "AKIAZW7Q2LMNB4X9R3TV"
        self.write_doc(
            "docs/modules/notes.md",
            typed_doc("module-doc", "MODULE-001", "随手记") + f"\n{secret}\n",
        )

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("AWS Access Key", output)
        self.assertNotIn(secret, output)
        self.assertIn("AKIA…（已打码）", output)

    def test_token_formats_are_errors_and_masked(self) -> None:
        secrets = [
            "ghp_abcdefghijklmnopqrstuvwxyz0123",
            "xoxb-1234567890-abcdefghij",
            "sk-proj-abcdefghijklmnopqrstuvwx",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghij",
        ]
        self.write_doc(
            "docs/modules/notes.md",
            typed_doc("module-doc", "MODULE-001", "随手记")
            + "\n"
            + "\n".join(secrets)
            + "\n",
        )

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        for label in ("GitHub Token", "Slack Token", "sk- 密钥", "JWT"):
            self.assertIn(label, output)
        for secret in secrets:
            self.assertNotIn(secret, output)

    def test_password_assignment_only_warns_and_masked(self) -> None:
        self.write_doc(
            "docs/modules/notes.md",
            typed_doc("module-doc", "MODULE-001", "随手记")
            + '\n- password = "hunter2xyz"\n',
        )

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("疑似敏感赋值", output)
        self.assertNotIn("hunter2xyz", output)
        self.assertIn("hunt…（已打码）", output)

    def test_placeholders_are_not_flagged(self) -> None:
        placeholders = [
            '- password = "<your-password>"',
            "- token: xxx",
            "- api_key: YOUR_KEY",
            "- secret: ***",
            "- client_secret: 待填写",
            "- access_key: example",
            '- password = ""',
            "- token: {{TOKEN}}",
        ]
        self.write_doc(
            "docs/modules/notes.md",
            typed_doc("module-doc", "MODULE-001", "随手记")
            + "\n"
            + "\n".join(placeholders)
            + "\n",
        )

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("疑似泄露", output)
        self.assertNotIn("疑似敏感赋值", output)

    def test_task_mode_scans_only_related_documents(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md", task_document()
        )
        self.write_doc(
            "docs/bugs/BUG-002.md",
            typed_doc("bug", "BUG-002", "无关缺陷") + "\nAKIAZW7Q2LMNB4X9R3TV\n",
        )

        task_result = self.run_check()
        full_result = self.run_full()

        self.assertEqual(task_result.returncode, 0, self.output(task_result))
        self.assertNotIn("疑似泄露", self.output(task_result))
        self.assertEqual(full_result.returncode, 1, self.output(full_result))
        self.assertIn("疑似泄露", self.output(full_result))

    def test_private_key_block_variants_are_errors(self) -> None:
        body = "MIIEowIBAAKCAQEAabcdefghijklmnop"
        for label in ("OPENSSH", "EC", "RSA"):
            block = (
                f"-----BEGIN {label} PRIVATE KEY-----\n"
                f"{body}\n"
                f"-----END {label} PRIVATE KEY-----"
            )
            self.write_doc(
                "docs/modules/notes.md",
                typed_doc("module-doc", "MODULE-001", "随手记")
                + "\n"
                + block
                + "\n",
            )

            result = self.run_full()

            output = self.output(result)
            self.assertEqual(result.returncode, 1, f"{label}: {output}")
            self.assertIn("私钥块", output)
            self.assertNotIn(body, output)

    def test_pgp_private_key_block_is_error(self) -> None:
        body = "abc123def456ghi789"
        block = (
            "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
            f"{body}\n"
            "-----END PGP PRIVATE KEY BLOCK-----"
        )
        self.write_doc(
            "docs/modules/notes.md",
            typed_doc("module-doc", "MODULE-001", "随手记") + "\n" + block + "\n",
        )

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("私钥块", output)
        self.assertNotIn(body, output)

    def test_slack_xoxc_and_xoxe_are_errors(self) -> None:
        secrets = [
            "xoxc-1234567890-abcdefghij",
            "xoxe-1234567890-abcdefghij",
        ]
        for secret in secrets:
            self.write_doc(
                "docs/modules/notes.md",
                typed_doc("module-doc", "MODULE-001", "随手记")
                + f"\n{secret}\n",
            )

            result = self.run_full()

            output = self.output(result)
            self.assertEqual(result.returncode, 1, f"{secret}: {output}")
            self.assertIn("Slack Token", output)
            self.assertNotIn(secret, output)

    def test_task_progress_word_in_document_status_hints_task_status(self) -> None:
        for word in ("已完成", "进行中", "已记录", "已确认"):
            self.write_doc(
                "docs/tasks/TASK-001.md",
                task_document(document_status=word),
            )

            result = self.run_check()

            output = self.output(result)
            self.assertEqual(result.returncode, 1, f"{word}: {output}")
            self.assertIn("document_status 非法", output)
            self.assertIn("工作接续快照的 task_status", output)
            self.assertNotIn("本文件的 task_status", output)

    def test_other_invalid_status_has_no_task_status_hint(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001.md", task_document(document_status="生效中")
        )

        result = self.run_check()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("document_status 非法", output)
        self.assertNotIn("task_status", output)

    def test_work_snapshot_status_hint_points_to_its_own_field(self) -> None:
        self.write_doc(
            "docs/tasks/TASK-001-work-snapshot.md",
            """---
id: "WS-TASK-001"
type: work-snapshot
title: "工作接续快照：TASK-001"
document_status: 进行中
task_status: 进行中
owner: "张三"
updated_at: "2026-10-26"
related_tasks: ["TASK-001"]
replaces: ""
---

# 工作接续快照：TASK-001
""",
        )

        result = self.run_full()

        output = self.output(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("本文件的 task_status", output)
        self.assertNotIn("工作接续快照的 task_status", output)

if __name__ == "__main__":
    unittest.main()
