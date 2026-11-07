from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "init_project.py"


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
                'system_version: "0.1.0"',
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


if __name__ == "__main__":
    unittest.main()
