from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend import updater


def _make_tree(root: Path, version: str, text: str) -> None:
    (root / "backend").mkdir(parents=True, exist_ok=True)
    (root / "backend" / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    (root / "backend" / "main.py").write_text(text, encoding="utf-8")
    (root / "backend" / "updater.py").write_text("", encoding="utf-8")
    (root / "frontend").mkdir(exist_ok=True)
    (root / "frontend" / "index.html").write_text(text, encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_example.py").write_text("", encoding="utf-8")
    (root / "deploy").mkdir(exist_ok=True)
    (root / "deploy" / "install.sh").write_text("", encoding="utf-8")
    (root / "README.md").write_text(text, encoding="utf-8")
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")


class ApplyAndRollbackTests(unittest.TestCase):
    def test_apply_tree_replaces_code_but_preserves_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app = base / "app"
            stage = base / "stage"
            _make_tree(app, "1.1.0", "ancienne")
            _make_tree(stage, "1.2.0", "nouvelle")
            (app / "config").mkdir()
            personal = app / "config" / "config.json"
            personal.write_text('{"location": "local"}\n', encoding="utf-8")

            updater.apply_tree(stage, app)

            self.assertIn("nouvelle", (app / "backend" / "main.py").read_text(encoding="utf-8"))
            self.assertEqual(
                (app / "backend" / "__init__.py").read_text(encoding="utf-8"),
                '__version__ = "1.2.0"\n',
            )
            self.assertEqual(
                personal.read_text(encoding="utf-8"), '{"location": "local"}\n'
            )
            self.assertFalse((app / ".update-new-backend").exists())

    def test_snapshot_and_restore_return_previous_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app = base / "app"
            backup = base / "backup"
            _make_tree(app, "1.1.0", "version stable")
            updater.snapshot(app, backup)
            _make_tree(app, "1.2.0", "version fautive")

            updater.restore_backup(app, backup)

            self.assertIn("version stable", (app / "backend" / "main.py").read_text(encoding="utf-8"))
            self.assertIn(
                '__version__ = "1.1.0"',
                (app / "backend" / "__init__.py").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
