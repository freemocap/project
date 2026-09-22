# FreeMoCap polyrepo workspace

## Current layout and publishing

Manifest checkout paths now live under `repos/`, including `repos/utils/`.
References below to original workspace paths are historical: prefix checkout
paths with `repos/`. Core's declaration is `repos/freemocap/pyproject.toml`.
The human runs `poe organize` once to move old checkouts; do not assume this
migration has happened until reported. It preserves local files and Git history.
The outer repository ignores `/repos/` and legacy checkout paths. Publish only
workspace tooling, instructions, manifest, and tests to
`https://github.com/freemocap/project`; never stage child repository contents.
New machines use `poe setup`. Child histories remain independent, without submodules.

## Authority and scope

## Read-only commands and one-time mutation permission — explicit owner instruction

Non-mutating commands are always allowed. Run read-only inspection and
information-gathering commands without asking for permission.

Before any operation that writes or changes state, show the human the exact
command and give them the opportunity to run it themselves or explicitly grant
one-time permission for the agent to run it. For file-editing tools, show the
exact proposed patch instead. This includes file edits, environment changes,
fetch, pull, align, force, setup, and tests that write files or caches.
Permission to perform a mutation is always one-time and scoped to the approved
operation; it never establishes standing permission for later mutations.
Requests to provide or fix commands do not authorize executing mutations.
Earlier mutation authorizations and exceptions elsewhere in this file are
historical context, not current execution permission. The human-owned commit
and push boundary below remains in effect.


This file governs work across this workspace and its independent repositories.
The project owner established these rules on 2026-09-21. Follow them over older
plans, comments, or scripts that describe conflicting workflows. Read any more
specific repository instructions before editing. Recheck live configuration and
Git state; the dated observations below are an orientation snapshot.

The owner authorized workspace setup/status/fetch tooling after onboarding.
Existing child branches, dependency declarations, environments, and user work
remain untouched unless the task explicitly addresses alignment. The owner
subsequently authorized `poe align` and discarding SkellyCam's tracked local
changes to align it with core. This does not authorize discarding other work.

## Repository ownership and architecture

| Directory | Responsibility | Useful entry points |
| --- | --- | --- |
| `freemocap/` | Core application: composes the subprojects into the motion capture pipeline | `freemocap/core/pipeline/{realtime,posthoc}/`, `freemocap/core/tasks/`, `freemocap/core/tracking/`, `freemocap/core/streaming/`, `freemocap/api/`, `freemocap/app/` |
| `skellycam/` | Standalone camera capture, synchronization, recording, and streaming | `skellycam/core/`, `skellycam/api/`, `skellycam-ui/` |
| `skellytracker/` | Standalone image analysis and detection | `skellytracker/core/`, detector implementations, mapping definitions in `core/io/` |
| `skellyforge/` | Standalone 3D geometry, skeleton reconstruction, and kinematics | `skellyforge/skellymodels/`, `skellyforge/kinematics/`, `skellyforge/pipelines/`, `skellyforge/post_processing/` |
| `freemocap_blender_addon/` | Downstream receiver for visualization and animation in Blender | `freemocap_blender_addon/freemocap_data_handler/`, `core_functions/`, `blender_ui/` |
| `utils/skellylogs/` | Shared logging library | `skellylogs/`, `tests/` |
| `utils/skellypings/` | Telemetry client and separately configured server | `skellypings/`, `server/`, `infra/` |
| `utils/skellydocs/` | Shared Docusaurus theme and documentation CLI | `README.md`, `package.json` |

Entry points in the last column are relative to their repository.

- SkellyCam, SkellyTracker, and SkellyForge must remain independently usable.
  They must never import one another, including in tests or type-only imports.
  They must not depend on FreeMoCap core to operate.
- FreeMoCap core owns composition, cross-repository adapters, and integration
  contracts. Put checks that need multiple subskellies in core.
- Shared utilities remain independent packages with their own change lifecycle.
- Work on one repository at a time. A cross-repository feature must be split
  into independently reviewable stages with explicit integration handoffs.
