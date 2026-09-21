"""Layout migration tests operate only on disposable local repositories."""
import contextlib
import io
import unittest

import test_workspace as fixtures


class OrganizeTests(unittest.TestCase):
    setUp = fixtures.WorkspaceTests.setUp
    setup_workspace = fixtures.WorkspaceTests.setup_workspace

    def set_new_layout(self):
        content = self.manifest.replace('path = "core"', 'path = "repos/core"')
        content = content.replace('path = "utils/dep"', 'path = "repos/utils/dep"')
        (self.root / "repos.toml").write_text(content)

    def test_moves_preserve_history_and_local_files_and_are_repeatable(self):
        self.setup_workspace()
        (self.root / "utils/dep/hello.txt").write_text("local tracked work")
        (self.root / "utils/dep/untracked.txt").write_text("keep")
        before = fixtures.command(self.root / "utils/dep", "rev-parse", "HEAD")
        self.set_new_layout()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fixtures.module.organize(self.root, dry_run=True), 0)
        self.assertFalse((self.root / "repos").exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fixtures.module.organize(self.root), 0)
            self.assertEqual(fixtures.module.organize(self.root), 0)
        dep = self.root / "repos/utils/dep"
        self.assertEqual(fixtures.command(dep, "rev-parse", "HEAD"), before)
        self.assertEqual((dep / "hello.txt").read_text(), "local tracked work")
        self.assertEqual((dep / "untracked.txt").read_text(), "keep")
        self.assertFalse((self.root / "core").exists())

    def test_collision_prevents_all_moves(self):
        self.setup_workspace()
        self.set_new_layout()
        (self.root / "repos/utils/dep").mkdir(parents=True)
        with self.assertRaises(ValueError):
            fixtures.module.organize(self.root)
        self.assertTrue((self.root / "core/.git").exists())
        self.assertFalse((self.root / "repos/core").exists())

    def test_setup_refuses_duplicate_legacy_clones(self):
        self.setup_workspace()
        self.set_new_layout()
        workspace = fixtures.module.Workspace(self.root)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(workspace.setup(), 1)
        self.assertFalse((self.root / "repos").exists())
