#!/usr/bin/env python3
"""检查接入项目的正式文档，或只检查某个任务的记录。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from doc_types import BUILTIN_TYPES, DOC_TYPES  # noqa: E402

ALLOWED_DOCUMENT_STATUS = {"草稿", "现行", "已取代", "已归档"}
REQUIRED_FIELDS = ("id", "type", "title", "document_status", "owner", "updated_at")
# 常见把任务进度填进 document_status 的词，报错时给人指个路。
TASK_PROGRESS_WORDS = {
    "进行中",
    "已完成",
    "已结束",
    "已记录",
    "已确认",
    "处理中",
    "待处理",
    "待开始",
    "未开始",
    "待验证",
    "已验证",
    "已关闭",
    "已合并",
    "已取消",
}
TASK_SECTIONS = ("改动与原因", "文档影响判断", "验证", "合并检查")
# 快照可能先于任务记录存在，不对它们的 related_tasks 报缺失。
SNAPSHOT_TYPES = {"work-snapshot", "project-snapshot"}
ALLOWED_CONCLUSIONS = ("已更新", "检查后无需更新")
IMPACT_HEADERS = (
    "文档类型或具体文件",
    "结论（已更新／检查后无需更新）",
    "链接或无需更新的理由",
)
VERIFICATION_HEADERS = (
    "命令或操作",
    "结果",
    "代码版本",
    "时间",
    "未运行原因与影响",
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]*)\)")
# 行内代码里的链接写法只是举例，不参与本地链接检查。
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
# 表格分隔行至少一个短横，与 CommonMark/GFM 一致；:-- 一类写法也认得。
SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
# docs/ 下是文档本身，不是代码区域，不列入「未登记在对应表」的提示。
DOCS_PREFIX = "docs/"
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
    content: str

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
    # docs/index.md 是文档索引页，不是正式文档，不要求 frontmatter。
    if relative == Path("index.md"):
        return False
    return not path.name.startswith("_")


def scan_documents(project: Path, report: Report) -> list[Document]:
    docs_dir = project / "docs"
    documents: list[Document] = []
    for path in sorted(docs_dir.rglob("*.md")):
        if not is_scan_candidate(path, docs_dir):
            continue
        relative = path.relative_to(project)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            report.warning(f"无法读取 {relative}：{exc}；已跳过。")
            continue
        meta, body = parse_frontmatter(text)
        if not meta:
            report.error(
                f"{relative} 缺少 frontmatter（开头用 --- 包裹的字段块），"
                "不能作为正式文档。"
            )
            continue
        documents.append(
            Document(
                path=path,
                relative=relative,
                meta=meta,
                body=body,
                content=text,
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
        # HEADING_RE 只认一级和二级标题，下级小节不影响本节的结束位置。
        if HEADING_RE.match(lines[index].strip()):
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


def normalize_header(cell: str) -> str:
    return cell.strip().replace(" ", "").replace("*", "").replace("`", "")


def resolve_columns(
    document: Document,
    header: list[str] | None,
    expected: tuple[str, ...],
    label: str,
    report: Report,
) -> dict[str, int] | None:
    """按表头名定位列；表头缺失或列名不符时报告错误，不按列下标猜。"""
    if header is None:
        report.error(f"{document.relative} 的「{label}」小节缺少表格。")
        return None
    normalized = [normalize_header(cell) for cell in header]
    missing = [name for name in expected if normalize_header(name) not in normalized]
    if missing:
        actual = " | ".join(cell.strip() for cell in header)
        report.error(
            f"{document.relative} 的「{label}」表头缺少列：{'、'.join(missing)}；"
            f"实际表头：{actual}。"
        )
        return None
    return {name: normalized.index(normalize_header(name)) for name in expected}


def table_cell(row: list[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


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


def version_tuple(value: str) -> tuple[int, ...] | None:
    parts = value.split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


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
    if project_version == repo_version:
        return
    project_tuple = version_tuple(project_version)
    repo_tuple = version_tuple(repo_version)
    if project_tuple is not None and repo_tuple is not None and project_tuple > repo_tuple:
        report.warning(
            f"项目模板版本 {project_version} 高于本仓库 VERSION {repo_version}；"
            "本仓库的模板与检查规则可能落后于该项目，请先核对两者的差异，"
            "不要用旧版覆盖项目。"
        )
        return
    report.warning(
        f"项目模板版本 {project_version} 低于本仓库 VERSION {repo_version}；"
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
            report.error(
                f"文档 id 重复：{doc_id} 同时出现在 {paths}。"
                "文档 id 与任务编号是两套命名空间：前者标识文档，后者标识一次任务；"
                "related_tasks 引用的是任务编号。"
            )


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
    empty = [
        name
        for name in REQUIRED_FIELDS
        if name in document.meta and not document.text(name).strip()
    ]
    if empty:
        report.error(
            f"{document.relative} 的必需字段为空：{'、'.join(empty)}。"
        )

    if "document_status" in document.meta:
        status = document.text("document_status").strip()
        if status not in ALLOWED_DOCUMENT_STATUS:
            message = (
                f"{document.relative} 的 document_status 非法：{status or '（空）'}；"
                f"应为 {'、'.join(sorted(ALLOWED_DOCUMENT_STATUS))} 之一。"
            )
            if status in TASK_PROGRESS_WORDS:
                if document.text("type").strip() == "work-snapshot":
                    message += (
                        " 任务进度写在本文件的 task_status 里；"
                        "document_status 只表示文档的有效性。"
                    )
                else:
                    message += (
                        " 任务进度写在工作接续快照的 task_status 里；"
                        "document_status 只表示文档的有效性。"
                    )
            report.error(message)
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
        elif not is_real_date(updated_at):
            report.error(
                f"{document.relative} 的 updated_at 不是有效日期：{updated_at}。"
            )


def is_real_date(value: str) -> bool:
    """格式已是 YYYY-MM-DD，再确认日历上真有这一天。"""
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True



def extract_link_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")].strip()
    parts = target.split()
    return parts[0] if parts else ""


def check_local_links(document: Document, project: Path, report: Report) -> None:
    body = INLINE_CODE_RE.sub("", strip_fenced_code(document.body))
    for match in LINK_RE.finditer(body):
        target = extract_link_target(match.group(1))
        if not target or "{{" in target:
            continue
        if target.lower().startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_part = unquote(target.split("#", 1)[0].split("?", 1)[0]).strip()
        if not path_part:
            continue
        if link_target_exists(document, project, path_part):
            continue
        report.error(
            f"{document.relative} 的本地 Markdown 链接目标不存在：{target}；"
            "按文档所在目录和项目根目录都没找到。"
        )


def link_target_exists(document: Document, project: Path, path_part: str) -> bool:
    """链接先按文档所在目录解析；不含 .. 时再按项目根目录解析。"""
    if path_part.startswith("/"):
        return (project / path_part.lstrip("/")).exists()
    if (document.path.parent / path_part).exists():
        return True
    if ".." in Path(path_part).parts:
        return False
    return (project / path_part).exists()


# ---------------------------------------------------------------------------
# 敏感信息扫描
# ---------------------------------------------------------------------------

# 模板和示例里的占位写法，一律放过。
PLACEHOLDER_MARKERS = (
    "xxx",
    "***",
    "your_",
    "your-",
    "<",
    ">",
    "{{",
    "${",
    "example",
    "placeholder",
    "待填写",
)
PLACEHOLDER_WORDS = {
    "",
    "无",
    "暂无",
    "空",
    "none",
    "null",
    "nil",
    "true",
    "false",
    "todo",
    "tbd",
}

# (名称, 正则, 取值分组)。匹配到即报错，报错前打码。
# 新增要高置信抓取的格式，就往这个元组里加一条，并在
# tests/test_check_task.py 的敏感信息测试里补对应样例；正则别写得太宽，宁窄勿滥。
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    (
        "私钥块",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?"
            r"-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"
        ),
        0,
    ),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0),
    ("GitHub Token", re.compile(r"\bgh[po]_[A-Za-z0-9]{20,}\b"), 0),
    ("Slack Token", re.compile(r"\bxox[a-z]-[A-Za-z0-9-]{10,}\b"), 0),
    ("sk- 密钥", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), 0),
    (
        "JWT",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
        ),
        0,
    ),
    (
        "Bearer Token",
        re.compile(r"\bBearer[ \t]+([A-Za-z0-9\-._~+/]{24,}=*)"),
        1,
    ),
)

# 键名前用 (?<![A-Za-z0-9]) 而不是 \b：DB_PASSWORD、AWS_SECRET_ACCESS_KEY
# 这类带下划线前缀的环境变量也能命中；后面的 \b 仍然挡住 tokenizer 之类的词尾。
ASSIGNMENT_RE = re.compile(
    r"(?<![A-Za-z0-9])(password|passwd|secret|api[_-]?key|apikey|token|"
    r"access[_-]?key|client[_-]?secret)\b\s*[:=]\s*[\"'`]?([^\s\"'`]{6,})[\"'`]?",
    re.IGNORECASE,
)


def is_placeholder_secret(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in PLACEHOLDER_WORDS:
        return True
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def mask_secret(value: str) -> str:
    """最多露前四位，其余打码；输出里绝不放密钥原文。"""
    if len(value) <= 4:
        return "*" * len(value)
    return value[:4] + "…（已打码）"


def scan_secrets(document: Document, report: Report) -> None:
    content = document.content
    flagged_lines: set[int] = set()
    for label, pattern, group in SECRET_PATTERNS:
        for match in pattern.finditer(content):
            value = match.group(group)
            if is_placeholder_secret(value):
                continue
            line = content.count("\n", 0, match.start(group)) + 1
            flagged_lines.add(line)
            report.error(
                f"{document.relative}:{line} 发现疑似泄露（{label}）："
                f"{mask_secret(value)}。请删除或改用占位符。"
            )
    for match in ASSIGNMENT_RE.finditer(content):
        key = match.group(1)
        value = match.group(2).rstrip(",.;；。")
        if is_placeholder_secret(value):
            continue
        line = content.count("\n", 0, match.start(2)) + 1
        if line in flagged_lines:
            continue
        report.warning(
            f"{document.relative}:{line} 疑似敏感赋值（{key}）："
            f"{mask_secret(value)}；请确认不是真实密钥。"
        )


# ---------------------------------------------------------------------------
# 任务变更记录内容
# ---------------------------------------------------------------------------


def check_impact_table(document: Document, lines: list[str], report: Report) -> None:
    header, rows = parse_table(lines)
    data_rows = [row for row in rows if has_any_content(row)]
    if not data_rows:
        report.error(f"{document.relative} 的「文档影响判断」表无数据行。")
        return
    columns = resolve_columns(
        document, header, IMPACT_HEADERS, "文档影响判断", report
    )
    if columns is None:
        return
    conclusion_index = columns[IMPACT_HEADERS[1]]
    target_index = columns[IMPACT_HEADERS[0]]
    reason_index = columns[IMPACT_HEADERS[2]]
    for row in data_rows:
        conclusion = table_cell(row, conclusion_index)
        target = table_cell(row, target_index)
        reason = table_cell(row, reason_index)
        if conclusion in ("待填写", ""):
            report.error(
                f"{document.relative} 的「文档影响判断」仍为“待填写”。"
            )
        elif conclusion not in ALLOWED_CONCLUSIONS:
            report.error(
                f"{document.relative} 的「文档影响判断」结论非法：{conclusion}；"
                "应为“已更新”或“检查后无需更新”。"
            )
        elif conclusion == "已更新" and not target:
            report.warning(
                f"{document.relative} 的「文档影响判断」结论为“已更新”，"
                "但没写更新的文档或类型，无法核实。"
            )
        elif conclusion == "检查后无需更新" and reason in ("", "待填写"):
            report.warning(
                f"{document.relative} 的「文档影响判断」结论为“检查后无需更新”，"
                "但未写无需更新的理由。"
            )


def normalize_cell_text(cell: str) -> str:
    return cell.strip().strip("`").strip()


def looks_like_document_path(
    cell: str,
    document: Document,
    project: Path,
    changed: list[str],
) -> bool:
    """带链接、以 .md 结尾、或在项目里真实存在，才当作文档路径。"""
    text = normalize_cell_text(cell)
    if LINK_RE.search(text):
        return True
    if text.endswith(".md"):
        return True
    changed_set = set(changed)
    for candidate in impact_path_candidates(text, document, project):
        if candidate in changed_set or (project / candidate).exists():
            return True
    return False


def type_name_parts(cell: str) -> list[str]:
    return [
        name
        for name in (type_name_of(part) for part in cell.split("/"))
        if name
    ]


def type_name_of(cell: str) -> str:
    name = normalize_cell_text(cell)
    if name.endswith("文档"):
        name = name[: -len("文档")].strip()
    return name


def changed_for_type(name: str, changed: list[str]) -> bool | None:
    """判断本次改动是否涉及某种文档类型；未知类型返回 None。"""
    spec = next((item for item in DOC_TYPES if item.name == name), None)
    if spec is None:
        return None
    if spec.starter:
        directory = (Path("docs") / Path(spec.starter).parent).as_posix()
        return any(
            path == directory or path.startswith(directory + "/")
            for path in changed
        )
    return any(path == "docs/CHANGELOG.md" for path in changed)


def impact_path_candidates(
    cell: str, document: Document, project: Path
) -> list[str]:
    """把影响判断里的文档写法换算成项目相对路径，供改动集合比对。"""
    raw = normalize_cell_text(cell)
    link = LINK_RE.search(raw)
    if link:
        raw = extract_link_target(link.group(1))
    raw = unquote(raw.split("#", 1)[0].split("?", 1)[0]).strip()
    if not raw:
        return []
    plain = raw.replace("\\", "/")
    while plain.startswith("./"):
        plain = plain[2:]
    plain = plain.lstrip("/")
    candidates: list[str] = [plain]
    if raw.startswith("/"):
        bases = [project]
    else:
        bases = [document.path.parent, project]
    for base in bases:
        try:
            candidates.append(
                (base / raw.lstrip("/")).resolve().relative_to(project).as_posix()
            )
        except (OSError, ValueError):
            continue
    return list(dict.fromkeys(candidates))


def reconcile_impact_table(
    document: Document,
    project: Path,
    changed: list[str],
    revision: str,
    report: Report,
) -> None:
    """核对“已更新”的说法：声明的文档或类型必须在本次改动里出现。"""
    lines = section_lines(document.body, "文档影响判断")
    if lines is None:
        return
    header, rows = parse_table(lines)
    # 表头问题由 check_impact_table 报，这里不重复报。
    columns = resolve_columns(
        document, header, IMPACT_HEADERS, "文档影响判断", Report()
    )
    if columns is None:
        return
    changed_set = set(changed)
    for row in rows:
        if not has_any_content(row):
            continue
        conclusion = table_cell(row, columns[IMPACT_HEADERS[1]])
        if conclusion != "已更新":
            continue
        target = table_cell(row, columns[IMPACT_HEADERS[0]])
        if not target:
            # 空目标已由 check_impact_table 警告，这里不重复报。
            continue
        if looks_like_document_path(target, document, project, changed):
            candidates = impact_path_candidates(target, document, project)
            if any(path in changed_set for path in candidates):
                continue
            shown = candidates[0] if candidates else target
            report.error(
                f"{document.relative} 的「文档影响判断」写“已更新”，"
                f"但 {shown} 不在本次改动中。"
                f"只对比 {revision} 之后的改动，ref 选早了会误报。"
            )
            continue
        names = type_name_parts(target)
        known = [name for name in names if changed_for_type(name, changed) is not None]
        if not names or len(known) != len(names):
            report.warning(
                f"{document.relative} 的「文档影响判断」第一列“{target}”"
                "既不是文档路径，也不是已知文档类型，无法核实。"
            )
            continue
        missing = [name for name in names if not changed_for_type(name, changed)]
        if missing:
            listed = "、".join(f"「{name}」" for name in missing)
            report.error(
                f"{document.relative} 的「文档影响判断」写“已更新”，"
                f"但本次改动没有任何{listed}类型的文档。"
                f"只对比 {revision} 之后的改动，ref 选早了会误报。"
            )


def check_verification_table(
    document: Document, lines: list[str], report: Report
) -> None:
    header, rows = parse_table(lines)
    data_rows = [
        row
        for row in rows
        if any(cell.strip() and cell.strip() != "待填写" for cell in row)
    ]
    if not data_rows:
        report.error(f"{document.relative} 的「验证」表无数据行。")
        return
    columns = resolve_columns(
        document, header, VERIFICATION_HEADERS, "验证", report
    )
    if columns is None:
        return
    result_index = columns["结果"]
    reason_index = columns["未运行原因与影响"]
    for row in data_rows:
        result = table_cell(row, result_index)
        reason = table_cell(row, reason_index)
        if result in ("", "待填写"):
            report.error(
                f"{document.relative} 的「验证」表结果仍为“待填写”，"
                "不能作为验证已完成或未完成的依据。"
            )
            continue
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


@dataclass(frozen=True)
class DocumentArea:
    """document-map.yml 中的一个代码区域及其相关正式文档。"""

    path: str
    docs: tuple[str, ...]


GLOB_CHARS = ("*", "?")


def looks_like_glob(pattern: str) -> bool:
    return any(char in pattern for char in GLOB_CHARS)


def glob_to_regex(pattern: str) -> str:
    """把 glob 转成正则：* 只在一段路径内，** 跨目录，? 是一个字符。"""
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    parts.append("(?:.*/)?")
                    index += 1
                else:
                    parts.append(".*")
                continue
            parts.append("[^/]*")
        elif char == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(char))
        index += 1
    return "".join(parts)


def normalize_map_path(value: str) -> str:
    """统一成项目相对的 posix 路径，去掉开头的 ./ 和结尾的 /。"""
    path = value.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.rstrip("/")


def area_matches(area_path: str, changed_path: str) -> bool:
    """目录按前缀匹配，glob 按通配匹配。"""
    pattern = normalize_map_path(area_path)
    changed = normalize_map_path(changed_path)
    if not pattern or not changed:
        return False
    if looks_like_glob(pattern):
        return re.fullmatch(glob_to_regex(pattern), changed) is not None
    return changed == pattern or changed.startswith(pattern + "/")


def parse_document_map(text: str) -> tuple[list[DocumentArea], bool]:
    """尽量解析 document-map.yml 的 areas 块，返回 (区域列表, 是否无法解析)。"""
    lines = text.splitlines()
    in_areas = False
    areas_indent = 0
    item_indent: int | None = None
    docs_indent: int | None = None
    malformed = False
    areas: list[DocumentArea] = []
    current_path = ""
    current_docs: list[str] = []

    def flush() -> None:
        nonlocal current_path, current_docs
        if current_path or current_docs:
            areas.append(DocumentArea(current_path, tuple(current_docs)))
        current_path, current_docs = "", []

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

        if stripped.startswith("- ") and (item_indent is None or indent == item_indent):
            flush()
            item_indent = indent
            indent += 2
            stripped = stripped[2:].strip()
        elif item_indent is None:
            malformed = True
            continue
        elif indent <= item_indent:
            break

        if docs_indent is not None:
            # 列表项可以比 docs: 深一层，也可以和它同缩进。
            if indent >= docs_indent and stripped.startswith("- "):
                item = unquote_value(strip_yaml_comment(stripped[2:]))
                if item:
                    current_docs.append(item)
                continue
            docs_indent = None

        match = re.match(r"^-?\s*path:\s*(.*)$", stripped)
        if match:
            value = unquote_value(strip_yaml_comment(match.group(1).strip()))
            if not value:
                malformed = True
            current_path = value
            continue

        match = re.match(r"^-?\s*docs:\s*(.*)$", stripped)
        if not match:
            if re.match(r"^-?\s*docs\s*\{", stripped):
                malformed = True
            continue
        rest = unquote_value(strip_yaml_comment(match.group(1).strip()))
        if not rest:
            docs_indent = indent
            continue
        if rest.startswith("{"):
            malformed = True
            continue
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            if inner:
                for item in inner.split(","):
                    item = unquote_value(item)
                    if item:
                        current_docs.append(item)
            continue
        current_docs.append(rest)

    if in_areas:
        flush()
    return areas, malformed


def check_document_map(project: Path, report: Report) -> list[DocumentArea] | None:
    """检查对应表里登记的文档是否存在，返回解析出的区域。

    对应表缺失时返回空列表；读不了或解析失败时返回 None，调用方据此跳过提示。
    """
    map_file = project / "docs/document-map.yml"
    if not map_file.exists():
        return []
    try:
        text = map_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report.warning(f"无法读取 docs/document-map.yml：{exc}；已跳过。")
        return None

    areas, malformed = parse_document_map(text)
    if malformed:
        report.warning(
            "docs/document-map.yml 的 areas 结构无法解析，已跳过文档对应关系检查。"
        )
        return None

    seen: set[str] = set()
    for area in areas:
        for entry in area.docs:
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
    return areas


def changed_files(project: Path, revision: str) -> list[str]:
    """取相对某个 Git 版本的改动文件，含未跟踪文件。"""
    git = shutil.which("git")
    if not git:
        raise UsageError("未找到 git 命令，无法比较改动。")
    verify = subprocess.run(
        [git, "-C", str(project), "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if verify.returncode != 0:
        raise UsageError(f"无法识别 Git 版本：{revision}")

    def run(*arguments: str) -> str:
        result = subprocess.run(
            [git, "-c", "core.quotepath=off", "-C", str(project), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise UsageError(f"git {' '.join(arguments)} 失败：{message}")
        return result.stdout

    names: set[str] = set()
    for output in (
        run("diff", "--name-only", revision, "--"),
        run("ls-files", "--others", "--exclude-standard"),
    ):
        for line in output.splitlines():
            line = line.strip()
            if line:
                names.add(line)
    return sorted(names)


def hint_affected_documents(
    changed: list[str],
    areas: list[DocumentArea],
    report: Report,
) -> None:
    """按对应表提示改动可能影响哪些文档；只提示，不判定。"""
    covered: set[str] = set()
    for area in areas:
        if not area.path:
            continue
        hits = [path for path in changed if area_matches(area.path, path)]
        if not hits:
            continue
        covered.update(hits)
        docs = [
            document
            for document in dict.fromkeys(area.docs)
            if document and "{{" not in document
        ]
        if not docs:
            report.warning(f"改动命中区域 {area.path}，但该区域没有登记文档。")
            continue
        report.warning(
            f"改动命中区域 {area.path}，可能影响文档：{'、'.join(docs)}。"
        )
    unregistered = [
        path
        for path in changed
        if path not in covered and not path.startswith(DOCS_PREFIX)
    ]
    if unregistered:
        report.warning(
            "改动的文件未登记在 docs/document-map.yml 的区域中，建议补充 path 与 docs："
            + "、".join(unregistered)
            + "。"
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


def check_related_tasks(
    documents: list[Document],
    all_ids: dict[str, list[Document]],
    report: Report,
) -> None:
    """related_tasks 要指向实际存在的任务编号；只警告，不阻止。

    任务编号在项目内会出现在任务变更记录的 id 和各文档的 related_tasks 里，
    这里只要求至少有一份文档以它为 id，挡住拼写错误和已删除的任务。
    快照除外：工作接续快照本就可能先于任务变更记录出现。
    """
    reported: set[str] = set()
    for document in documents:
        if document.text("type").strip() in SNAPSHOT_TYPES:
            continue
        for task_id in document.items("related_tasks"):
            if task_id in all_ids or task_id in reported:
                continue
            reported.add(task_id)
            report.warning(
                f"{document.relative} 的 related_tasks 指向不存在的任务编号："
                f"{task_id}；项目内没有以它为 id 的文档，核对是否拼写错误。"
            )


def run_checks(
    project: Path,
    task_id: str | None,
    report: Report,
    changed_from: str | None = None,
) -> None:
    check_version(project, report)
    documents = scan_documents(project, report)
    all_ids = document_ids(documents)

    check_duplicate_ids(documents, report)
    check_custom_types(documents, report)
    check_related_tasks(documents, all_ids, report)

    # 字段和链接对所有正式文档生效，不只对任务相关文档生效。
    for document in documents:
        check_document_fields(document, project, all_ids, report)
        check_local_links(document, project, report)

    secret_scope = (
        documents
        if task_id is None
        else [
            document
            for document in documents
            if is_task_related(document, task_id)
        ]
    )
    for document in secret_scope:
        scan_secrets(document, report)

    changed: list[str] | None = None
    if changed_from:
        changed = changed_files(project, changed_from)

    if task_id is not None:
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
        for document in records:
            check_task_change_content(document, report)
            if changed is not None and changed_from is not None:
                reconcile_impact_table(
                    document, project, changed, changed_from, report
                )
    elif changed is not None:
        report.warning(
            "未指定任务号，没有核对影响判断中的“已更新”；"
            "用任务号运行才会对账。"
        )

    areas = check_document_map(project, report)
    if changed is not None and areas is not None:
        hint_affected_documents(changed, areas, report)


def print_report(report: Report, scope: str) -> int:
    for message in report.errors:
        print(f"错误：{message}")
    for message in report.warnings:
        print(f"警告：{message}")
    if report.errors:
        print(
            f"错误：{scope}检查未通过，"
            f"共 {len(report.errors)} 个错误、{len(report.warnings)} 个警告。"
        )
        return 1
    print(f"通过：{scope}检查通过，无错误（{len(report.warnings)} 个警告）。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(
        description="检查接入项目的正式文档，或只检查某个任务的记录。"
    )
    parser.add_argument("project", type=Path, help="接入项目的根目录")
    parser.add_argument(
        "task_id",
        nargs="?",
        default=None,
        help="任务编号，例如 TASK-001；省略时检查全部正式文档",
    )
    parser.add_argument(
        "--changed-from",
        metavar="REV",
        default=None,
        help="相对某个 Git 版本（如 HEAD）列出改动可能影响的文档",
    )
    args = parser.parse_args(argv)

    if args.task_id is not None and not args.task_id.strip():
        print("错误：任务编号不能为空。")
        return 2
    task_id = args.task_id.strip() if args.task_id is not None else None
    try:
        project = prepare_project(args.project)
    except UsageError as exc:
        print(f"错误：{exc}")
        return 2

    report = Report()
    try:
        run_checks(project, task_id, report, args.changed_from)
    except UsageError as exc:
        print(f"错误：{exc}")
        return 2
    scope = f"任务 {task_id} " if task_id else "全部文档"
    return print_report(report, scope)


if __name__ == "__main__":
    sys.exit(main())