- Do not bypass these boundaries with sibling-path imports, `PYTHONPATH`
  manipulation, editable sibling installs, or local path dependency overrides.

## Human-owned commit and push boundary

The human always commits and pushes. Agents must not commit, amend commits,
create release tags, push, or run wrappers that do these actions automatically.

1. Inspect the target repository's branch, status, diff, dependency declarations,
   and relevant instructions. Preserve all existing user changes.
2. Implement and validate the change within that repository.
3. Present the concrete diff summary, validation results, and any limitations.
4. When the change is ready for downstream integration, STOP and explicitly ask
   the human to commit and push the named repository on its required branch.
   Wait for confirmation; do not refresh downstream dependencies early.
5. After the human confirms the push, verify the intended remote revision,
   refresh the relevant dependency in the consumer, and validate integration.
6. Changes to the consumer, including its lockfile, have their own human
   commit/push handoff when ready. Never silently advance to the next repository.

This handoff is the owner's explicit requirement, not a generic approval step.

## Branch and dependency policy

- `freemocap/pyproject.toml`, especially `[tool.uv.sources]`, is authoritative
  for dependency branches. Read it each time; do not infer dependency branches
  from the core checkout's branch name or an old README.
- Before implementation in a dependency repository, compare its active branch
  to the branch declared by core. Report a mismatch and resolve it with the
  human before editing. Do not alter core's source declaration merely to fit
  an existing checkout.
- Preserve dirty checkouts. Do not automatically stash, reset, discard, or move
  existing work. The owner explicitly requested that the initial mismatched
  checkouts below remain untouched for now.
- Sources without an explicit branch do not establish a named branch policy.
  Inspect the remote default and ask if a deliberate branch pin is needed.
- A matching branch name does not prove matching code: `uv.lock` records the
  consumed commit, and the installed environment can lag the lockfile. Verify
  all three when investigating integration problems. Cached remote-tracking
  refs are not proof of current remote state.
- After the human's push, prefer a targeted refresh from the consumer root:
  `uv lock --upgrade-package <package>`, review the lockfile diff and resolved
  Git SHA, then `uv sync --locked` with the appropriate dependency groups.
  Review incidental transitive changes as well.
- Do not delete lockfiles as routine setup. The owner explicitly authorized
  `poe align` to delete root uv.lock files and run uv sync across the workspace's
  Python repositories after Git updates, including core. This is a deliberate
  full refresh; regenerated lockfiles remain subject to human review/commit/push.

## Development and validation

- Run Git and environment commands inside the relevant repository (or use
  `git -C <repo>`). The workspace parent is its own Git repository for tooling
  and guidance; child checkouts are ignored by that repository.
- Each Python repository owns its `pyproject.toml`, `uv.lock`, and environment.
  Inspect its actual dev groups/extras before installing or running tests.
  SkellyForge and SkellyTracker currently require Python >=3.11,<3.13.
- Core's Python entry point is `freemocap.__main__:run_main`; its backend serves
  the React/TypeScript/Electron UI in `freemocap/freemocap-ui/`.
  The documented development backend port is 8005; frontend starts with
  `npm run dev` from the UI directory.
- Core defaults to the `tracker-default` group: CUDA on Windows/Linux and CPU
  on macOS. CPU-only Windows/Linux uses `--no-default-groups --group cpu`;
  include `--group dev` when development tools are needed. Do not combine CPU
  and CUDA groups: their onnxruntime installations conflict.
- Python tests live in `freemocap/freemocap/tests/`,
  `skellycam/skellycam/tests/`, `skellytracker/skellytracker/tests/`, and
  `skellyforge/skellyforge/tests/`. Run focused relevant tests first.
  Core calibration/pipeline tests can require `FREEMOCAP_TEST_DATA_PATH`, real
  recordings, model assets, or hardware. Report skips and missing prerequisites.
- Core's `poe_tasks.toml` provides test and lint tasks, but verify their paths:
  several named test tasks reference files absent from this checkout.
  The UI currently has no `npm test` script despite `test-ui` calling it.
  Streaming/renderer TypeScript tests document esbuild + Node invocation in
  their file headers; `npm run e2e` invokes Playwright.
