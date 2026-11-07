"""文档类型的唯一出处。

中文类型名、``type`` 值、模板路径和起始草稿只在这里写一次。检查脚本的类型集合
和初始化脚本的起始草稿映射都从这里派生。新增文档类型时，准备模板文件并在这张
表里加一行。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocumentType:
    """一种正式文档的声明。"""

    name: str  # 中文类型名，与框架设计中的表格一致
    type: str  # frontmatter 里的 type 值
    template: str  # 相对仓库根目录的模板路径
    starter: str | None = None  # 起始草稿相对接入项目 docs/ 的路径
    starter_label: str | None = None  # 起始草稿标题里的中文标签


DOC_TYPES: tuple[DocumentType, ...] = (
    DocumentType(
        "需求",
        "requirement",
        "templates/documents/requirement.md",
        "requirements/_draft.md",
        "需求",
    ),
    DocumentType(
        "缺陷",
        "bug",
        "templates/documents/bug.md",
        "bugs/_draft.md",
        "缺陷",
    ),
    DocumentType(
        "接口",
        "interface",
        "templates/documents/interface.md",
        "interfaces/_draft.md",
        "接口",
    ),
    DocumentType(
        "设计决定",
        "adr",
        "templates/documents/adr.md",
        "adr/_draft.md",
        "设计决定",
    ),
    DocumentType(
        "任务变更记录",
        "task-change",
        "templates/documents/task-change.md",
        "tasks/_task-change-draft.md",
        "任务变更记录",
    ),
    DocumentType(
        "工作接续快照",
        "work-snapshot",
        "templates/documents/work-snapshot.md",
        "tasks/_work-snapshot-draft.md",
        "工作接续快照",
    ),
    DocumentType(
        "项目状态快照",
        "project-snapshot",
        "templates/documents/project-snapshot.md",
        "snapshots/_draft.md",
        "项目状态快照",
    ),
    DocumentType(
        "项目变更记录",
        "project-changelog",
        "templates/project/docs/CHANGELOG.md",
    ),
)

BUILTIN_TYPES: frozenset[str] = frozenset(spec.type for spec in DOC_TYPES)

STARTERS: dict[str, tuple[str, str]] = {
    Path(spec.template).name: (spec.starter, spec.starter_label)
    for spec in DOC_TYPES
    if spec.starter and spec.starter_label
}
