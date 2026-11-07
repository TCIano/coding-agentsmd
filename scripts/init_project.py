#!/usr/bin/env python3
"""Copy the versioned documentation starter into a new Git project."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "templates" / "project"
DOCUMENTS = ROOT / "templates" / "documents"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

STARTERS = {
    "requirement.md": ("requirements/_draft.md", "需求"),
    "bug.md": ("bugs/_draft.md", "缺陷"),
    "interface.md": ("interfaces/_draft.md", "接口"),
    "adr.md": ("adr/_draft.md", "设计决定"),
    "task-change.md": ("tasks/_task-change-draft.md", "任务变更记录"),
    "work-snapshot.md": ("tasks/_work-snapshot-draft.md", "工作接续快照"),
    "project-snapshot.md": ("snapshots/_draft.md", "项目状态快照"),
}


def git_root(target: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def render(content: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", value)
    return content


def build_files(project_name: str) -> dict[Path, str]:
    today = date.today().isoformat()
    common = {
        "PROJECT_NAME": project_name,
        "DATE": today,
        "SYSTEM_VERSION": VERSION,
    }
    files: dict[Path, str] = {}

    for source in BASE.rglob("*"):
        if source.is_file():
            files[source.relative_to(BASE)] = render(
                source.read_text(encoding="utf-8"), common
            )

    for source in DOCUMENTS.glob("*.md"):
        content = source.read_text(encoding="utf-8")
        files[Path("docs/_templates") / source.name] = content
        starter_path, label = STARTERS[source.name]
        starter_values = {
            **common,
            "ID": "DRAFT-" + source.stem.upper(),
            "TITLE": "起始草稿：" + label,
            "OWNER": "待填写",
        }
        files[Path("docs") / starter_path] = render(content, starter_values)

    files[Path("docs/attachments/.gitkeep")] = ""
    files[Path("docs/modules/.gitkeep")] = ""
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="目标 Git 项目根目录")
    parser.add_argument("--name", required=True, help="项目名称")
    args = parser.parse_args()

    project = args.project.resolve()
    if not project.is_dir():
        parser.error(f"目标目录不存在：{project}")
    if git_root(project) != project:
        parser.error(f"目标目录必须是 Git 项目根目录：{project}")

    files = build_files(args.name)
    collisions = [str(project / path) for path in files if (project / path).exists()]
    if collisions:
        parser.error("以下文件已存在，未写入任何文件：\n" + "\n".join(collisions))

    for path, content in files.items():
        destination = project / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    print(f"已创建 {len(files)} 个文件：{project}")
    print("起始草稿仍需填写和审核，不能作为项目当前事实。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