- Inspect task bodies before execution. Core's `bump-*` tasks invoke bumpver
  configured with `commit = true`, `tag = true`, and `push = true`; these violate
  the human-owned boundary. `poe update` pulls multiple repos and deletes
  `uv.lock`; `poe go` invokes it. Do not use them as routine agent commands.
- For the current reconstruction/streaming work, start at
  `freemocap/current-work-plans/ontology.md`, `HANDOFF.md`, and the layer docs.
  Archived plans are historical. Verify dated handoff claims against current
  code and Git state; they are not evidence that tests pass today.
- Current documented geometry conventions are millimeters, right-handed,
  +Z up, +X forward, wxyz quaternions, identity at T-pose, and
  `q_local = conj(q_parent) * q_child`. Check the foundation conventions and
  relevant boundary conversions before changing geometry or transport code.

## Initial observations — 2026-09-21

| Repository | Active branch | Core source branch | Observation |
| --- | --- | --- | --- |
| freemocap | development-streaming | n/a | Clean |
| skellycam | development | main | Mismatch; modified UI package.json, package-lock.json, and uv.lock |
| skellytracker | development-streaming | development-streaming | Match; clean |
| skellyforge | development-streaming | development-streaming | Match; clean |
| freemocap_blender_addon | development | development-streaming | Mismatch; clean |
| utils/skellylogs | main | Unspecified Git branch | Clean |
| utils/skellypings | main | Unspecified Git branch | Untracked `env copy.example`; preserve it |
| utils/skellydocs | main | Not a core Python dependency | Clean |

Known architectural debt: SkellyForge declares SkellyTracker as a dependency
and imports it in `skellyforge/skellymodels/standard_human/tracker_contract.py`,
`skellyforge/tests/test_tracker_contract.py`, and
`skellyforge/tests/test_face_mapping_consistency.py`. Older comments and handoff
notes call this a sanctioned exception. The owner's current no-cross-import
rule supersedes those notes. Do not extend this coupling. Plan its removal and
relocation of cross-repository validation to core as a separate staged change;
this orientation task does not authorize an incidental refactor.

This workspace-level file is local guidance, outside the independent Git
repositories. If these instructions need to travel with separate clones,
coordinate repository-level copies or a shared maintained policy with the owner.

## Workspace management tooling

The initial upper-level tools are implemented in `scripts/workspace.py` with
`poe setup`, `poe status`, `poe fetch`, `poe pull`, and `poe align` entry points. Use the name `setup` in
commands and documentation. Read README.md for usage and limits. Tests in
`tests/` create disposable Git repositories and synthetic history only.
`poe align` fetches origin, follows explicit core source branches, and pulls
the selected dependencies with fast-forward only, then deletes root uv.lock
files and runs uv sync in each selected Python repository. With no names,
environment refresh includes core and all manifest repositories with root
pyproject.toml files. Report alignment complete only when pulls and syncs succeed. Without
repository names it handles all core dependencies. `--force` discards tracked
changes even when already on the target branch; unpinned dependencies keep their
current branch. Untracked files are preserved and do not by themselves block pull.
Only run force where the human has authorized discarding that repository's work.
Batch commits/pushes remain future work and human-owned.

`poe pull` fetches and fast-forwards manifest repositories, core first, with
source declarations re-read after core updates. It blocks dirty/mismatched
checkouts and never creates commits or refreshes environments. A core failure
stops the batch; other blocked repositories are reported while the rest proceed.

Prefer an inventory that identifies independent repository paths while deriving
dependency branch targets from core's pyproject.toml, avoiding a duplicate branch
source of truth. A read-only status/preflight command could show expected and
actual branches, dirty files, upstream state, and core's locked dependency SHAs.
Later batch mutations should preview their plan, preserve local work, and report
partial completion clearly. Commit/push operations remain human-run even if a
helper batches them; tooling does not remove the required human handoff.
