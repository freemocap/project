"""Workspace-wide alignment and preservation of unrelated untracked files."""
import contextlib
import io
import unittest

import test_workspace as fixtures

command = fixtures.command


class BatchWorkflowTests(unittest.TestCase):
    setUp = fixtures.WorkspaceTests.setUp
    setup_workspace = fixtures.WorkspaceTests.setup_workspace
    run_align = fixtures.WorkspaceTests.run_align

    def test_align_fetches_previously_unknown_branch(self):
        self.setup_workspace()
        command(self.dep, "branch", "new-branch")
        project = self.root / "core/pyproject.toml"
        project.write_text(project.read_text().replace('branch = "main"', 'branch = "new-branch"'))
        self.assertEqual(self.run_align(force=True), 0)
        self.assertEqual(command(self.root / "utils/dep", "branch", "--show-current"), "new-branch")

    def test_unpinned_dependency_force_preserves_untracked_file_and_pulls(self):
        self.setup_workspace()
        project = self.root / "core/pyproject.toml"
        project.write_text(project.read_text().replace(', branch = "main"', ''))
        dep = self.root / "utils/dep"
        (dep / "hello.txt").write_text("tracked edit")
        (dep / "env copy.example").write_text("preserve")
        self.assertEqual(self.run_align(force=True), 0)
        self.assertEqual((dep / "hello.txt").read_text(), "original")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.workspace.pull(["dep"]), 0)
        self.assertEqual((dep / "env copy.example").read_text(), "preserve")

    def test_pull_preserves_untracked_collision(self):
        self.setup_workspace()
        dep = self.root / "utils/dep"
        (dep / "new.txt").write_text("local content")
        (self.dep / "new.txt").write_text("remote content")
        command(self.dep, "add", "new.txt")
        command(self.dep, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-m", "Fixture collision")
        before = command(dep, "rev-parse", "HEAD")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.workspace.pull(["dep"]), 1)
        self.assertEqual(command(dep, "rev-parse", "HEAD"), before)
        self.assertEqual((dep / "new.txt").read_text(), "local content")

    def test_align_pulls_already_aligned_dependency(self):
        self.setup_workspace()
        dep = self.root / "utils/dep"
        (self.dep / "hello.txt").write_text("latest remote content")
        command(self.dep, "add", "hello.txt")
        command(self.dep, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-m", "Fixture remote update")
        self.assertEqual(self.run_align(force=True), 0)
        self.assertEqual(command(dep, "rev-parse", "HEAD"), command(self.dep, "rev-parse", "HEAD"))
        self.assertEqual((dep / "hello.txt").read_text(), "latest remote content")
