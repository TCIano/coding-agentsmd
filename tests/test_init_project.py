from pathlib import Path
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "init_project.py"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def load_init_module():
    spec = importlib.util.spec_from_file_location("init_project_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载初始化脚本：{SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


INIT_MODULE = load_init_module()


class InitProjectTest(unittest.TestCase):
    def run_init(self, target: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(target), "--name", "示例项目"],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_creates_local_templates_and_noncurrent_starters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(["git", "init", "-q", str(target)], check=True)

            result = self.run_init(target)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("# 示例项目", (target / "README.md").read_text())
            self.assertEqual(
                (target / "docs/_templates/bug.md").read_bytes(),
                (ROOT / "templates/documents/bug.md").read_bytes(),
            )
            self.assertIn(
                "document_status: 草稿",
                (target / "docs/bugs/_draft.md").read_text(),
            )
            self.assertIn(
                f'system_version: "{VERSION}"',
                (target / "docs/system.yml").read_text(),
            )
            self.assertTrue((target / "docs/attachments/.gitkeep").exists())

    def test_existing_file_stops_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            (target / "README.md").write_text("已有说明", encoding="utf-8")

            result = self.run_init(target)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((target / "README.md").read_text(), "已有说明")
            self.assertFalse((target / "docs").exists())

    def test_requires_project_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_init(Path(directory))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(directory) / "docs").exists())

    def test_rendered_files_have_no_unreplaced_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(["git", "init", "-q", str(target)], check=True)

            result = self.run_init(target)

            self.assertEqual(result.returncode, 0, result.stderr)
            for path in target.rglob("*"):
                if not path.is_file() or ".git" in path.parts:
                    continue
                relative = path.relative_to(target)
                if relative.parts[:2] == ("docs", "_templates"):
                    continue
                self.assertNotIn("{{", path.read_text(encoding="utf-8"), relative)

    def test_unreplaced_placeholder_exits_2_without_writing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            stderr = io.StringIO()
            with (
                patch.object(
                    INIT_MODULE,
                    "build_files",
                    return_value={Path("README.md"): "{{UNRESOLVED}}"},
                ),
                patch.object(
                    sys,
                    "argv",
                    [str(SCRIPT), str(target), "--name", "示例项目"],
                ),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                INIT_MODULE.main()

            self.assertEqual(raised.exception.code, 2)
            self.assertIn("未写入任何文件", stderr.getvalue())
            self.assertEqual({path.name for path in target.iterdir()}, {".git"})


if __name__ == "__main__":
    unittest.main()
