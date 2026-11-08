#!/usr/bin/env python3
"""汇总已合并任务的候选清单，供人整理 docs/CHANGELOG.md。

只读脚本。绝不修改、也绝不写入 docs/CHANGELOG.md：候选默认打到屏幕，
用 --output 写到指定文件；--output 指向 docs/CHANGELOG.md 会被拒绝。
“已合并”只按任务变更记录「合并检查」里的合并负责人判定，不另发明规则；
改动和验证原文照抄，不改写、不总结。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from check_task import parse_frontmatter, section_lines  # noqa: E402

PLACEHOLDER = "待填写"
CHANGELOG_RELATIVE = Path("docs/CHANGELOG.md")
MERGED_SECTION = "合并检查"
CHANGE_SECTION = "改动与原因"
VERIFY_SECTION = "验证"
MERGED_OWNER_RE = re.compile(r"^-\s*合并负责人[^：:]*[：:]\s*(.*)$")


class UsageError(Exception):
    """用法或项目环境不满足汇总条件。"""


@dataclass(frozen=True)
class Candidate:
    task_id: str
    title: str
    relative: Path
    change: tuple[str, ...]
    verification: tuple[str, ...]


def require_project(project_argument: Path) -> Path:
    project = project_argument.resolve()
    if not project.exists():
        raise UsageError(f"项目目录不存在：{project_argument}")
    if not project.is_dir():
        raise UsageError(f"项目路径不是目录：{project_argument}")
    if not (project / "docs/system.yml").is_file() or not (
        project / "docs/tasks"
    ).is_dir():
        raise UsageError(
            f"项目未初始化：缺少 docs/system.yml 或 docs/tasks：{project}"
        )
    return project


def trim_blank(lines: list[str]) -> tuple[str, ...]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return tuple(lines[start:end])


def merged_owner(lines: list[str] | None) -> str | None:
    """从「合并检查」小节取合并负责人；未填或仍是待填写时返回 None。"""
    if lines is None:
        return None
    for line in lines:
        match = MERGED_OWNER_RE.match(line.strip())
        if match is None:
            continue
        value = match.group(1).strip()
        if value and PLACEHOLDER not in value:
            return value
        return None
    return None


def task_records(project: Path) -> list[tuple[Path, str, str, str]]:
    """返回 (路径, 任务号, 标题, 正文)，按路径排序。"""
    records: list[tuple[Path, str, str, str]] = []
    tasks_dir = project / "docs" / "tasks"
    for path in sorted(tasks_dir.rglob("*.md")):
        relative = path.relative_to(project)
        if "drafts" in relative.parts or path.name.startswith("_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise UsageError(f"无法读取 {relative}：{exc}") from exc
        meta, body = parse_frontmatter(text)
        if str(meta.get("type", "")).strip() != "task-change":
            continue
        task_id = str(meta.get("id", "")).strip()
        title = str(meta.get("title", "")).strip()
        records.append((relative, task_id, title, body))
    return records


def changelog_body(project: Path) -> str:
    """读 CHANGELOG 正文，用来判断任务号是否已经收录。"""
    changelog = project / CHANGELOG_RELATIVE
    if not changelog.is_file():
        return ""
    try:
        text = changelog.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UsageError(f"无法读取 {CHANGELOG_RELATIVE}：{exc}") from exc
    _meta, body = parse_frontmatter(text)
    return body


def appears_in_changelog(task_id: str, changelog_body: str) -> bool:
    pattern = rf"(?<![\w-]){re.escape(task_id)}(?![\w-])"
    return re.search(pattern, changelog_body) is not None


def collect(
    project: Path,
) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    skipped: list[str] = []
    existing = changelog_body(project)
    for relative, task_id, title, body in task_records(project):
        label = task_id or "（无任务号）"
        if not task_id:
            skipped.append(f"{relative.as_posix()}：缺少 id，无法作为候选。")
            continue
        owner = merged_owner(section_lines(body, MERGED_SECTION))
        if owner is None:
            skipped.append(
                f"{label}（{relative.as_posix()}）：合并检查未填合并负责人，"
                "按未合并处理。"
            )
            continue
        if appears_in_changelog(task_id, existing):
            skipped.append(f"{label}（{relative.as_posix()}）：任务号已在 docs/CHANGELOG.md 中。")
            continue
        change = section_lines(body, CHANGE_SECTION)
        verification = section_lines(body, VERIFY_SECTION)
        missing = [
            name
            for name, lines in (
                (CHANGE_SECTION, change),
                (VERIFY_SECTION, verification),
            )
            if lines is None
        ]
        if missing:
            skipped.append(
                f"{label}（{relative.as_posix()}）：缺少小节"
                f"「{'、'.join(missing)}」，无法逐字摘录。"
            )
            continue
        candidates.append(
            Candidate(
                task_id=task_id,
                title=title,
                relative=relative,
                change=trim_blank(change or []),
                verification=trim_blank(verification or []),
            )
        )
    return candidates, skipped


def render(candidates: list[Candidate]) -> str:
    lines = [
        "# CHANGELOG 候选清单",
        "",
        "只列「合并检查」里已填合并负责人的任务变更记录；原文照抄，未做改写。",
        "链接为项目相对路径，整理 docs/CHANGELOG.md 时按需调整。",
        "",
    ]
    if not candidates:
        lines.append("（没有符合条件的新候选）")
        return "\n".join(lines) + "\n"
    for candidate in candidates:
        lines.extend(
            [
                f"## {candidate.task_id} {candidate.title}".rstrip(),
                "",
                f"- 任务号：{candidate.task_id}",
                f"- 标题：{candidate.title or '（空）'}",
                f"- 链接：{candidate.relative.as_posix()}",
                "",
                "改动原文：",
                "",
                *candidate.change,
                "",
                "验证原文：",
                "",
                *candidate.verification,
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="接入项目的根目录")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="文件",
        help="把候选写入该文件；省略时打到屏幕。文件已存在则不写",
    )
    args = parser.parse_args(argv)

    try:
        project = require_project(args.project)
        candidates, skipped = collect(project)
    except UsageError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    text = render(candidates)
    summary = f"候选 {len(candidates)} 条，跳过 {len(skipped)} 条。"

    if args.output is None:
        print(text, end="")
    else:
        target = args.output
        try:
            resolved = target.resolve()
        except OSError as exc:
            print(f"错误：无法解析输出路径：{exc}", file=sys.stderr)
            return 2
        if resolved == (project / CHANGELOG_RELATIVE).resolve():
            print(
                "错误：不允许写入 docs/CHANGELOG.md；请用 --output 指向别的文件，"
                "候选由人整理后手动并入。",
                file=sys.stderr,
            )
            return 2
        if target.exists():
            print(f"错误：输出文件已存在，未覆盖：{target}", file=sys.stderr)
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"已写入：{target}", file=sys.stderr)

    print(summary, file=sys.stderr)
    for item in skipped:
        print(f"跳过：{item}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
