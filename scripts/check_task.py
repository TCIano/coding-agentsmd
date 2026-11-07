#!/usr/bin/env python3
"""检查接入项目中某个任务的文档记录是否完整。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[1]

BUILTIN_TYPES = {
    "requirement",
    "bug",
    "interface",
    "adr",
    "task-change",
    "work-snapshot",
    "project-snapshot",
    "project-changelog",
}
ALLOWED_DOCUMENT_STATUS = {"草稿", "现行", "已取代", "已归档"}
REQUIRED_FIELDS = ("id", "type", "title", "document_status", "owner", "updated_at")
TASK_SECTIONS = ("改动与原因", "文档影响判断", "验证", "合并检查")
ALLOWED_CONCLUSIONS = ("已更新", "检查后无需更新")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]*)\)")
SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
HEADING_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*$")


class UsageError(Exception):
    """用法或运行环境不满足检查条件。"""


class ChineseArgumentParser(argparse.ArgumentParser):
    """参数错误也使用中文前缀，保持退出码 2。"""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"错误：参数不正确（{message}）。", file=sys.stderr)
        raise SystemExit(2)


@dataclass
class Document:
    path: Path
    relative: Path
    meta: dict[str, str | list[str]]
    body: str

    def text(self, key: str) -> str:
        value = self.meta.get(key)
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    def items(self, key: str) -> list[str]:
        value = self.meta.get(key)
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)


# ---------------------------------------------------------------------------
# 通用解析
# ---------------------------------------------------------------------------


def unquote_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def strip_yaml_comment(value: str) -> str:
    """去掉 YAML 行内注释；引号内的 # 保留。"""
    quote = ""
    for index, char in enumerate(value):
        if char in "\"'":
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
        elif char == "#" and not quote:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
    return value.rstrip()


def parse_value(value: str) -> str | list[str]:
    value = strip_yaml_comment(value.strip())
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [
            unquote_value(item)
            for item in inner.split(",")
            if unquote_value(item)
        ]
    return unquote_value(value)


def parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    """解析文件开头 ``---`` 之间的简单 frontmatter，返回 (字段, 正文)。"""
    lines = text.splitlines()
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].strip() != "---":
        return {}, text

    end = None
    for index in range(start + 1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text

    meta: dict[str, str | list[str]] = {}
    current_key: str | None = None
    for raw in lines[start + 1 : end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = FRONTMATTER_KEY_RE.match(raw)
        if match:
            key = match.group(1)
            current_key = key
            value = match.group(2).strip()
            if not value:
                meta[key] = []
            else:
                meta[key] = parse_value(value)
            continue
        if current_key and raw.lstrip().startswith("- "):
            item = unquote_value(strip_yaml_comment(raw.lstrip()[2:]))
            existing = meta.get(current_key)
            if isinstance(existing, list):
                existing.append(item)
            else:
                meta[current_key] = [item]

    body = "\n".join(lines[end + 1 :])
    return meta, body


def is_scan_candidate(path: Path, docs_dir: Path) -> bool:
    relative = path.relative_to(docs_dir)
    if "_templates" in relative.parts or "drafts" in relative.parts:
        return False
    return not path.name.startswith("_")


def scan_documents(project: Path, report: Report) -> list[Document]:
    docs_dir = project / "docs"
    documents: list[Document] = []
    for path in sorted(docs_dir.rglob("*.md")):
        if not is_scan_candidate(path, docs_dir):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            report.warning(f"无法读取 {path.relative_to(project)}：{exc}；已跳过。")
            continue
        meta, body = parse_frontmatter(text)
        documents.append(
            Document(
                path=path,
                relative=path.relative_to(project),
                meta=meta,
                body=body,
            )
        )
    return documents


def section_lines(body: str, name: str) -> list[str] | None:
    """返回 ``## name`` 小节的正文行；小节不存在时返回 None。"""
    lines = body.splitlines()
    start = None
    for index, line in enumerate(lines):
        heading = HEADING_RE.match(line.strip())
        if heading and heading.group(1) == "##" and heading.group(2) == name:
            start = index + 1
            break
    if start is None:
        return None

    end = len(lines)
    for index in range(start, len(lines)):
        heading = HEADING_RE.match(lines[index].strip())
        if heading and len(heading.group(1)) <= 2:
            end = index
            break
    return lines[start:end]


def split_table_row(line: str) -> list[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [cell.strip() for cell in row.split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(SEPARATOR_CELL_RE.match(cell) for cell in cells)


def parse_table(lines: list[str]) -> tuple[list[str] | None, list[list[str]]]:
    """解析小节中的第一张 Markdown 表格，返回 (表头, 数据行)。"""
    header: list[str] | None = None
    rows: list[list[str]] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("|"):
            cells = split_table_row(stripped)
            if header is None:
                header = cells
            elif is_separator_row(cells):
                continue
            else:
                rows.append(cells)
            continue
        if header is not None:
            break
    return header, rows


def has_any_content(cells: list[str]) -> bool:
    return any(cell.strip() for cell in cells)


def strip_fenced_code(text: str) -> str:
    output: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if not in_fence:
            output.append(line)
    return "\n".join(output)


# ---------------------------------------------------------------------------
# 环境与版本
# ---------------------------------------------------------------------------


def read_repo_version() -> str | None:
    version_file = REPO_ROOT / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def read_system_version(project: Path) -> str | None:
    system_file = project / "docs/system.yml"
    try:
        lines = system_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for line in lines:
        match = re.match(r"^\s*system_version:\s*(.*)$", line)
        if match:
            value = unquote_value(strip_yaml_comment(match.group(1)).strip())
            return value or None
    return None


def check_version(project: Path, report: Report) -> None:
    repo_version = read_repo_version()
    if not repo_version:
        report.warning("无法读取本仓库 VERSION，已跳过模板版本比较。")
        return
    project_version = read_system_version(project)
    if not project_version:
        report.warning(
            "无法从 docs/system.yml 读取 system_version，已跳过模板版本比较。"
        )
        return
    if project_version != repo_version:
        report.warning(
            f"项目模板版本 {project_version} 与本仓库 VERSION {repo_version} 不同；"
            "可用 scripts/upgrade_templates.py 查看差异（版本较旧不单独构成失败）。"
        )


# ---------------------------------------------------------------------------
# 文档字段与链接
# ---------------------------------------------------------------------------


def document_ids(documents: list[Document]) -> dict[str, list[Document]]:
    result: dict[str, list[Document]] = {}
    for document in documents:
        doc_id = document.text("id").strip()
        if doc_id:
            result.setdefault(doc_id, []).append(document)
    return result


def check_duplicate_ids(documents: list[Document], report: Report) -> None:
    for doc_id, owners in sorted(document_ids(documents).items()):
        if len(owners) > 1:
            paths = "、".join(str(document.relative) for document in owners)
            report.error(f"文档编号重复：{doc_id} 同时出现在 {paths}。")


def replaces_target_exists(
    value: str,
    document: Document,
    project: Path,
    all_ids: dict[str, list[Document]],
) -> bool:
    target = value.strip()
    if not target:
        return False
    if target in all_ids:
        return True
    raw = unquote(target.split("#", 1)[0]).strip()
    if not raw:
        return False
    candidates: list[Path] = []
    if raw.startswith("/"):
        candidates.append(project / raw.lstrip("/"))
    else:
        candidates.append(document.path.parent / raw)
        candidates.append(project / raw)
    return any(candidate.exists() for candidate in candidates)


def check_document_fields(
    document: Document,
    project: Path,
    all_ids: dict[str, list[Document]],
    report: Report,
) -> None:
    missing = [name for name in REQUIRED_FIELDS if name not in document.meta]
    if missing:
        report.error(
            f"{document.relative} 缺少必需字段：{'、'.join(missing)}。"
        )

    if "document_status" in document.meta:
        status = document.text("document_status").strip()
        if status not in ALLOWED_DOCUMENT_STATUS:
            report.error(
                f"{document.relative} 的 document_status 非法：{status or '（空）'}；"
                f"应为 {'、'.join(sorted(ALLOWED_DOCUMENT_STATUS))} 之一。"
            )
        if status == "已取代":
            replaces = document.text("replaces").strip()
            if not replaces:
                report.error(
                    f"{document.relative} 的 document_status 为“已取代”，但 replaces 为空；"
                    "已取代文档必须指向接替文档。"
                )
            elif not replaces_target_exists(
                replaces, document, project, all_ids
            ):
                report.error(
                    f"{document.relative} 的 replaces 指向不存在的文档或编号：{replaces}。"
                )

    if "updated_at" in document.meta:
        updated_at = document.text("updated_at").strip()
        if not DATE_RE.match(updated_at):
            report.error(
                f"{document.relative} 的 updated_at 不是 YYYY-MM-DD 格式："
                f"{updated_at or '（空）'}。"
            )

    if "title" in document.meta and not document.text("title").strip():
        report.error(f"{document.relative} 的 title 为空。")


def extract_link_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")].strip()
    parts = target.split()
    return parts[0] if parts else ""


def check_local_links(document: Document, project: Path, report: Report) -> None:
    body = strip_fenced_code(document.body)
    for match in LINK_RE.finditer(body):
        target = extract_link_target(match.group(1))
        if not target or "{{" in target:
            continue
        lowered = target.lower()
        if lowered.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if target.startswith("#"):
            continue
        path_part = unquote(target.split("#", 1)[0].split("?", 1)[0]).strip()
        if not path_part:
            continue
        if path_part.startswith("/"):
            destination = project / path_part.lstrip("/")
        else:
            destination = document.path.parent / path_part
        if not destination.exists():
            report.error(
                f"{document.relative} 的本地 Markdown 链接目标不存在：{target}。"
            )


# ---------------------------------------------------------------------------
# 任务变更记录内容
# ---------------------------------------------------------------------------


def check_impact_table(document: Document, lines: list[str], report: Report) -> None:
    _header, rows = parse_table(lines)
    data_rows = [row for row in rows if has_any_content(row)]
    if not data_rows:
        report.error(f"{document.relative} 的「文档影响判断」表无数据行。")
        return
    for row in data_rows:
        conclusion = row[1].strip() if len(row) > 1 else ""
        reason = row[2].strip() if len(row) > 2 else ""
        if conclusion == "待填写" or not conclusion:
            report.error(
                f"{document.relative} 的「文档影响判断」仍为“待填写”。"
            )
        elif conclusion not in ALLOWED_CONCLUSIONS:
            report.error(
                f"{document.relative} 的「文档影响判断」结论非法：{conclusion}；"
                "应为“已更新”或“检查后无需更新”。"
            )
        elif conclusion == "检查后无需更新" and reason in ("", "待填写"):
            report.warning(
                f"{document.relative} 的「文档影响判断」结论为“检查后无需更新”，"
                "但未写无需更新的理由。"
            )


def check_verification_table(
    document: Document, lines: list[str], report: Report
) -> None:
    _header, rows = parse_table(lines)
    data_rows = [
        row
        for row in rows
        if any(cell.strip() and cell.strip() != "待填写" for cell in row)
    ]
    if not data_rows:
        report.error(f"{document.relative} 的「验证」表无数据行。")
        return
    for row in data_rows:
        result = row[1].strip() if len(row) > 1 else ""
        reason = row[4].strip() if len(row) > 4 else ""
        if "待运行" in result and reason in ("", "待填写"):
            report.warning(
                f"{document.relative} 的验证结果“{result or '待运行'}”未写未运行原因与影响。"
            )


def merge_section_is_empty(lines: list[str]) -> bool:
    in_comment = False
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            in_comment = "-->" not in stripped
            continue
        if stripped in ("---", "***", "___"):
            continue
        return False
    return True


def check_task_change_content(document: Document, report: Report) -> None:
    sections: dict[str, list[str]] = {}
    missing: list[str] = []
    for name in TASK_SECTIONS:
        lines = section_lines(document.body, name)
        if lines is None:
            missing.append(name)
        else:
            sections[name] = lines
    if missing:
        report.error(
            f"{document.relative} 缺少任务变更记录小节：{'、'.join(missing)}。"
        )
    if "文档影响判断" in sections:
        check_impact_table(document, sections["文档影响判断"], report)
    if "验证" in sections:
        check_verification_table(document, sections["验证"], report)
    if "合并检查" in sections and merge_section_is_empty(sections["合并检查"]):
        report.warning(f"{document.relative} 的「合并检查」小节为空。")


# ---------------------------------------------------------------------------
# 文档对应表
# ---------------------------------------------------------------------------


def parse_document_map(text: str) -> tuple[list[str], bool]:
    """尽量解析 document-map.yml，返回 (docs 路径列表, 是否无法解析)。"""
    docs_paths: list[str] = []
    lines = text.splitlines()
    in_areas = False
    areas_indent = 0
    docs_indent: int | None = None
    malformed = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))

        if not in_areas:
            match = re.match(r"^(\s*)areas:\s*(.*)$", line)
            if not match:
                continue
            in_areas = True
            areas_indent = len(match.group(1))
            rest = strip_yaml_comment(match.group(2).strip())
            if rest == "[]":
                return [], False
            if rest:
                # 非空但非块状列表（如 flow mapping）无法安全解析。
                return [], True
            continue

        if indent <= areas_indent and not stripped.startswith("-"):
            break

        if docs_indent is not None:
            if indent > docs_indent and stripped.startswith("- "):
                item = unquote_value(strip_yaml_comment(stripped[2:]))
                if item:
                    docs_paths.append(item)
                continue
            docs_indent = None

        match = re.match(r"^\s*(?:-\s+)?docs:\s*(.*)$", line)
        if not match:
            if re.match(r"^\s*(?:-\s+)?docs\s*\{", line):
                malformed = True
            continue
        rest = unquote_value(strip_yaml_comment(match.group(1).strip()))
        if not rest:
            docs_indent = indent
            continue
        if rest.startswith("{") or rest.startswith("["):
            if rest.startswith("[") and rest.endswith("]"):
                inner = rest[1:-1].strip()
                if inner:
                    for item in inner.split(","):
                        item = unquote_value(item)
                        if item:
                            docs_paths.append(item)
                continue
            malformed = True
            continue
        docs_paths.append(rest)

    return docs_paths, malformed


def check_document_map(project: Path, report: Report) -> None:
    map_file = project / "docs/document-map.yml"
    if not map_file.exists():
        return
    try:
        text = map_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report.warning(f"无法读取 docs/document-map.yml：{exc}；已跳过。")
        return

    docs_paths, malformed = parse_document_map(text)
    if malformed:
        report.warning(
            "docs/document-map.yml 的 areas 结构无法解析，已跳过文档对应关系检查。"
        )
        return

    seen: set[str] = set()
    for entry in docs_paths:
        entry = entry.strip()
        if not entry or "{{" in entry or entry in seen:
            continue
        seen.add(entry)
        target = project / entry.lstrip("/")
        if not target.exists():
            report.warning(
                f"docs/document-map.yml 记录的文档不存在：{entry}；"
                "如为占位内容请忽略。"
            )


# ---------------------------------------------------------------------------
# 主检查流程
# ---------------------------------------------------------------------------


def prepare_project(project_argument: Path) -> Path:
    project = project_argument.resolve()
    if not project.exists():
        raise UsageError(f"项目目录不存在：{project_argument}")
    if not project.is_dir():
        raise UsageError(f"项目路径不是目录：{project_argument}")

    git = shutil.which("git")
    if not git:
        raise UsageError("未找到 git 命令，无法确认项目是否为 Git 根目录。")
    result = subprocess.run(
        [git, "-C", str(project), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise UsageError(f"无法确认 Git 根目录（项目不是 Git 仓库？）：{project}")
    try:
        git_root = Path(result.stdout.strip()).resolve()
    except OSError as exc:
        raise UsageError(f"无法解析 Git 根目录：{exc}") from exc
    if git_root != project:
        raise UsageError(
            f"项目目录必须是 Git 根目录：{project}（实际根目录：{git_root}）"
        )

    required = [
        (project / "docs/system.yml", "文件"),
        (project / "docs/_templates", "目录"),
        (project / "docs/tasks", "目录"),
    ]
    missing = [
        f"{path.relative_to(project)}（{kind}）"
        for path, kind in required
        if not path.exists()
    ]
    if missing:
        raise UsageError("缺少检查所需结构：" + "、".join(missing))
    return project


def is_task_related(document: Document, task_id: str) -> bool:
    return document.text("id").strip() == task_id or task_id in document.items(
        "related_tasks"
    )


def check_custom_types(documents: list[Document], report: Report) -> None:
    warned: set[str] = set()
    for document in documents:
        doc_type = document.text("type").strip()
        if not doc_type or doc_type in BUILTIN_TYPES or doc_type in warned:
            continue
        warned.add(doc_type)
        report.warning(
            f"{document.relative} 使用了自定义文档类型“{doc_type}”；"
            "请在项目内声明对应模板、存放位置和检查规则。"
        )


def run_checks(project: Path, task_id: str, report: Report) -> None:
    check_version(project, report)
    documents = scan_documents(project, report)
    all_ids = document_ids(documents)

    check_duplicate_ids(documents, report)
    check_custom_types(documents, report)

    records = [
        document
        for document in documents
        if document.text("type").strip() == "task-change"
        and is_task_related(document, task_id)
    ]
    if not records:
        report.error(
            f"未找到任务 {task_id} 的任务变更记录：需要 type 为 task-change，"
            f"且 id 为 {task_id} 或 related_tasks 含 {task_id} 的文档。"
        )

    related_documents = [
        document for document in documents if is_task_related(document, task_id)
    ]
    for document in related_documents:
        check_document_fields(document, project, all_ids, report)
        check_local_links(document, project, report)

    for document in records:
        check_task_change_content(document, report)

    check_document_map(project, report)


def print_report(report: Report, task_id: str) -> int:
    for message in report.errors:
        print(f"错误：{message}")
    for message in report.warnings:
        print(f"警告：{message}")
    if report.errors:
        print(
            f"错误：任务 {task_id} 检查未通过，"
            f"共 {len(report.errors)} 个错误、{len(report.warnings)} 个警告。"
        )
        return 1
    print(f"通过：任务 {task_id} 检查通过，无错误（{len(report.warnings)} 个警告）。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(
        description="检查接入项目中当前任务的文档记录。"
    )
    parser.add_argument("project", type=Path, help="接入项目的根目录")
    parser.add_argument("task_id", help="任务编号，例如 TASK-001")
    args = parser.parse_args(argv)

    if not args.task_id.strip():
        print("错误：任务编号不能为空。")
        return 2
    try:
        project = prepare_project(args.project)
    except UsageError as exc:
        print(f"错误：{exc}")
        return 2

    report = Report()
    run_checks(project, args.task_id.strip(), report)
    return print_report(report, args.task_id.strip())


if __name__ == "__main__":
    sys.exit(main())
