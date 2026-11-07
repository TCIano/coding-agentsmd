"""锁定框架、模板与检查器之间的契约，防止三处各改一处、对不上。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "templates" / "documents"
CONTEXT = ROOT / "CONTEXT.md"
FRAMEWORK = ROOT / "docs" / "framework.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses 在 Python 3.14 需要从 sys.modules 反查模块。
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CHECK = load_module("check_task_contract", ROOT / "scripts" / "check_task.py")
INIT = load_module("init_project_contract", ROOT / "scripts" / "init_project.py")


def template_files() -> list[Path]:
    return sorted(DOCUMENTS.glob("*.md"))


def template_meta(path: Path) -> dict[str, object]:
    meta, _body = CHECK.parse_frontmatter(path.read_text(encoding="utf-8"))
    return meta


class TemplateContractTest(unittest.TestCase):
    def test_document_templates_exist(self) -> None:
        self.assertTrue(template_files(), "templates/documents/ 下没有模板文件。")

    def test_every_template_has_required_fields(self) -> None:
        for path in template_files():
            meta = template_meta(path)
            missing = [name for name in CHECK.REQUIRED_FIELDS if name not in meta]
            self.assertEqual(missing, [], f"{path.name} 缺少必填字段：{missing}")

    def test_every_template_type_is_builtin(self) -> None:
        for path in template_files():
            doc_type = str(template_meta(path).get("type", "")).strip()
            self.assertIn(
                doc_type,
                CHECK.BUILTIN_TYPES,
                f"{path.name} 的 type“{doc_type}”不在 BUILTIN_TYPES 中。",
            )

    def test_template_document_status_is_allowed(self) -> None:
        for path in template_files():
            status = str(template_meta(path).get("document_status", "")).strip()
            self.assertIn(
                status,
                CHECK.ALLOWED_DOCUMENT_STATUS,
                f"{path.name} 的 document_status“{status}”不在允许值中。",
            )

    def test_task_template_has_expected_table_headers(self) -> None:
        text = (DOCUMENTS / "task-change.md").read_text(encoding="utf-8")
        for header in CHECK.IMPACT_HEADERS + CHECK.VERIFICATION_HEADERS:
            self.assertIn(
                header,
                text,
                f"templates/documents/task-change.md 缺少检查器要求的表头列“{header}”。",
            )

    def test_every_template_has_starter(self) -> None:
        expected = {path.name for path in template_files()}
        self.assertEqual(
            set(INIT.STARTERS),
            expected,
            "init_project.py 的 STARTERS 与 templates/documents/ 不一致。",
        )


class GlossaryContractTest(unittest.TestCase):
    def test_impact_conclusions_match_glossary(self) -> None:
        text = CONTEXT.read_text(encoding="utf-8")
        line = next(
            (
                item
                for item in text.splitlines()
                if item.startswith("**文档影响判断**")
            ),
            "",
        )
        self.assertTrue(line, "CONTEXT.md 缺少「文档影响判断」条目。")
        for conclusion in CHECK.ALLOWED_CONCLUSIONS:
            self.assertIn(
                conclusion,
                line,
                f"术语表未使用检查器认可的结论“{conclusion}”。",
            )
        self.assertNotIn(
            "需要更新",
            line,
            "术语表仍写「需要更新」，与检查器的结论枚举冲突。",
        )



def framework_mapping_rows() -> list[list[str]]:
    """读取 framework.md 中「类型标识与模板」表的行。"""
    lines = FRAMEWORK.read_text(encoding="utf-8").splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("| 中文类型名")),
        None,
    )
    if start is None:
        return []
    rows: list[list[str]] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


class FrameworkMappingContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = framework_mapping_rows()
        self.mapping = {
            cells[1]: cells[2] for cells in self.rows if len(cells) == 3
        }

    def test_mapping_table_exists(self) -> None:
        self.assertTrue(
            self.rows, "docs/framework.md 缺少「类型标识与模板」映射表。"
        )
        self.assertEqual(
            len(self.rows),
            len(CHECK.BUILTIN_TYPES),
            f"映射表 {len(self.rows)} 行，BUILTIN_TYPES {len(CHECK.BUILTIN_TYPES)} 个。",
        )

    def test_mapping_covers_builtin_types(self) -> None:
        self.assertEqual(
            set(self.mapping),
            set(CHECK.BUILTIN_TYPES),
            "映射表的 type 值与 BUILTIN_TYPES 不一致。",
        )

    def test_mapping_template_paths_exist(self) -> None:
        for doc_type, template in self.mapping.items():
            self.assertTrue(
                (ROOT / template).is_file(),
                f"映射表中 {doc_type} 的模板路径不存在：{template}",
            )

    def test_document_templates_match_mapping(self) -> None:
        for path in template_files():
            relative = path.relative_to(ROOT).as_posix()
            self.assertIn(
                relative,
                self.mapping.values(),
                f"模板 {relative} 未登记在框架映射表中。",
            )
            doc_type = str(template_meta(path).get("type", "")).strip()
            self.assertEqual(
                self.mapping.get(doc_type),
                relative,
                f"模板 {relative} 的 type“{doc_type}”在映射表中指向了别的文件。",
            )


if __name__ == "__main__":
    unittest.main()
