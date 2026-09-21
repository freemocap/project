# FreeMoCap project workspace

This repository contains the manifest, commands, tests, and [agent instructions](AGENTS.md).
Application repositories remain independent clones under the ignored `repos/` directory:

```text
project/
├── AGENTS.md
├── README.md
├── repos.toml
├── poe_tasks.toml
├── scripts/
├── tests/
└── repos/                         # ignored by the outer repository
    ├── freemocap/
    ├── skellycam/
    ├── skellytracker/
    ├── skellyforge/
    ├── freemocap_blender_addon/
    └── utils/
        ├── skellylogs/
        ├── skellypings/
        └── skellydocs/
```

No application source is copied into this repository. No submodules are used.
Every child retains its own Git history, remotes, branches, and environment.

## New machine

Prerequisites: Git, Python 3.11+, and uv. Once this workspace is published:

```sh
git clone https://github.com/freemocap/project.git
cd project
uv tool install --python 3.12 'poethepoet==0.46.0'
poe setup
poe align
poe status
```

Follow uv's PATH instructions if `poe` is not found. Poe resolves `python` or
`python3`; that interpreter must be Python 3.11+. Alternatively use
`python3 scripts/workspace.py <command>` (Windows: `py -3.12` if appropriate).

Setup clones core first and reads its Git sources to clone dependencies on the
declared branches. Existing checkouts are preserved. Align installs Python
dependencies; frontend npm installs and nested projects remain separate.
This reproduces the layout and workflow, not an exact historical snapshot:
branch tips move and align intentionally re-resolves Python dependencies.

## Migrate existing checkouts

From the original workspace with application directories at its top level:

```sh
poe organize --dry-run
poe organize
poe status
```

Organize moves the directories without recloning, changing branches, or removing
local files. It preflights all moves, rejects conflicting destinations and linked
worktrees, and can be rerun after partial completion. Stop application processes
first and update editor paths afterward. Legacy paths remain ignored as well.

Moved Python environments may contain launchers with absolute paths. The move
preserves them, but they may require recreation; ordinary uv sync alone does not
guarantee those paths are repaired.

## Commands

Run from the workspace root or use `poe -C /path/to/project <command>`.

| Command | Behavior |
| --- | --- |
| `poe setup` | Clone missing repositories; preserve existing ones |
| `poe organize` | Move legacy top-level checkouts under repos/ |
| `poe status` | Show branches, local changes, cached upstream counts, core lock SHAs |
| `poe status --json` | Structured status with full SHAs |
| `poe status --check` | Nonzero exit for dirty, missing, or mismatched checkouts |
| `poe fetch` | Fetch origin in all manifest repositories |
| `poe pull` | Fetch and fast-forward manifest repositories, core first |
| `poe align` | Fetch, align and pull core dependencies, then refresh Python environments |
| `poe align --force` | Same, discarding tracked dependency edits |
| `poe test-tools` | Run tooling tests using disposable Git repositories and mocked uv installs |

Setup, organize, fetch, pull, and align support `--dry-run`. Fetch, pull, and
align accept optional repository names; normal use needs none. Dry-run and
status use local information and cannot predict newly published remote changes.
Core lock equality does not verify installed packages.

## Alignment and environments

`repos/freemocap/pyproject.toml` owns dependency Git URLs and branch declarations.
The manifest owns directory paths, core's initial branch, and SkellyDocs' source.
Align leaves core's branch and SkellyDocs alone. It fetches dependencies, selects
declared branches, and pulls with fast-forward only. Unpinned dependencies keep
their current branch. Existing local commits remain; divergence is reported.

Force discards staged and unstaged tracked dependency edits, even on an already
aligned branch. It preserves untracked and ignored files, core edits, and local
commits. Unrelated untracked files do not block pull; Git refuses to overwrite
them during switches or merges.

After successful Git updates, align deletes root `uv.lock` files and runs plain
`uv sync`. Without repository names this covers core and every manifest repository
with a root `pyproject.toml`. Named alignment refreshes only that selection.
It skips non-Python roots, nested projects such as SkellyPings' server, and npm
installation. Default dependency groups apply, including core's platform-specific
CUDA/CPU selection; dev extras are not automatically added.

Re-resolved lockfiles may be dirty afterward. The human reviews, commits, and
pushes them. Missing uv preserves the existing lockfile; a failed sync after
deletion can leave a new lockfile or none. Failures return nonzero and report
incomplete alignment. No automatic commits or pushes occur.

## Pull behavior

Pull processes core first and re-reads its source declarations for dependencies.
A core failure stops the batch; other failures are reported while remaining
repositories proceed. Tracked edits, mismatched branches, active Git operations,
or unexpected upstreams block a repository. Pull never rebases, stashes, resets,
commits, or updates environments. Successful changes remain if another pull
fails. The outer workspace itself is not part of the manifest's pull operation.

## Publish the workspace

The human creates and pushes `freemocap/project`. `/repos/` and legacy checkout
paths are ignored. Do not force-add child checkouts. Gitignore does not remove
files already tracked in history. Review the staged file list before committing.

After testing, from the outer workspace:

```sh
git status --short
git add .gitignore AGENTS.md README.md repos.toml poe_tasks.toml scripts tests
git diff --cached --stat
git commit -m "Add FreeMoCap polyrepo workspace tooling"
gh repo create freemocap/project --public --source=. --remote=origin --push
```

The last command requires authenticated GitHub CLI and organization permissions.
It creates a public repo; choose `--private` if appropriate. If the GitHub repo
already exists, add its URL instead (provided origin is not already configured):

```sh
git remote add origin https://github.com/freemocap/project.git
git push -u origin main
```

Publishing the outer repository does not publish child checkout changes. Each
repository has its own human commit/push handoff. Agents edit requested files;
the human runs all commands.
