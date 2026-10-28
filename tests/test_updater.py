from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from backend import updater


def _tar_member(name: str, *, data: bytes | None = None, mode: int = 0o644) -> tarfile.TarInfo:
    member = tarfile.TarInfo(name)
    member.mode = mode
    if data is None:
        member.type = tarfile.DIRTYPE
    else:
        member.size = len(data)
    return member


class VersionTests(unittest.TestCase):
    def test_version_tags_are_normalized_and_ordered(self) -> None:
        self.assertEqual(updater.version_from_tag("v1.2.3"), "1.2.3")
        self.assertTrue(updater.is_newer("v1.2.0", "1.1.9"))
        self.assertFalse(updater.is_newer("v1.1.0", "1.1.0"))
        self.assertEqual(
            updater.release_asset_name("pi-dashboard", "v2.0.0"),
            "pi-dashboard-2.0.0.tar.gz",
        )

    def test_invalid_tags_are_rejected(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater.version_from_tag("release-latest")
        with self.assertRaises(updater.UpdateError):
            updater.parse_version("1.2")


class ChecksumTests(unittest.TestCase):
    def test_sha256sum_file_is_parsed(self) -> None:
        digest = "a" * 64
        result = updater.parse_checksums(
            f"# commentaire\n{digest}  pi-dashboard-1.2.0.tar.gz\n"
        )
        self.assertEqual(result["pi-dashboard-1.2.0.tar.gz"], digest)

    def test_invalid_checksum_line_is_rejected(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater.parse_checksums("pas-un-hash  archive.tar.gz\n")


class ArchiveTests(unittest.TestCase):
    def _write_archive(self, path: Path, members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
        with tarfile.open(path, "w:gz") as bundle:
            for member, data in members:
                bundle.addfile(member, io.BytesIO(data) if data is not None else None)

    def test_safe_archive_is_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "release.tar.gz"
            self._write_archive(
                archive,
                [
                    (_tar_member("pi-dashboard-1.1.0/"), None),
                    (
                        _tar_member(
                            "pi-dashboard-1.1.0/backend/__init__.py",
                            data=b'__version__ = "1.1.0"\n',
                        ),
                        b'__version__ = "1.1.0"\n',
                    ),
                ],
            )
            root = updater.safe_extract(archive, tmp_path / "out")
            self.assertEqual(
                (root / "backend" / "__init__.py").read_text(encoding="utf-8"),
                '__version__ = "1.1.0"\n',
            )

    def test_archive_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "release.tar.gz"
            self._write_archive(
                archive,
                [(_tar_member("../outside.txt", data=b"x"), b"x")],
            )
            with self.assertRaises(updater.UpdateError):
                updater.safe_extract(archive, tmp_path / "out")
            self.assertFalse((tmp_path / "outside.txt").exists())

    def test_archive_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "release.tar.gz"
            link = tarfile.TarInfo("pi-dashboard-1.1.0/backend/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../etc/passwd"
            self._write_archive(archive, [(_tar_member("pi-dashboard-1.1.0/"), None), (link, None)])
            with self.assertRaises(updater.UpdateError):
                updater.safe_extract(archive, tmp_path / "out")

    def test_archive_with_two_roots_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "release.tar.gz"
            self._write_archive(
                archive,
                [
                    (_tar_member("one/"), None),
                    (_tar_member("two/"), None),
                ],
            )
            with self.assertRaises(updater.UpdateError):
                updater.safe_extract(archive, tmp_path / "out")


class TreeValidationTests(unittest.TestCase):
    def _make_tree(self, root: Path, version: str = "1.1.0") -> None:
        (root / "backend").mkdir(parents=True)
        (root / "backend" / "__init__.py").write_text(
            f'__version__ = "{version}"\n', encoding="utf-8"
        )
        (root / "backend" / "main.py").write_text("", encoding="utf-8")
        (root / "backend" / "updater.py").write_text("", encoding="utf-8")
        (root / "frontend").mkdir()
        (root / "frontend" / "index.html").write_text("", encoding="utf-8")
        (root / "deploy" / "systemd").mkdir(parents=True)
        (root / "deploy" / "install.sh").write_text("", encoding="utf-8")
        (root / "deploy" / "systemd" / "pi-dashboard.service").write_text("", encoding="utf-8")
        (root / "tests").mkdir()

    def test_release_tree_accepts_matching_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "stage"
            self._make_tree(root)
            updater.validate_release_tree(root, "1.1.0")

    def test_release_tree_rejects_wrong_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "stage"
            self._make_tree(root, version="1.0.0")
            with self.assertRaises(updater.UpdateError):
                updater.validate_release_tree(root, "1.1.0")


class UpdateConfigTests(unittest.TestCase):
    def test_config_is_read_and_defaults_are_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "update.json"
            path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "repository": "compte/pi-dashboard",
                        "channel": "release",
                        "asset_prefix": "pi-dashboard",
                        "checksum_asset": "SHA256SUMS",
                    }
                ),
                encoding="utf-8",
            )
            config = updater.load_update_config(path)
            self.assertTrue(config["enabled"])
            self.assertEqual(config["repository"], "compte/pi-dashboard")

    def test_invalid_repository_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "update.json"
            path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "repository": "pas-un-depot",
                        "channel": "release",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(updater.UpdateError):
                updater.load_update_config(path)


if __name__ == "__main__":
    unittest.main()
