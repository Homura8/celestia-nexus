import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from nexuslib.cli import positive_seconds, read_build, recipe_for, ROOT
from nexuslib.core import (NexusError, Recorder, active_mirrors, digest, fetch_url, load_lock, load_target,
                           fetch_source, mirror_variable, relative_path, verified_artifact, verify_source)
from nexuslib.hakios import copy_source
from nexuslib.host import clock_support, missing_hint


class CoreTests(unittest.TestCase):
    def test_instruction_clock_rejects_known_hanging_qemu(self):
        for major in (6, 8, 9):
            version = f"QEMU emulator version {major}.2.2 (distribution)"
            self.assertFalse(clock_support(version, "instruction")[0])
            self.assertTrue(clock_support(version, "host")[0])
        self.assertTrue(clock_support("QEMU emulator version 10.0.13", "instruction")[0])
        self.assertFalse(clock_support("unrecognised version", "instruction")[0])

    def test_repository_configuration(self):
        sources = load_lock(ROOT / "upstreams.lock.toml")
        for path in (ROOT / "targets").glob("*/target.toml"):
            target = load_target(path)
            self.assertIn(target["source"], sources)
            recipe_for(target)

    def test_recipe_rejects_untested_cpu_acceleration_and_typos(self):
        target = load_target(ROOT / "targets/qemu-virt-xnu/target.toml")
        for field, value in (("accel", "hvf"), ("cpu", "host"), ("cpus", True), ("cpus", 2),
                             ("memory_mib", 1024), ("clock", "auto"), ("unknown", True)):
            changed = {**target, "qemu": {**target["qemu"], field: value}}
            with self.subTest(field=field, value=value), self.assertRaises(NexusError):
                recipe_for(changed)

    def test_metadata_reader_has_no_qemu_or_arm_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "target.toml"
            path.write_text('schema=1\nid="new-target"\nrecipe="new-recipe"\nsource="new-source"\n'
                            'description="unimplemented experiment"\narchitecture="riscv64"\n')
            self.assertEqual(load_target(path)["architecture"], "riscv64")
            with self.assertRaisesRegex(NexusError, "Unknown recipe"):
                recipe_for(load_target(path))

    def test_paths_cannot_escape(self):
        for value in ("../other", "/tmp/other", "a/../../other", "a\\other", ""):
            with self.subTest(value=value), self.assertRaises(NexusError):
                relative_path(value)

    def test_hash_mismatch_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "kernel").write_bytes(b"good")
            item = {"path": "kernel", "sha256": digest(source / "kernel")}
            self.assertEqual(verified_artifact(source, item), source / "kernel")
            (source / "kernel").write_bytes(b"bad")
            with self.assertRaisesRegex(NexusError, "Hash mismatch"):
                verified_artifact(source, item)
            (root / "outside").write_bytes(b"good")
            (source / "kernel").unlink()
            (source / "kernel").symlink_to(root / "outside")
            with self.assertRaisesRegex(NexusError, "escapes"):
                verified_artifact(source, item)

    def test_failed_command_preserves_returncode_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = Recorder(root / "experiment")
            with self.assertRaises(NexusError):
                record.command([sys.executable, "-c", "print('diagnostic');raise SystemExit(7)"], cwd=root)
            commands = json.loads((record.directory / "commands.json").read_text())
            self.assertEqual(commands[0]["returncode"], 7)
            self.assertIn("diagnostic", (record.directory / commands[0]["log"]).read_text())

    def test_command_timeout_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = Recorder(root / "experiment")
            with self.assertRaisesRegex(NexusError, "timed out"):
                record.command([sys.executable, "-c", "import time;time.sleep(5)"], cwd=root, timeout=0.05)
            commands = json.loads((record.directory / "commands.json").read_text())
            self.assertEqual(commands[0]["error"], "timeout")

    def test_partial_fetch_does_not_poison_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "upstream"
            repo.mkdir()
            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()
            git("init")
            (repo / "file").write_text("source")
            git("add", "file")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "base")
            source = {"id": "example", "commit": git("rev-parse", "HEAD"), "url": str(root / "missing")}
            first = Recorder(root / "first")
            with self.assertRaises(NexusError):
                fetch_source(root, source, first)
            self.assertFalse((root / "sources/example").exists())
            self.assertTrue((first.directory / "fetch-example/.git").exists())
            source["url"] = str(repo)
            second = Recorder(root / "second")
            path = fetch_source(root, source, second)
            verify_source(path, source)
            self.assertEqual((path / "file").read_text(), "source")

    def test_overlay_does_not_follow_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "input").write_text("source")
            tree = root / "tree"
            tree.mkdir()
            with self.assertRaises(NexusError):
                copy_source(root / "input", root / "escape", tree)
            (root / "link").symlink_to(root / "input")
            with self.assertRaises(NexusError):
                copy_source(root / "link", tree / "output", tree)

    def test_malformed_build_records_are_actionable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "build.json"
            for content in ("not-json", "{}", '{"schema": 1, "artifacts": []}'):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaisesRegex(NexusError, "Cannot read build record"):
                    read_build(path)

    def test_dirty_or_wrong_source_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
            git("init")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "base")
            source = {"id": "test", "commit": git("rev-parse", "HEAD")}
            verify_source(root, source)
            (root / "untracked.c").write_text("do not lose me")
            with self.assertRaisesRegex(NexusError, "changes"):
                verify_source(root, source)
            self.assertTrue((root / "untracked.c").exists())
            with self.assertRaisesRegex(NexusError, "revision"):
                verify_source(root, {**source, "commit": "0" * 40})

    def test_nonfinite_timeout_rejected(self):
        for value in ("nan", "inf", "-inf", "0", "-1", "86401"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                positive_seconds(value)


def make_repo(path: Path, content: str = "source") -> str:
    path.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init")
    (path / "file").write_text(content)
    git("add", "file")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "base")
    return git("rev-parse", "HEAD")


