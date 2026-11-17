# Phase 11.18B — CAD Surface Picking & Topology Inspection

Implemented against HEAD `8b1e168`, verified on Windows on 2026-11-17.
Only CAD inspection and temporary project selection are added. Named selections,
loads, boundary conditions, materials and solvers remain outside this phase.

## Behavior and contracts

- CAD preview tessellation enumerates OCC faces individually. Each triangle has
  an owning `triangle_face_keys` entry; split quadrangles retain the same owner.
- The immutable geometry artifact UUID is `geometry_revision_id`. Face keys have
  the form `<revision UUID>:face:<local tag>`. A local Gmsh tag alone is never a
  selection identity. Existing derived previews retain the mapping for that
  revision; replacing/reimporting geometry creates a different identity.
- OCC supplies area, bounding box and geometric type. Coordinate units come from
  the geometry job; STEP imports use the existing millimeter normalization.
  Missing historical units are reported as unknown, never guessed. Bounds are
  `[xmin, ymin, zmin, xmax, ymax, zmax]`, with explicit minimum/maximum XYZ vectors
  also exposed for agent use. OCC bounds can include small tolerance margins.
- Planes expose a constant CAD parametric normal, explicitly not guaranteed
  outward. Curved faces report varying normals and no misleading global vector.
- `CadFaceService` validates project ownership, artifact type, active completed
  geometry job, revision and face membership. Invalid/stale references return
  HTTP 409; missing/cross-project artifacts return HTTP 404. Selection writes
  compare the active revision inside the database update to reject stale clicks.
- Selection is project engineering state, shared by chats in that project, as
  active geometry/mesh selection already is. Chat histories never supply face
  identity. Geometry changes clear CAD selection; remeshing does not. Selecting
  the old geometry again does not resurrect a selection cleared by a change.
- The viewer uses vtk.js cell picking on the CAD actor and colors every triangle
  belonging to the selected face. Hover is separate from committed selection;
  drag/orbit does not select. Background click, Clear and Escape clear selection.
  Camera changes preserve it; Geometry/Mesh mode switches and reload restore it
  from backend metadata. Camera/selection changes do not download previews.
- Read-only agent tools are `list_cad_faces`, `inspect_cad_face` and
  `get_selected_cad_face`. Routing recognizes selection questions in either word
  order. Missing/stale selection requires clarification. Existing SSE event
  contracts and provider abstraction are unchanged.

## Endpoints

