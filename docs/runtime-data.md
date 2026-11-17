# Runtime data directory

The API and worker default to `<repository-root>/data`, anchored to the backend
source location. Starting from the repository root or `backend/` selects the same
absolute directory.

Set `SIMASSIST_DATA_DIR` to an absolute path in both process environments to select
another directory. Empty and relative values fail configuration validation.

The worker also accepts `--data-root`. This explicit argument takes precedence
over the environment setting. Relative worker arguments resolve against the
invocation's current directory, preserving the previous command-line behavior.
Both processes log their resolved absolute root at startup.

## Existing installations

If `backend/data/` contains entries, startup requires an explicit data-root
selection. The warning names the existing directory and the canonical default.
This guard also applies when only the backend store exists, so startup cannot
silently create a new canonical database in its place.

To continue using the backend store in this checkout, set the following in both
API and worker shells before starting them.

```powershell
$env:SIMASSIST_DATA_DIR = 'C:\Users\tsahi\Projects\simassist\backend\data'
```

Selecting `C:\Users\tsahi\Projects\simassist\data` explicitly uses the repository
store. Each selection exposes the projects and chats in that chosen store.

Phase A changes configuration only. Consolidating existing stores remains a
separate migration requiring stopped writers, backups of both complete roots,
schema reconciliation on copies, database and payload merging, message-ID
remapping with attachment/turn/summary references, hash and relationship checks,
and a coordinated API/worker cutover with rollback copies retained.

## Opt-in development reset

To discard development state, preview the exact targets from any working
directory using the script's full path, or run this from the repository root.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/reset_runtime.ps1
```

After reviewing the preview, stop API and worker and keep them stopped throughout
cleanup. Run the same command with `-Execute` to delete the listed runtime files.
The script checks Windows processes through CIM and refuses deletion if inspection
fails or Python, uv, ASGI, or identifiable SimAssist hosts remain. This conservative
check can also require stopping unrelated Python processes. It never stops them.
The execution-policy option applies only to that PowerShell process.

Only `data/` and `backend/data/` are inspected for deletion. Known runtime layouts
cover SQLite databases and sidecars, UUID-scoped uploads, artifact payloads and
preview caches, and generated workspace outputs. Empty recognized directories
are pruned without recursive deletion. Git-tracked files, `.gitkeep`, unknown
files/directories, and links are protected. Linked roots or ancestors are refused.
Git inspection must succeed before cleanup. External configured roots, benchmark
fixtures in `.benchmarks/`, tooling caches, source, tests and documentation are
outside the reset scope.

The legacy `data/projects/` files have unverified provenance and remain protected.
Review these separately if they should also be discarded. Protected entries in
`backend/data/` may keep the Phase A selection guard active after cleanup.

Before restarting both processes, explicitly select the canonical root in both
launch environments and remove any worker override pointing elsewhere.

```powershell
$env:SIMASSIST_DATA_DIR = 'C:\Users\tsahi\Projects\simassist\data'
```

Repositories create required directories and databases on first use. Review the
API and worker startup logs for this same absolute path. Post-reset acceptance
requires creating a project/chat, generating geometry, uploading/importing STEP,
meshing and remeshing, restarting both processes, and reopening the chat and
artifacts. Confirm new files appear exclusively in the selected `data/` root.