class SourceLocationTests(unittest.TestCase):
    def lock(self, url: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "lock.toml"
        path.write_text(f'schema = 1\n[[upstream]]\nid = "example"\nurl = "{url}"\ncommit = "{"a" * 40}"\n')
        return path

    def test_lock_accepts_public_https_hosts_only(self):
        for url in ("https://github.com/owner/repo.git", "https://gitlab.com/qemu-project/qemu.git",
                    "https://codeberg.org/owner/repo"):
            with self.subTest(url=url):
                self.assertEqual(load_lock(self.lock(url))["example"]["url"], url)
        for url in ("http://github.com/owner/repo.git", "git@github.com:owner/repo.git",
                    "https://user:secret@github.com/owner/repo.git", "https://github.com/owner/repo.git?x=1",
                    "https://github.com:8443/owner/repo.git", "https://github.com", "/local/repo",
                    "ext::sh -c touch% /tmp/pwned"):
            with self.subTest(url=url), self.assertRaises(NexusError):
                load_lock(self.lock(url))

    def test_mirror_variable_name(self):
        self.assertEqual(mirror_variable("apple-xnu"), "NEXUS_MIRROR_APPLE_XNU")

    def test_mirror_override_is_validated_and_reported(self):
        source = {"id": "example", "url": "https://github.com/owner/repo.git", "commit": "a" * 40}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("NEXUS_MIRROR_EXAMPLE", None)
                self.assertEqual(fetch_url(source), source["url"])
                self.assertEqual(active_mirrors({"example": source}), {})
            for value, expected in (("https://gitlab.com/mirror/repo.git", "https://gitlab.com/mirror/repo.git"),
                                    (tmp, str(Path(tmp).resolve())), ("file://" + tmp, str(Path(tmp).resolve()))):
                with self.subTest(value=value), mock.patch.dict(os.environ, {"NEXUS_MIRROR_EXAMPLE": value}):
                    self.assertEqual(fetch_url(source), expected)
                    self.assertEqual(active_mirrors({"example": source}), {"example": expected})
            for value in ("relative/repo", "-uupload-pack=evil", "ext::sh -c id", tmp + "/missing",
                          "ssh://host/repo.git", "https://user:pw@host.example/repo"):
                with self.subTest(value=value), mock.patch.dict(os.environ, {"NEXUS_MIRROR_EXAMPLE": value}):
                    with self.assertRaises(NexusError):
                        fetch_url(source)

    def test_mirror_must_supply_the_locked_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            commit = make_repo(root / "mirror")
            source = {"id": "example", "commit": commit, "url": "https://github.com/owner/missing.git"}
            with mock.patch.dict(os.environ, {"NEXUS_MIRROR_EXAMPLE": str(root / "mirror")}):
                path = fetch_source(root / "work", source, Recorder(root / "first"))
            verify_source(path, source)
            self.assertEqual((path / "file").read_text(), "source")
            make_repo(root / "other", "different")
            wrong = {**source, "id": "wrong"}
            with mock.patch.dict(os.environ, {"NEXUS_MIRROR_WRONG": str(root / "other")}):
                with self.assertRaises(NexusError):
                    fetch_source(root / "work", wrong, Recorder(root / "second"))
            self.assertFalse((root / "work/sources/wrong").exists())

    def test_macos_missing_tool_hints(self):
        self.assertIn("brew install lld", missing_hint("ld64", "Darwin"))
        self.assertIn("brew install lld", missing_hint("lld_link", "Darwin"))
        self.assertIn("brew install llvm", missing_hint("clang", "Darwin"))
        self.assertIn("docs/development.md", missing_hint("ld64", "Linux"))