All endpoints are under `/api/projects/{project_id}`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/cad-previews/{preview_artifact_id}` | CAD preview with face provenance |
| GET | `/geometries/{geometry_revision_id}/faces` | List authoritative face metadata |
| GET | `/geometries/{geometry_revision_id}/faces/{face_key}` | Inspect one validated face |
| GET | `/cad-selection` | Retrieve current valid selection or clarification state |
| PUT | `/cad-selection` | Set/clear with `geometry_revision_id` and nullable `face_key` |

These geometry routes take the **artifact revision UUID**, not a geometry job UUID.

## Persistence and compatibility

The existing `project_context` table gains nullable `selected_cad_revision_id`
and `selected_cad_face_key` columns through the existing additive initialization
pattern. No jobs, original STEP files, previews or meshes are overwritten.
Older previews are lazily upgraded into a separate derived artifact in an
isolated subprocess, with a 120-second timeout. Native Gmsh never runs in an HTTP
thread. Repeated reads reuse the derived preview. Original artifact bytes are
checked in the upgrade test. Old download URLs remain available.

Rollback: reverting this implementation leaves harmless nullable columns and
derived preview artifacts; no reverse migration or artifact deletion is needed.

## Verification

Executed from the repository root:

```powershell
uv --cache-dir .cache/uv run --package simassist-backend ruff check backend/
uv --cache-dir .cache/uv run --package simassist-backend ruff format --check backend/
New-Item -ItemType Directory -Force .test-tmp | Out-Null
uv --cache-dir .cache/uv run --package simassist-backend pytest backend/tests -q --basetemp .test-tmp/full-final -p no:cacheprovider
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run test:cad-faces
npm.cmd --prefix frontend run test:viewer
git diff --check
```

- **280 backend tests passed**, including new real-Gmsh provenance/area/bounds,
  planar/curved metadata, repeat-preview identity, restart persistence, ownership,
  stale geometry rejection, agent tool routing/data and legacy upgrade checks.
  Existing geometry, mesh, upload, chat isolation, MAF and SSE tests passed.
- TypeScript/Vite production build passed. Vite retains its large-bundle warning.
- Ruff check and format check passed. The fixture script also passed Ruff.
- Both browser suites passed using headless Microsoft Edge with SwiftShader.
  CAD tests pick a box top and side, verify all owning triangles are highlighted,
  inspect hover and orbit behavior, retain selection through camera/mode/reload,
  clear using the button/Escape, pick a 2D face and a cylindrical hole wall,
  reject a click after an external geometry change visibly, and verify that no
  FEM mesh job was generated. The existing viewer suite also passed navigation,
  mesh versions, quality, fullscreen, resize and project switching.
- Live local `spark-x2.6-4b` requests through the actual chat endpoint retrieved
  the selected cylindrical face, correct revision, area and min/max XYZ bounds;
  a second request after clearing selection asked for a CAD-face click. Both
  submitted zero jobs. Initial live testing revealed that the model misread the
  flat bounds array; explicit min/max vectors and instructions corrected the
  observed follow-up. Model prose remains subject to model behavior; engineering
  identity and validation remain deterministic.
- Frontend lint ran successfully with warnings (including the existing pattern
  of setting state in effects); no lint errors.

`uv`'s default cache and pytest's default temp directory were inaccessible under
the sandbox, so verification used workspace-local paths. Windows execution
policy required `npm.cmd` in place of `npm.ps1`.

To reproduce browser tests, run these in separate terminals:

```powershell
uv --cache-dir .cache/uv run --package simassist-backend python scripts/benchmarks/cad_faces_fixture.py --root .benchmarks/cad-faces-repro --port 8003
$env:VITE_API_URL='http://127.0.0.1:8003'
$env:VITE_API_BASE_URL='http://127.0.0.1:8003'
npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 4176
# In another terminal:
npm.cmd --prefix frontend run test:cad-faces
```

The existing viewer suite uses `scripts/benchmarks/viewer_fixture.py`, port 8002
and frontend port 4175, with the existing 120k-tetra fixture available.

## Changed files

| Area | Files |
| --- | --- |
| Preview provenance and metadata | `backend/src/simassist/simulation/visualization/gmsh_preview.py`, `backend/src/simassist/workers/runner.py` |
| Validation and persistence | `backend/src/simassist/projects/cad_faces.py`, `backend/src/simassist/projects/context.py` |
| HTTP routes | `backend/src/simassist/api/routes/cad_faces.py`, `backend/src/simassist/main.py` |
| Agent integration | `backend/src/simassist/agents/tools/simulation_tools.py`, `backend/src/simassist/agents/registry.py`, `backend/src/simassist/agents/router.py`, `backend/src/simassist/agents/modules/selections/instructions.md` |
| Viewer and inspector | `frontend/src/features/viewer/components/ViewerScene.ts`, `frontend/src/features/viewer/components/SimulationViewer.tsx`, `frontend/src/styles/workspace.css` |
| Frontend requests and activation ordering | `frontend/src/services/cadFaces.ts`, `frontend/src/services/previews.ts`, `frontend/src/components/layout/AppShell.tsx` |
| Tests and fixture | `backend/tests/integration/test_cad_faces.py`, `frontend/e2e/cad-faces.mjs`, `frontend/package.json`, `scripts/benchmarks/cad_faces_fixture.py` |
| Report | `docs/PHASE_11_18B_IMPLEMENTATION_REPORT.md` |

## Limits and remaining risks

- Single selection only. There are no persistent named regions or FEM boundary
  mappings. CAD highlighting appears in Geometry mode; Mesh mode retains and
  displays the CAD selection in the inspector without coloring FEM cells.
- No automatic cross-revision remapping; changed geometry requires a new click.
- Selection is not pushed live between multiple browser tabs. Writes/read tools
  always revalidate; stale clicks show an error and reload restores backend state.
- Native GPU behavior and very large/complex STEP picking performance were not
  profiled in this phase. Browser verification used software WebGL.
- Concurrent first requests for a legacy preview can create duplicate equivalent
  derived artifacts; neither changes the source revision nor overwrites originals.
- A small viewer lifecycle fix initializes orientation-axis configuration at
  construction, preventing delayed vtk.js setter updates after Strict Mode
  teardown. Geometry preview activation now waits for backend context activation.

The pre-existing untracked `scripts/instal_skills.ps1` was left untouched.
