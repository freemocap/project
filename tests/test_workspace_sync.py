"""Verify lock refresh ordering and failure handling without running uv."""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_workspace as fixtures

module = fixtures.module


class SyncRepositoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        (self.path / "uv.lock").write_text("old lock")

    def test_removes_lock_before_sync_in_repository_directory(self):
        def sync(args, cwd):
            self.assertEqual(args, ["/fake/uv", "sync"])
            self.assertEqual(cwd, self.path)
            self.assertFalse((cwd / "uv.lock").exists())
            (cwd / "uv.lock").write_text("new lock")
            return SimpleNamespace(returncode=0)
        with patch.object(module.shutil, "which", return_value="/fake/uv"), patch.object(module.subprocess, "run", side_effect=sync):
            module.sync_repository(self.path)
        self.assertEqual((self.path / "uv.lock").read_text(), "new lock")

    def test_missing_uv_preserves_lock(self):
        with patch.object(module.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "lockfile was preserved"):
                module.sync_repository(self.path)
        self.assertEqual((self.path / "uv.lock").read_text(), "old lock")

    def test_sync_failure_is_reported(self):
        with patch.object(module.shutil, "which", return_value="/fake/uv"), patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError, "status 1"):
                module.sync_repository(self.path)


class EnvironmentSelectionTests(unittest.TestCase):
    setUp = fixtures.WorkspaceTests.setUp
    setup_workspace = fixtures.WorkspaceTests.setup_workspace

    def test_includes_core_and_dependency_with_root_python_projects(self):
        self.setup_workspace()
        dep = self.root / "utils/dep"
        (dep / "pyproject.toml").write_text('[project]\nname="dep"\nversion="0.0.1"\n')
        with patch.object(module, "sync_repository") as sync, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.Workspace.sync_environments(self.workspace, []), 0)
        self.assertEqual([call.args[0] for call in sync.call_args_list], [self.root / "core", dep])

    def test_no_root_project_is_skipped(self):
        self.setup_workspace()
        with patch.object(module, "sync_repository") as sync, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.Workspace.sync_environments(self.workspace, ["dep"]), 0)
        sync.assert_not_called()
