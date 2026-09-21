"""Workspace Git coordination, using only Python 3.11+ and Git."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args], text=True, capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.rstrip("\n")


def read_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def normalized_url(url: str) -> str:
    # Treat GitHub-style SSH and HTTPS clone URLs as the same identity.
    url = url.removesuffix("/").removesuffix(".git")
    if url.startswith("git@"):
        url = url[4:].replace(":", "/", 1)
    for prefix in ("https://", "http://", "ssh://git@"):
        url = url.removeprefix(prefix)
    return url


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        config = read_toml(self.root / "repos.toml")
        self.repos = config["repos"]
        names, paths = set(), set()
        for repo in self.repos:
            path = (self.root / repo["path"]).resolve()
            if path == self.root or not path.is_relative_to(self.root):
                raise ValueError(f"Repository path escapes workspace: {repo['path']}")
            if repo["name"] in names or path in paths:
                raise ValueError("Duplicate repository name or path")
            if any(path.is_relative_to(p) or p.is_relative_to(path) for p in paths):
                raise ValueError("Repository paths must not contain each other")
            names.add(repo["name"])
            paths.add(path)
        self.core = next(r for r in self.repos if r["name"] == config["core"])
        if "source" in self.core:
            raise ValueError("Core must have its own URL and initial branch")
        self.repos = [self.core] + [r for r in self.repos if r != self.core]

    def path(self, repo: dict) -> Path:
        return self.root / repo["path"]

    def target(self, repo: dict) -> dict:
        if "source" not in repo:
            return {"git": repo["url"], "branch": repo.get("branch")}
        project = read_toml(self.path(self.core) / "pyproject.toml")
        source = project["tool"]["uv"]["sources"][repo["source"]]
        if not isinstance(source, dict) or "git" not in source:
            raise ValueError(f"{repo['name']}: expected a Git source in core pyproject.toml")
        if "rev" in source or "tag" in source:
            raise ValueError(f"{repo['name']}: revision/tag source requires explicit handling")
        return source

    def verify(self, repo: dict, target: dict) -> None:
        path = self.path(repo)
        if not (path / ".git").exists():
            raise ValueError("Path exists but is not an independent Git checkout")
        if Path(git(path, "rev-parse", "--show-toplevel")).resolve() != path.resolve():
            raise ValueError("Path is not the repository root")
        origin = git(path, "remote", "get-url", "origin")
        if normalized_url(origin) != normalized_url(target["git"]):
            raise ValueError("Origin does not match configured source; inspect git remote -v")

    def setup(self, dry_run: bool = False) -> int:
        failures = 0
        for repo in self.repos:
            name, path = repo["name"], self.path(repo)
            try:
                relative = Path(repo["path"])
                if relative.parts[0] == "repos" and not path.exists():
                    legacy = self.root.joinpath(*relative.parts[1:])
                    if legacy.exists():
                        raise ValueError("Existing checkout is at the legacy path; run poe organize first to avoid duplicate clones")
                if dry_run and "source" in repo and not (self.path(self.core) / "pyproject.toml").exists():
                    print(f"PLAN {name}: resolve source after cloning core")
                    continue
                target = self.target(repo)
                if path.exists():
                    self.verify(repo, target)
                    print(f"KEEP {name}: existing checkout unchanged")
                    continue
                if path.is_symlink():
                    raise ValueError("Destination is a broken symlink")
                branch = target.get("branch")
                print(f"{'PLAN' if dry_run else 'CLONE'} {name}: {branch or 'remote default branch'}", flush=True)
                if dry_run:
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                args = ["clone"]
                if branch:
                    args.extend(["--branch", branch])
                args.extend(["--", target["git"], str(path)])
                git(self.root, *args)
            except (ValueError, OSError, KeyError) as exc:
                print(f"ERROR {name}: {exc}", file=sys.stderr)
                failures += 1
                if repo == self.core:
                    break
        print("Setup preserves existing branches, files, and environments. Run status to review alignment.")
        return int(failures > 0)

    def locked_revisions(self) -> dict:
        lock = self.path(self.core) / "uv.lock"
        if not lock.exists():
            return {}
        result = {}
        for package in read_toml(lock).get("package", []):
            url = package.get("source", {}).get("git", "")
            if "#" in url:
                result[package["name"].replace("_", "-")] = url.rsplit("#", 1)[1]
        return result

    def status(self) -> list[dict]:
        locked = self.locked_revisions()
        rows = []
        for repo in self.repos:
            row = {"repo": repo["name"], "path": repo["path"], "issues": []}
            rows.append(row)
            path = self.path(repo)
            try:
                target = self.target(repo)
                row["expected"] = target.get("branch") or "remote default (unpinned)"
                if not path.exists():
                    row["issues"].append("missing checkout")
                    continue
                self.verify(repo, target)
                row["head"] = git(path, "rev-parse", "HEAD")
                row["branch"] = git(path, "branch", "--show-current") or "DETACHED"
                # Keep status entries intact, including spaces in filenames.
                changes = git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all")
                row["dirty"] = bool(changes)
                row["changes"] = changes.split("\0") if changes else []
                if row["dirty"]:
                    row["issues"].append("uncommitted files")
                if target.get("branch") and row["branch"] != target["branch"]:
                    row["issues"].append("branch mismatch")
                elif row["branch"] == "DETACHED":
                    row["issues"].append("detached HEAD")
                try:
                    row["upstream"] = git(path, "rev-parse", "--abbrev-ref", "@{upstream}")
                    ahead, behind = git(path, "rev-list", "--left-right", "--count", "HEAD...@{upstream}").split()
                    row["ahead"], row["behind"] = int(ahead), int(behind)
                except ValueError:
                    row["upstream"] = None
                    row["issues"].append("no upstream")
                row["locked"] = locked.get(repo.get("source", "").replace("_", "-"))
                if row["locked"]:
                    row["lock_matches_head"] = row["locked"] == row["head"]
                fetch_head = Path(git(path, "rev-parse", "--git-path", "FETCH_HEAD"))
                if not fetch_head.is_absolute():
                    fetch_head = path / fetch_head
                row["last_fetch_timestamp"] = fetch_head.stat().st_mtime if fetch_head.exists() else None
            except (ValueError, OSError, KeyError) as exc:
                row["issues"].append(str(exc))
            # Strip the final separator emitted by porcelain -z.
            row["changes"] = [entry for entry in row.get("changes", []) if entry]
        return rows

    def align(self, names: list[str], force: bool = False, dry_run: bool = False) -> int:
        """Fetch, align, pull dependencies, then rebuild repository Python environments."""
        unknown = set(names) - {repo["name"] for repo in self.repos}
        if unknown:
            raise ValueError(f"Unknown repositories: {', '.join(sorted(unknown))}")
        plans = []
        failures = []
        for repo in self.repos:
            if names and repo["name"] not in names:
                continue
            try:
                if "source" not in repo:
                    if names:
                        raise ValueError("Not a dependency declared by core; align leaves this repository alone")
                    continue
                target = self.target(repo)
                branch = target.get("branch")
                self.verify(repo, target)
                path = self.path(repo)
                if not dry_run:
                    print(f"FETCH {repo['name']}: origin", flush=True)
                    git(path, "fetch", "--no-recurse-submodules", "origin")
                if not branch:
                    branch = git(path, "branch", "--show-current")
                    if not branch:
                        raise ValueError("Core does not specify a branch and HEAD is detached; select a branch first")
                    print(f"KEEP BRANCH {repo['name']}: {branch} (core does not specify a branch)")
                git(path, "check-ref-format", "--branch", branch)
                for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "BISECT_START"):
                    marker_path = Path(git(path, "rev-parse", "--git-path", marker))
                    if not marker_path.is_absolute():
                        marker_path = path / marker_path
                    if marker_path.exists():
                        raise ValueError(f"Git operation in progress ({marker}); finish it first")
                current = git(path, "branch", "--show-current") or "DETACHED"
                if current == branch:
                    changes = git(path, "status", "--porcelain=v1", "--untracked-files=no")
                    if force and changes:
                        plans.append((repo, branch, current, False, True))
                    else:
                        print(f"KEEP {repo['name']}: already on {branch}; files unchanged")
                    continue
                try:
                    git(path, "show-ref", "--verify", f"refs/heads/{branch}")
                    create = False
                except ValueError:
                    git(path, "show-ref", "--verify", f"refs/remotes/origin/{branch}")
                    create = True
                # Do not discard work before finding out the branch is occupied.
                for line in git(path, "worktree", "list", "--porcelain").splitlines():
                    if line == f"branch refs/heads/{branch}":
                        raise ValueError(f"Target branch {branch} is checked out in another worktree")
                changes = git(path, "status", "--porcelain=v1", "--untracked-files=no")
                if changes and not force:
                    raise ValueError("Tracked changes present; commit/stash them or explicitly select this repo with --force")
                plans.append((repo, branch, current, create, bool(changes)))
            except (ValueError, OSError, KeyError) as exc:
                failures.append(f"{repo['name']}: {exc}")
        for repo, branch, current, create, discard in plans:
            detail = "create tracking branch" if create else "use existing local branch"
            print(f"PLAN {repo['name']}: {current} -> {branch} ({detail})")
            if discard:
                print("  DISCARD staged and unstaged tracked changes; preserve untracked and ignored files")
        if failures:
            for failure in failures:
                print(f"ERROR {failure}", file=sys.stderr)
            print("Preflight failed; no working files or local branches were changed. Remote refs may have been fetched.")
            return 1
        if dry_run:
            print("Dry run; no files or branches changed. After alignment, all selected dependencies will be pulled (fast-forward only).")
            print("Remote changes, divergence, and file conflicts are checked when applying.")
            for repo in self.repos:
                if (not names or repo["name"] in names) and (self.path(repo) / "pyproject.toml").is_file():
                    print(f"PLAN {repo['name']}: delete root uv.lock, then run uv sync")
            return 0
        completed = []
        for repo, branch, current, create, discard in plans:
            path = self.path(repo)
            try:
                if discard:
                    # Unlike reset --hard, restore doesn't remove unrelated untracked paths.
                    git(path, "restore", "--source=HEAD", "--staged", "--worktree", ":/")
                if current != branch:
                    args = ["switch", "--no-overwrite-ignore"]
                    if create:
                        args.extend(["--track", "-c", branch, f"origin/{branch}"])
                    else:
                        args.extend(["--no-guess", branch])
                    git(path, *args)
                completed.append(repo["name"])
                print(f"ALIGNED {repo['name']}: {branch}", flush=True)
            except (ValueError, OSError) as exc:
                print(f"ERROR {repo['name']}: {exc}", file=sys.stderr)
                if discard:
                    print(f"{repo['name']}: tracked changes were discarded before the switch attempt.")
                print(f"Stopped. Completed: {', '.join(completed) or 'none'}. Remaining repositories unchanged.")
                return 1
        selected = [repo["name"] for repo in self.repos
                    if "source" in repo and (not names or repo["name"] in names)]
        if selected:
            print("Branches aligned. Pulling selected dependencies...", flush=True)
            result = self.pull(selected)
            if result:
                print("Alignment incomplete: some dependencies could not be pulled. See BLOCKED messages above.")
                return result
        result = self.sync_environments(names)
        if result:
            print("Alignment incomplete: Git updates succeeded but environment setup failed. See errors above.")
            return result
        print("Alignment complete: dependency branches match, pulls succeeded, and Python environments were rebuilt.")
        return 0

    def sync_environments(self, names: list[str]) -> int:
        """Re-resolve root Python projects; each keeps its own environment."""
        failures = []
        for repo in self.repos:
            if names and repo["name"] not in names:
                continue
            path = self.path(repo)
            if not (path / "pyproject.toml").is_file():
                print(f"SKIP ENV {repo['name']}: no root pyproject.toml")
                continue
            try:
                self.verify(repo, self.target(repo))
                print(f"SYNC {repo['name']}: delete uv.lock and run uv sync", flush=True)
                sync_repository(path)
            except (ValueError, OSError, KeyError) as exc:
                failures.append(repo["name"])
                print(f"ERROR ENV {repo['name']}: {exc}", file=sys.stderr)
        if failures:
            print(f"Environment failures: {', '.join(failures)}. Successful updates are retained.")
        return int(bool(failures))

    def pull(self, names: list[str], dry_run: bool = False) -> int:
        """Fetch and fast-forward each eligible checkout, processing core first."""
        unknown = set(names) - {repo["name"] for repo in self.repos}
        if unknown:
            raise ValueError(f"Unknown repositories: {', '.join(sorted(unknown))}")
        completed, failed = [], []
        for repo in self.repos:
            if names and repo["name"] not in names:
                continue
            try:
                target = self.target(repo)  # Re-read after pulling core.
                self.verify(repo, target)
                path = self.path(repo)
                branch = git(path, "branch", "--show-current")
                if not branch:
                    raise ValueError("Detached HEAD; select a branch first")
                # Core's manifest branch is a setup default, not a restriction.
                if repo != self.core and target.get("branch") and branch != target["branch"]:
                    raise ValueError(f"Branch mismatch: {branch} != {target['branch']}; run align first")
                for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "BISECT_START"):
                    marker_path = Path(git(path, "rev-parse", "--git-path", marker))
                    if not marker_path.is_absolute():
                        marker_path = path / marker_path
                    if marker_path.exists():
                        raise ValueError(f"Git operation in progress ({marker})")
                if git(path, "status", "--porcelain=v1", "--untracked-files=no"):
                    raise ValueError("Tracked changes present; commit them or use poe align --force to discard dependency edits")
                remote = git(path, "config", "--get", f"branch.{branch}.remote")
                remote_ref = git(path, "config", "--get", f"branch.{branch}.merge")
                if remote != "origin" or remote_ref != f"refs/heads/{branch}":
                    raise ValueError(f"Expected upstream origin/{branch}; inspect branch tracking configuration")
                print(f"{'PLAN' if dry_run else 'PULL'} {repo['name']}: origin/{branch} (fast-forward only)", flush=True)
                if not dry_run:
                    before = git(path, "rev-parse", "HEAD")
                    git(path, "fetch", "--no-recurse-submodules", "origin", remote_ref)
                    # Explicit merge options avoid user pull.rebase/autostash settings.
                    git(path, "-c", "merge.autoStash=false", "merge", "--ff-only", "--no-autostash",
                        "--no-overwrite-ignore", "FETCH_HEAD")
                    after = git(path, "rev-parse", "HEAD")
                    print(f"  {before[:10]} -> {after[:10]}" if before != after else "  Already up to date")
                completed.append(repo["name"])
            except (ValueError, OSError, KeyError) as exc:
                print(f"BLOCKED {repo['name']}: {exc}", file=sys.stderr)
                failed.append(repo["name"])
                if repo == self.core:
                    print("Stopped: core could not be updated; dependency targets may be stale.")
                    break
        print(f"{'Planned' if dry_run else 'Completed'}: {', '.join(completed) or 'none'}. Blocked: {', '.join(failed) or 'none'}.")
        if dry_run:
            print("Dry run is local only; remote divergence and changes to core's dependency targets are checked when applying.")
        return int(bool(failed))

    def fetch(self, names: list[str], dry_run: bool = False) -> int:
        unknown = set(names) - {repo["name"] for repo in self.repos}
        if unknown:
            raise ValueError(f"Unknown repositories: {', '.join(sorted(unknown))}")
        failures = 0
        for repo in self.repos:
            if names and repo["name"] not in names:
                continue
            try:
                self.verify(repo, self.target(repo))
                print(f"{'PLAN' if dry_run else 'FETCH'} {repo['name']}: origin", flush=True)
                if not dry_run:
                    git(self.path(repo), "fetch", "origin")
            except (ValueError, OSError, KeyError) as exc:
                print(f"ERROR {repo['name']}: {exc}", file=sys.stderr)
                failures += 1
        return int(failures > 0)


def organize(root: Path, dry_run: bool = False) -> int:
    """Move legacy checkouts into manifest paths; retain history and local files."""
    workspace = Workspace(root)
    moves = []
    for repo in workspace.repos:
        relative = Path(repo["path"])
        if not relative.parts or relative.parts[0] != "repos":
            raise ValueError(f"Expected a repos/ destination for {repo['name']}")
        old = workspace.root.joinpath(*relative.parts[1:])
        new = workspace.path(repo)
        if old.is_symlink() or new.is_symlink():
            raise ValueError(f"{repo['name']}: symlink checkout requires manual migration")
        if old.exists() and new.exists():
            raise ValueError(f"{repo['name']}: both old and new locations exist; nothing moved")
        if not old.exists():
            print(f"KEEP {repo['name']}: already organized" if new.exists() else f"MISSING {repo['name']}: run poe setup after organizing")
            continue
        if not (old / ".git").is_dir():
            raise ValueError(f"{repo['name']}: expected a standalone clone; linked worktrees need manual migration")
        if Path(git(old, "rev-parse", "--show-toplevel")).resolve() != old.resolve():
            raise ValueError(f"{repo['name']}: old location is not a repository root")
        if git(old, "worktree", "list", "--porcelain").count("worktree ") > 1:
            raise ValueError(f"{repo['name']}: linked worktrees exist; move and repair them explicitly")
        moves.append((repo["name"], old, new))
    for name, old, new in moves:
        print(f"{'PLAN' if dry_run else 'MOVE'} {name}: {old.relative_to(workspace.root)} -> {new.relative_to(workspace.root)}", flush=True)
        if not dry_run:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
    print("Organization preview complete." if dry_run else "Organization complete. Git history and local files were preserved. Rebuild moved Python environments with poe align.")
    return 0


def sync_repository(path: Path) -> None:
    """Equivalent to removing the root lockfile and running uv sync there."""
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv is not installed or not on PATH; lockfile was preserved")
    (path / "uv.lock").unlink(missing_ok=True)
    result = subprocess.run([uv, "sync"], cwd=path)
    if result.returncode:
        raise ValueError(f"uv sync exited with status {result.returncode}; the previous lockfile was removed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Workspace containing repos.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    organize_parser = sub.add_parser("organize", help="Move legacy checkouts under repos/; preserves local changes")
    organize_parser.add_argument("--dry-run", action="store_true")
    setup = sub.add_parser("setup", help="Clone missing repositories, core first")
    setup.add_argument("--dry-run", action="store_true")
    status = sub.add_parser("status", help="Inspect local state; does not fetch")
    status.add_argument("--json", action="store_true")
    status.add_argument("--check", action="store_true", help="Exit nonzero for missing/dirty/mismatched checkouts")
    fetch = sub.add_parser("fetch", help="Fetch origin; never pull or switch")
    fetch.add_argument("repos", nargs="*", help="Optional manifest repository names")
    fetch.add_argument("--dry-run", action="store_true")
    pull = sub.add_parser("pull", help="Fetch and fast-forward configured repositories, core first")
    pull.add_argument("repos", nargs="*", help="Optional manifest repository names")
    pull.add_argument("--dry-run", action="store_true")
    align = sub.add_parser("align", help="Fetch, align, pull, then delete root lockfiles and uv sync Python repositories")
    align.add_argument("repos", nargs="*", help="Optional dependency names; defaults to all core dependencies")
    align.add_argument("--force", action="store_true", help="Discard tracked changes across selected dependencies (all by default), including already aligned ones")
    align.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "organize":
            return organize(args.root, args.dry_run)
        workspace = Workspace(args.root)
        if args.command == "setup":
            return workspace.setup(args.dry_run)
        if args.command == "fetch":
            return workspace.fetch(args.repos, args.dry_run)
        if args.command == "pull":
            return workspace.pull(args.repos, args.dry_run)
        if args.command == "align":
            return workspace.align(args.repos, args.force, args.dry_run)
        rows = workspace.status()
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            print("Repository                  Actual branch           Expected branch                 Upstream +/-    Core lock")
            for row in rows:
                counts = f"+{row['ahead']}/-{row['behind']}" if "ahead" in row else "unknown"
                lock = row.get("locked")
                lock_label = lock[:10] + (" = HEAD" if row["lock_matches_head"] else " != HEAD") if lock else "—"
                print(f"{row['repo']:<27} {row.get('branch', '—'):<23} {row.get('expected', 'unknown'):<31} {counts:<15} {lock_label}")
                for issue in row["issues"]:
                    print(f"  ! {issue}")
                for change in row["changes"]:
                    print(f"    {change}")
            print("\nUpstream counts use cached refs; run fetch to refresh. Core lock is not installed-environment verification.")
        return int(args.check and any(row["issues"] for row in rows))
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def poe_main() -> None:
    """Poe supplies the task name as argv[0]; propagate our exit status."""
    if sys.argv[0] == "test-tools":
        sys.exit(subprocess.call(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v", *sys.argv[1:]],
            cwd=ROOT,
        ))
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    sys.exit(main())
