"""Integration tests use disposable Git repositories; no real checkouts change."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("workspace", Path(__file__).resolve().parents[1] / "scripts/workspace.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def command(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True, stderr=subprocess.PIPE).strip()


def fixture_repo(path, files):
    path.mkdir()
    command(path, "init", "-b", "main")
    for name, content in files.items():
        (path / name).write_text(content)
    command(path, "add", ".")
    # Synthetic test history only, inside TemporaryDirectory.
    command(path, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "Fixture")
    return command(path, "rev-parse", "HEAD")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="freemocap-workspace-tests-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / "workspace with spaces"
        self.root.mkdir()
        self.dep = base / "dependency remote"
        sha = fixture_repo(self.dep, {"hello.txt": "original"})
        self.core = base / "core remote"
        fixture_repo(self.core, {
            "pyproject.toml": '[tool.uv.sources]\ndep = { git = ' + json.dumps(str(self.dep)) + ', branch = "main" }\n',
            "uv.lock": '[[package]]\nname = "dep"\nsource = { git = ' + json.dumps(str(self.dep) + '#'+sha) + ' }\n',
        })
        self.manifest = ('core = "core"\n[[repos]]\nname = "core"\npath = "core"\nurl = '
                         + json.dumps(str(self.core)) + '\nbranch = "main"\n'
                         + '[[repos]]\nname = "dep"\npath = "utils/dep"\nsource = "dep"\n')
        (self.root / "repos.toml").write_text(self.manifest)
        self.workspace = module.Workspace(self.root)
        # Git workflow tests do not install packages or access package indexes.
        sync_patch = patch.object(self.workspace, "sync_environments", return_value=0)
        sync_patch.start()
        self.addCleanup(sync_patch.stop)

    def setup_workspace(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.workspace.setup(), 0)

    def test_fresh_setup_uses_core_sources_and_independent_histories(self):
        self.setup_workspace()
        rows = self.workspace.status()
        self.assertTrue(all(not row["issues"] for row in rows))
        self.assertTrue(rows[1]["lock_matches_head"])
        self.assertNotEqual(rows[0]["head"], rows[1]["head"])

    def test_rerun_preserves_dirty_mismatched_checkout(self):
        self.setup_workspace()
        dep = self.root / "utils/dep"
        command(dep, "switch", "-c", "other")
        (dep / "hello.txt").write_text("user work")
        before = command(dep, "status", "--porcelain")
        self.setup_workspace()
        self.assertEqual(command(dep, "status", "--porcelain"), before)
        self.assertEqual((dep / "hello.txt").read_text(), "user work")
        row = self.workspace.status()[1]
        self.assertIn("branch mismatch", row["issues"])
        self.assertTrue(row["dirty"])

    def test_setup_refuses_existing_nonrepository(self):
        (self.root / "core").mkdir()
        (self.root / "core/precious.txt").write_text("keep")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.workspace.setup(), 1)
        self.assertEqual((self.root / "core/precious.txt").read_text(), "keep")
        self.assertFalse((self.root / "utils/dep").exists())

    def test_dry_setup_does_not_create_checkouts(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.workspace.setup(True), 0)
        self.assertFalse((self.root / "core").exists())
        self.assertFalse((self.root / "utils").exists())

    def test_fetch_updates_refs_without_changing_head_or_files(self):
        self.setup_workspace()
        dep = self.root / "utils/dep"
        before = command(dep, "rev-parse", "HEAD")
        (dep / "hello.txt").write_text("user work")
        (self.dep / "hello.txt").write_text("remote update")
        command(self.dep, "add", ".")
        command(self.dep, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-m", "Remote fixture update")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.workspace.fetch(["dep"], True), 0)
        self.assertEqual(self.workspace.status()[1]["behind"], 0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.workspace.fetch(["dep"]), 0)
        self.assertEqual(command(dep, "rev-parse", "HEAD"), before)
        self.assertEqual((dep / "hello.txt").read_text(), "user work")
        self.assertEqual(self.workspace.status()[1]["behind"], 1)

    def test_wrong_origin_is_rejected(self):
        self.setup_workspace()
        command(self.root / "utils/dep", "remote", "set-url", "origin", str(self.core))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.workspace.setup(), 1)
            self.assertEqual(self.workspace.fetch(["dep"]), 1)

    def test_manifest_cannot_escape_workspace(self):
        (self.root / "repos.toml").write_text(self.manifest.replace('path = "utils/dep"', 'path = "../escape"'))
        with self.assertRaises(ValueError):
            module.Workspace(self.root)

    def test_unknown_fetch_selection_is_rejected(self):
        with self.assertRaises(ValueError):
            self.workspace.fetch(["typo"])

    def test_check_reports_drift_and_json_is_parseable(self):
        self.setup_workspace()
        (self.root / "utils/dep/untracked file.txt").write_text("keep")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = module.main(["--root", str(self.root), "status", "--json", "--check"])
        self.assertEqual(result, 1)
        self.assertTrue(json.loads(output.getvalue())[1]["dirty"])

    def prepare_alignment(self):
        self.setup_workspace()
        dep = self.root / "utils/dep"
        command(dep, "switch", "-c", "other")
        return dep

    def commit_fixture_change(self, path, filename="hello.txt", content="remote update"):
        (path / filename).write_text(content)
        command(path, "add", filename)
        command(path, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-m", "Fixture update")

    def run_pull(self, names=None, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self.workspace.pull(names or [], **kwargs)

    def test_pull_fast_forwards_and_dry_run_does_not_fetch(self):
        self.setup_workspace()
        dep = self.root / "utils/dep"
        before = command(dep, "rev-parse", "HEAD")
        self.commit_fixture_change(self.dep)
        self.assertEqual(self.run_pull(dry_run=True), 0)
        self.assertEqual(command(dep, "rev-parse", "HEAD"), before)
        self.assertEqual(command(dep, "rev-parse", "origin/main"), before)
        self.assertEqual(self.run_pull(), 0)
        self.assertEqual(command(dep, "rev-parse", "HEAD"), command(self.dep, "rev-parse", "HEAD"))

    def test_pull_preserves_dirty_files_and_rejects_mismatch(self):
        dep = self.prepare_alignment()
        self.assertEqual(self.run_pull(["dep"]), 1)
        command(dep, "switch", "main")
        (dep / "untracked.txt").write_text("keep")
        self.commit_fixture_change(self.dep)
        self.assertEqual(self.run_pull(["dep"]), 0)
        self.assertEqual((dep / "untracked.txt").read_text(), "keep")
        self.assertEqual(command(dep, "rev-parse", "HEAD"), command(self.dep, "rev-parse", "HEAD"))
        (dep / "untracked.txt").unlink()
        (dep / "hello.txt").write_text("keep tracked")
        self.assertEqual(self.run_pull(["dep"]), 1)
        self.assertEqual((dep / "hello.txt").read_text(), "keep tracked")

    def test_pull_refuses_divergence_even_with_rebase_configured(self):
        self.setup_workspace()
        dep = self.root / "utils/dep"
        self.commit_fixture_change(dep, content="local change")
        self.commit_fixture_change(self.dep)
        before = command(dep, "rev-parse", "HEAD")
        command(dep, "config", "pull.rebase", "true")
        self.assertEqual(self.run_pull(["dep"]), 1)
        self.assertEqual(command(dep, "rev-parse", "HEAD"), before)
        self.assertEqual(command(dep, "status", "--porcelain"), "")

    def test_pull_rechecks_targets_after_core_update(self):
        self.setup_workspace()
        command(self.dep, "branch", "next")
        project = self.core / "pyproject.toml"
        self.commit_fixture_change(self.core, "pyproject.toml", project.read_text().replace('branch = "main"', 'branch = "next"'))
        dep = self.root / "utils/dep"
        before = command(dep, "rev-parse", "HEAD")
        self.assertEqual(self.run_pull(), 1)
        self.assertEqual(command(self.root / "core", "rev-parse", "HEAD"), command(self.core, "rev-parse", "HEAD"))
        self.assertEqual(command(dep, "rev-parse", "HEAD"), before)

    def test_pull_core_failure_stops_dependents(self):
        self.setup_workspace()
        self.commit_fixture_change(self.dep)
        with (self.root / "core/pyproject.toml").open("a") as stream:
            stream.write("\n# local tracked edit\n")
        dep = self.root / "utils/dep"
        before = command(dep, "rev-parse", "HEAD")
        self.assertEqual(self.run_pull(), 1)
        self.assertEqual(command(dep, "rev-parse", "origin/main"), before)

    def test_pull_rejects_unknown_names_and_wrong_upstream(self):
        self.setup_workspace()
        with self.assertRaises(ValueError):
            self.workspace.pull(["typo"])
        dep = self.root / "utils/dep"
        command(dep, "config", "branch.main.merge", "refs/heads/other")
        self.assertEqual(self.run_pull(["dep"]), 1)

    def run_align(self, names=None, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self.workspace.align(names or [], **kwargs)

    def test_align_refuses_dirty_checkout_without_force(self):
        dep = self.prepare_alignment()
        (dep / "hello.txt").write_text("user work")
        self.assertEqual(self.run_align(), 1)
        self.assertEqual(command(dep, "branch", "--show-current"), "other")
        self.assertEqual((dep / "hello.txt").read_text(), "user work")

    def test_force_align_discards_staged_and_unstaged_changes_preserves_untracked(self):
        dep = self.prepare_alignment()
        (dep / "hello.txt").write_text("staged work")
        command(dep, "add", "hello.txt")
        (dep / "hello.txt").write_text("unstaged work")
        (dep / "local.txt").write_text("keep")
        self.assertEqual(self.run_align(["dep"], force=True), 0)
        self.assertEqual(command(dep, "branch", "--show-current"), "main")
        self.assertEqual((dep / "hello.txt").read_text(), "original")
        self.assertEqual((dep / "local.txt").read_text(), "keep")
        self.assertEqual(command(dep, "diff", "--cached"), "")

    def test_force_defaults_to_all_dependencies(self):
        dep = self.prepare_alignment()
        (dep / "hello.txt").write_text("discard")
        self.assertEqual(self.run_align(force=True), 0)
        self.assertEqual(command(dep, "branch", "--show-current"), "main")
        self.assertEqual((dep / "hello.txt").read_text(), "original")

    def test_force_cleans_already_aligned_repository(self):
        self.setup_workspace()
        dep = self.root / "utils/dep"
        before = command(dep, "rev-parse", "HEAD")
        (dep / "hello.txt").write_text("staged change")
        command(dep, "add", "hello.txt")
        (dep / "hello.txt").write_text("unstaged change")
        (dep / "local.txt").write_text("keep")
        self.assertEqual(self.run_align(["dep"], force=True, dry_run=True), 0)
        self.assertEqual((dep / "hello.txt").read_text(), "unstaged change")
        self.assertEqual(self.run_align(["dep"], force=True), 0)
        self.assertEqual((dep / "hello.txt").read_text(), "original")
        self.assertEqual(command(dep, "diff", "--cached"), "")
        self.assertEqual(command(dep, "rev-parse", "HEAD"), before)
        self.assertEqual((dep / "local.txt").read_text(), "keep")

    def test_force_dry_run_preserves_changes_and_branch(self):
        dep = self.prepare_alignment()
        (dep / "hello.txt").write_text("user work")
        self.assertEqual(self.run_align(["dep"], force=True, dry_run=True), 0)
        self.assertEqual(command(dep, "branch", "--show-current"), "other")
        self.assertEqual((dep / "hello.txt").read_text(), "user work")

    def test_align_creates_missing_local_tracking_branch(self):
        dep = self.prepare_alignment()
        command(dep, "branch", "-D", "main")
        self.assertEqual(self.run_align(), 0)
        self.assertEqual(command(dep, "branch", "--show-current"), "main")
        self.assertEqual(command(dep, "rev-parse", "--abbrev-ref", "@{upstream}"), "origin/main")

    def test_missing_target_does_not_discard_changes(self):
        dep = self.prepare_alignment()
        (dep / "hello.txt").write_text("keep")
        project = self.root / "core/pyproject.toml"
        project.write_text(project.read_text().replace('branch = "main"', 'branch = "missing"'))
        self.assertEqual(self.run_align(["dep"], force=True), 1)
        self.assertEqual((dep / "hello.txt").read_text(), "keep")

    def test_existing_target_commit_is_not_reset(self):
        dep = self.prepare_alignment()
        command(dep, "switch", "main")
        (dep / "hello.txt").write_text("local target commit")
        command(dep, "add", ".")
        command(dep, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-m", "Local fixture commit")
        target_sha = command(dep, "rev-parse", "HEAD")
        command(dep, "switch", "other")
        self.assertEqual(self.run_align(), 0)
        self.assertEqual(command(dep, "rev-parse", "HEAD"), target_sha)

    def test_unpinned_sources_keep_current_branch_and_pull(self):
        dep = self.prepare_alignment()
        command(self.dep, "branch", "other")
        command(dep, "fetch", "origin")
        command(dep, "branch", "--set-upstream-to=origin/other", "other")
        project = self.root / "core/pyproject.toml"
        project.write_text(project.read_text().replace(', branch = "main"', ''))
        self.assertEqual(self.run_align(), 0)
        self.assertEqual(command(dep, "branch", "--show-current"), "other")

    def test_align_refuses_core(self):
        self.setup_workspace()
        self.assertEqual(self.run_align(["core"]), 1)

    def test_align_refuses_target_in_another_worktree_before_discard(self):
        dep = self.prepare_alignment()
        command(dep, "worktree", "add", str(self.root / "other-worktree"), "main")
        (dep / "hello.txt").write_text("keep")
        self.assertEqual(self.run_align(["dep"], force=True), 1)
        self.assertEqual((dep / "hello.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
