#!/usr/bin/env python3
"""比较项目 docs/_templates 中的模板副本与系统的最新模板，只读输出差异。"""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "templates" / "documents"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
SYSTEM_YML = Path("docs") / "system.yml"
LOCAL_TEMPLATES = Path("docs") / "_templates"


def git_root(target: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def read_system_version(path: Path) -> str | None:
    """从 docs/system.yml 读取 system_version，容忍简单引号。"""
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*system_version\s*:\s*(.*)$", line)
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        return value or None
    return None


def render_diff(project_text: str, system_text: str, name: str) -> list[str]:
    return list(
        difflib.unified_diff(
            project_text.splitlines(),
            system_text.splitlines(),
            fromfile=f"项目当前模板 {LOCAL_TEMPLATES.as_posix()}/{name}",
            tofile=f"系统模板 {name}",
            lineterm="",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="目标 Git 项目根目录")
    parser.add_argument(
        "--check",
        action="store_true",
        help="模板有差异或缺失时以退出码 1 失败；单纯版本较旧不会失败",
    )
    args = parser.parse_args()

    project = args.project.resolve()
    if not project.is_dir():
        print(f"错误：项目目录不存在：{project}", file=sys.stderr)
        return 2
    if not shutil.which("git"):
        print("错误：未找到 git 命令，无法确认项目是否为 Git 根目录。", file=sys.stderr)
        return 2
    if git_root(project) != project:
        print(f"错误：目标目录必须是 Git 项目根目录：{project}", file=sys.stderr)
        return 2

    system_yml = project / SYSTEM_YML
    templates_dir = project / LOCAL_TEMPLATES
    if not system_yml.is_file():
        print(f"错误：项目缺少 {SYSTEM_YML.as_posix()}：{project}", file=sys.stderr)
        return 2
    if not templates_dir.is_dir():
        print(
            f"错误：项目缺少 {LOCAL_TEMPLATES.as_posix()}/：{project}",
            file=sys.stderr,
        )
        return 2

    project_version = read_system_version(system_yml)
    if project_version is None:
        print(
            f"错误：无法从 {SYSTEM_YML.as_posix()} 读取 system_version：{project}",
            file=sys.stderr,
        )
        return 2

    system_templates = {path.name: path for path in sorted(DOCUMENTS.glob("*.md"))}
    local_templates = {path.name: path for path in sorted(templates_dir.glob("*.md"))}

    same = different = missing = custom = 0
    for name, system_path in system_templates.items():
        local_path = templates_dir / name
        if not local_path.is_file():
            missing += 1
            print(
                f"缺失：{LOCAL_TEMPLATES.as_posix()}/{name}"
                f"（项目没有该模板，系统模板为 templates/documents/{name}）"
            )
            continue
        system_bytes = system_path.read_bytes()
        local_bytes = local_path.read_bytes()
        if local_bytes == system_bytes:
            same += 1
            continue
        different += 1
        print(f"不同：{LOCAL_TEMPLATES.as_posix()}/{name}")
        lines = render_diff(
            local_bytes.decode("utf-8", errors="replace"),
            system_bytes.decode("utf-8", errors="replace"),
            name,
        )
        for line in lines:
            print(line)
        print()

    for name in local_templates:
        if name not in system_templates:
            custom += 1
            print(
                f"项目自定义模板：{LOCAL_TEMPLATES.as_posix()}/{name}"
                "（系统 templates/documents 无同名模板，不在比较范围内）"
            )

    print(
        f"对照结果：一致 {same} 个，不同 {different} 个，缺失 {missing} 个，"
        f"项目自定义 {custom} 个。"
    )
    if project_version == VERSION:
        print(f"模板版本：项目 {project_version}，系统 {VERSION}（一致）。")
    else:
        print(
            f"模板版本：项目 {project_version}，系统 {VERSION}"
            "（不一致：项目可暂留旧版，审阅差异后自行更新 docs/system.yml）。"
        )
    print("本命令只读，未修改任何文件。请人工合并差异；采用新版本后自行更新 docs/system.yml 的 system_version。")

    if args.check and (different or missing):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
