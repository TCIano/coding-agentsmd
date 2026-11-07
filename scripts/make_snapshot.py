#!/usr/bin/env python3
"""生成工作接续快照或项目状态快照的草稿。

工具只填机器知道的信息：代码版本、分支、有没有未提交改动、生成时间。
进度、验证结论、下一步一律留在“待填写”，不替人编。
文件已存在时拒绝覆盖；模板副本与工具对不上时直接报错，不静默产出错字段。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

TEMPLATE_NAMES = {
    "work": "work-snapshot.md",
    "project": "project-snapshot.md",
}
TARGET_DIRS = {
    "work": Path("docs") / "tasks",
    "project": Path("docs") / "snapshots",
}
KIND_LABELS = {
    "work": "工作接续快照",
    "project": "项目状态快照",
}
PLACEHOLDER = "待填写"
TASK_ID_RE = re.compile(r"^[\w.-]+$")


class UsageError(Exception):
    """用法或项目环境不满足生成条件。"""


def git_output(project: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "未知错误"
        raise UsageError(f"git {' '.join(arguments)} 失败：{message}")
    return result.stdout


def require_project(project_argument: Path, kind: str) -> Path:
    project = project_argument.resolve()
    if not project.exists():
        raise UsageError(f"项目目录不存在：{project_argument}")
    if not project.is_dir():
        raise UsageError(f"项目路径不是目录：{project_argument}")
    if not shutil.which("git"):
        raise UsageError("未找到 git 命令，无法读取代码版本。")
    root = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if root.returncode != 0:
        raise UsageError(f"项目不是 Git 仓库：{project}")
    git_root = Path(root.stdout.strip()).resolve()
    if git_root != project:
        raise UsageError(
            f"项目目录必须是 Git 根目录：{project}（实际根目录：{git_root}）"
        )
    if not (project / "docs/system.yml").is_file() or not (
        project / "docs/_templates"
    ).is_dir():
        raise UsageError(
            f"项目未初始化：缺少 docs/system.yml 或 docs/_templates：{project}"
        )
    target_dir = project / TARGET_DIRS[kind]
    if not target_dir.is_dir():
        raise UsageError(f"缺少快照目录：{TARGET_DIRS[kind]}（{project}）")
    return project


def read_template(project: Path, kind: str) -> str:
    template = project / "docs" / "_templates" / TEMPLATE_NAMES[kind]
    if not template.is_file():
        raise UsageError(
            f"项目缺少快照模板：docs/_templates/{TEMPLATE_NAMES[kind]}；"
            "可用 scripts/upgrade_templates.py 查看差异。"
        )
    return template.read_text(encoding="utf-8")


def render(content: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", value)
    return content


def display_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def set_field(
    content: str,
    key: str,
    value: str,
    warnings: list[str] | None = None,
) -> str:
    """把 frontmatter 的 key 强制写成 value，不照抄模板副本里的值。

    传入 warnings 时，如果模板副本原来的值和要写的值不同，追加一条警告。
    """
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*)$", re.MULTILINE)
    match = pattern.search(content)
    if match is None:
        raise UsageError(
            f"项目模板副本缺少 frontmatter 字段“{key}”；"
            "先用 scripts/upgrade_templates.py 查看差异。"
        )
    if warnings is not None:
        original = display_value(match.group(1))
        wanted = display_value(value)
        if original != wanted:
            warnings.append(
                f"模板副本的 {key} 是「{original or '（空）'}」，"
                f"工具已按「{wanted}」生成，请核对 docs/_templates/。"
            )
    return pattern.sub(lambda _match: f"{key}: {value}", content, count=1)


def require_and_replace(content: str, expected: str, replacement: str) -> str:
    """占位行必须原样存在且只出现一次，否则拒绝生成。"""
    if content.count(expected) != 1:
        raise UsageError(
            f"项目模板副本与服务工具不兼容：找不到唯一的“{expected}”；"
            "先用 scripts/upgrade_templates.py 查看差异。"
        )
    return content.replace(expected, replacement, 1)


def ensure_no_placeholders(content: str) -> str:
    for line in content.splitlines():
        if "{{" in line:
            raise UsageError(
                f"项目模板副本还有未替换的占位符：{line.strip()}；"
                "先用 scripts/upgrade_templates.py 查看差异。"
            )
    return content


def fill_line(content: str, prefix: str, value: str) -> str:
    """把模板里以 prefix 开头的一行替换成 prefix + value。"""
    for line in content.splitlines(keepends=True):
        if not line.startswith(prefix):
            continue
        newline = "\n" if line.endswith("\n") else ""
        content = content.replace(line, prefix + value + newline, 1)
        return content
    raise UsageError(
        f"项目模板副本与服务工具不兼容：找不到以“{prefix.strip()}”开头的行。"
    )


def code_revision(project: Path) -> str:
    try:
        return git_output(project, "rev-parse", "--short", "HEAD").strip()
    except UsageError as exc:
        raise UsageError(f"无法读取已提交代码版本（仓库还没有提交？）：{exc}") from exc


def current_branch(project: Path) -> str:
    branch = git_output(project, "rev-parse", "--abbrev-ref", "HEAD").strip()
    return "分离 HEAD" if branch == "HEAD" else branch


def describe_uncommitted(project: Path) -> str:
    status = git_output(
        project, "status", "--porcelain", "--untracked-files=all"
    )
    entries = [line for line in status.splitlines() if line.strip()]
    if not entries:
        return "无"
    items = []
    for line in entries:
        code = line[:2].strip() or "修改"
        path = line[3:].strip()
        items.append(f"{path}（{code}）")
    return f"有，共 {len(items)} 个文件：" + "、".join(items)


def generated_at_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_work_snapshot(
    project: Path, task_id: str, warnings: list[str]
) -> tuple[str, Path]:
    today = date.today().isoformat()
    content = render(
        read_template(project, "work"),
        {
            "ID": f"WS-{task_id}",
            "TITLE": f"工作接续快照：{task_id}",
            "OWNER": PLACEHOLDER,
            "DATE": today,
        },
    )
    revision = code_revision(project)
    branch = current_branch(project)
    content = set_field(content, "id", f'"WS-{task_id}"')
    content = set_field(content, "type", "work-snapshot", warnings)
    content = set_field(content, "title", f'"工作接续快照：{task_id}"')
    content = set_field(content, "document_status", "草稿", warnings)
    content = set_field(content, "task_status", "进行中", warnings)
    content = set_field(content, "owner", f'"{PLACEHOLDER}"')
    content = set_field(content, "updated_at", f'"{today}"')
    content = require_and_replace(
        content, "related_tasks: []", f'related_tasks: ["{task_id}"]'
    )
    content = fill_line(
        content,
        "- 分支与已提交代码版本：",
        f"{branch}（{revision}）。",
    )
    content = fill_line(content, "- 未提交改动：", f"{describe_uncommitted(project)}。")
    content = fill_line(content, "- 快照时间：", f"{generated_at_text()}。")
    return ensure_no_placeholders(content), TARGET_DIRS["work"] / (
        f"{task_id}-work-snapshot.md"
    )


def build_project_snapshot(
    project: Path, task_id: str | None, warnings: list[str]
) -> tuple[str, Path]:
    revision = code_revision(project)
    branch = current_branch(project)
    timestamp = generated_at_text()
    today = date.today().isoformat()
    content = render(
        read_template(project, "project"),
        {
            "ID": f"PS-{revision}",
            "TITLE": f"项目状态快照：{revision}",
            "OWNER": PLACEHOLDER,
            "DATE": today,
        },
    )
    content = set_field(content, "id", f'"PS-{revision}"')
    content = set_field(content, "type", "project-snapshot", warnings)
    content = set_field(content, "title", f'"项目状态快照：{revision}"')
    content = set_field(content, "document_status", "草稿", warnings)
    content = set_field(content, "owner", f'"{PLACEHOLDER}"')
    content = set_field(content, "updated_at", f'"{today}"')
    content = set_field(content, "verified_at", '""')
    content = require_and_replace(
        content, 'generated_at: ""', f'generated_at: "{timestamp}"'
    )
    content = require_and_replace(
        content, 'code_revision: ""', f'code_revision: "{revision}"'
    )
    related = f'related_tasks: ["{task_id}"]' if task_id else "related_tasks: []"
    content = require_and_replace(content, "related_tasks: []", related)
    content = fill_line(
        content,
        "- 代码版本与分支：",
        f"{revision}（{branch}）。",
    )
    content = fill_line(content, "- 未提交改动：", f"{describe_uncommitted(project)}。")
    content = fill_line(
        content,
        "- 快照生成时间：",
        f"{timestamp}。",
    )
    return ensure_no_placeholders(content), TARGET_DIRS["project"] / (
        f"{revision}-project-snapshot.md"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="接入项目的根目录")
    parser.add_argument(
        "--kind",
        required=True,
        choices=("work", "project"),
        help="work 生成工作接续快照，project 生成项目状态快照",
    )
    parser.add_argument(
        "--task",
        default=None,
        help="任务编号；work 必填，project 可省略",
    )
    args = parser.parse_args(argv)

    task_id = args.task.strip() if args.task is not None else None
    if args.task is not None and not task_id:
        print("错误：任务编号不能为空。")
        return 2
    if args.kind == "work" and not task_id:
        print("错误：生成工作接续快照必须提供 --task。")
        return 2
    if task_id and not TASK_ID_RE.fullmatch(task_id):
        print(f"错误：任务编号只能包含字母、数字、下划线、点和连字符：{task_id}")
        return 2

    try:
        project = require_project(args.project, args.kind)
        warnings: list[str] = []
        if args.kind == "work":
            content, relative = build_work_snapshot(
                project, task_id or "", warnings
            )
        else:
            content, relative = build_project_snapshot(project, task_id, warnings)
    except UsageError as exc:
        print(f"错误：{exc}")
        return 2

    target = project / relative
    if target.exists():
        print(f"错误：快照文件已存在，未覆盖：{relative}")
        return 1
    target.write_text(content, encoding="utf-8")
    for message in warnings:
        print(f"警告：{message}")
    print(f"已生成{KIND_LABELS[args.kind]}草稿：{relative}")
    print("只填了代码版本、分支、未提交改动和生成时间，其余内容仍需人工填写。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
