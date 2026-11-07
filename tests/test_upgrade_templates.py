from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "scripts" / "init_project.py"
UPGRADE = ROOT / "scripts" / "upgrade_templates.py"
SYSTEM_DOCUMENTS = ROOT / "templates" / "documents"
SYSTEM_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


class UpgradeTemplatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.project = Path(self._directory.name)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        init = subprocess.run(
            [sys.executable, str(INIT), str(self.project), "--name", "示例项目"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(init.returncode, 0, init.stderr)

    def run_upgrade(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(UPGRADE), str(self.project), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def local_templates(self) -> dict[str, bytes]:
        root = self.project / "docs" / "_templates"
        return {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_upgrade_script_exists(self) -> None:
        self.assertTrue(UPGRADE.is_file(), "scripts/upgrade_templates.py 尚未实现")

    def test_initialized_project_has_no_differences(self) -> None:
        result = self.run_upgrade()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("一致 7 个", result.stdout)
        self.assertIn("不同 0 个", result.stdout)
        self.assertIn("缺失 0 个", result.stdout)
        self.assertIn("模板版本", result.stdout)
        self.assertIn(SYSTEM_VERSION, result.stdout)
        self.assertNotIn("不同：", result.stdout)
        self.assertNotIn("缺失：", result.stdout)

        check = self.run_upgrade("--check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_modified_template_shows_diff_without_rewriting(self) -> None:
        local = self.project / "docs" / "_templates" / "bug.md"
        local.write_text(
            local.read_text(encoding="utf-8") + "\n项目补充说明\n",
            encoding="utf-8",
        )
        before = self.local_templates()
        system_before = (SYSTEM_DOCUMENTS / "bug.md").read_bytes()

        result = self.run_upgrade()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("不同 1 个", result.stdout)
        self.assertIn("--- 项目当前模板", result.stdout)
        self.assertIn("+++ 系统模板 bug.md", result.stdout)
        # diff 以项目当前模板为旧版、系统模板为新版，项目多出的补充显示为删除行。
        self.assertIn("-项目补充说明", result.stdout)
        self.assertEqual(self.local_templates(), before)
        self.assertEqual((SYSTEM_DOCUMENTS / "bug.md").read_bytes(), system_before)

        check = self.run_upgrade("--check")
        self.assertEqual(check.returncode, 1, check.stdout + check.stderr)

    def test_missing_project_template_is_reported(self) -> None:
        (self.project / "docs" / "_templates" / "adr.md").unlink()

        result = self.run_upgrade()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("缺失：docs/_templates/adr.md", result.stdout)
        self.assertIn("缺失 1 个", result.stdout)

        check = self.run_upgrade("--check")
        self.assertEqual(check.returncode, 1, check.stdout + check.stderr)

    def test_project_custom_template_is_informational(self) -> None:
        custom = self.project / "docs" / "_templates" / "custom.md"
        custom.write_text("# 项目自定义模板\n", encoding="utf-8")

        result = self.run_upgrade("--check")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("项目自定义模板", result.stdout)
        self.assertIn("custom.md", result.stdout)
        self.assertEqual(custom.read_text(encoding="utf-8"), "# 项目自定义模板\n")

    def test_version_mismatch_is_explained_but_does_not_fail_check(self) -> None:
        system_yml = self.project / "docs" / "system.yml"
        text = system_yml.read_text(encoding="utf-8")
        text = text.replace(
            f'system_version: "{SYSTEM_VERSION}"', 'system_version: "0.0.9"'
        )
        self.assertIn('system_version: "0.0.9"', text, "测试需要先制造版本差异")
        system_yml.write_text(text, encoding="utf-8")

        result = self.run_upgrade()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0.0.9", result.stdout)
        self.assertIn(SYSTEM_VERSION, result.stdout)
        self.assertIn("不一致", result.stdout)

        check = self.run_upgrade("--check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_non_git_directory_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(UPGRADE), directory],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Git", result.stderr)

    def test_nonexistent_project_exits_2(self) -> None:
        missing = self.project / "不存在的项目"
        result = subprocess.run(
            [sys.executable, str(UPGRADE), str(missing)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_git_root_without_system_files_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            result = subprocess.run(
                [sys.executable, str(UPGRADE), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("docs/system.yml", result.stderr)

    def test_missing_local_templates_directory_exits_2(self) -> None:
        for path in (self.project / "docs" / "_templates").iterdir():
            path.unlink()
        (self.project / "docs" / "_templates").rmdir()

        result = self.run_upgrade()

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("docs/_templates", result.stderr)


if __name__ == "__main__":
    unittest.main()
