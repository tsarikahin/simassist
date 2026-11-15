# Chat file uploads and STEP CAD meshing

This release implements the first vertical slice of the file-upload specification:
**STEP (.step/.stp) upload ? inspect ? resolve mesh settings ? import ? mesh ? preview and versions.**
It reuses `geometry.create` and `mesh.generate`, the existing worker, verification,
Geometry / Mesh explorer, viewer, version selection, and quality inspection.
IGES/BREP, imported `.msh` viewing, VTK, and STL reconstruction remain later work.
A mesh file is not an editable CAD model and is rejected with that explanation.

Use **Attach file** in the chat composer, or drop a STEP file onto the composer.
A progress label changes to **Inspecting CAD** while the backend validates it.
Remove/cancel a chip before sending, or retry a failed upload. Enter a query such as:

> Generate a 3D tetrahedral mesh of this attached model, with minimum size
> 0.5 mm and maximum size 1 mm.

Uploads alone submit no engineering jobs. The agent inspects project-owned file
IDs and asks for consequential missing sizing, units, or family decisions.
The combined upload meshing tool requires all of these settings before it can
submit jobs. STEP coordinates are normalized by OpenCASCADE to **millimeters**;
explicit mesh-size units in mm/cm/m/in are converted to mm in backend code.
File names and bounding-box magnitudes never establish mesh-size units.
The original STEP bytes remain unchanged. The import is a separate normalized
geometry artifact with source file ID/hash and a parent reference to the source.
Import success is not proof that every requested fine feature will be preserved
or that the mesh is suitable for a physical simulation.

A submitted import is asynchronous. After worker verification, the model appears
under **Geometry / Mesh** with an **[Imported]** label and can be selected,
renamed, and meshed again. Each new mesh is a separate version. Import-only calls
reuse the existing geometry job for that file. Check job errors for failed imports;
upload a corrected file rather than repeatedly submitting the failed import.

Attachments are saved with the user message and restored after refresh. Other
chats do not receive their message references automatically; explicit file tools
may inspect shared project files. Removing a composer chip or deleting a chat
removes that reference, not the original engineering upload. Project deletion
retains uploads/job files on disk, consistent with existing project deletion.
Upload bytes never enter the language model prompt; the model receives file IDs,
display names and tool-produced engineering metadata. That metadata is labeled
untrusted and is not permission to execute file-embedded instructions.

## Storage and API

- `POST /api/projects/{project_id}/files`: one multipart `file` per request.
- `GET /api/projects/{project_id}/files`: list validated project-owned files.
- `GET /api/projects/{project_id}/files/{file_id}`: metadata, inspection, import
  job ID, job status and generated geometry/preview references when available.
- Sync and SSE chat accept `attachments: [{"file_id": "..."}]`.

Additive SQLite tables `project_files` and `chat_message_attachments` retain
ownership, display filename, format, size, SHA-256, status, topology/bounds,
import job references, message references and attachment order. Existing tables
and job/artifact data are preserved. Storage filenames are computed from UUIDs
under `data/uploads/{project_id}/{file_id}.step`, never a supplied path. Original
files are checked for integrity again before worker import. Unknown/cross-project
IDs are rejected. Display filenames containing directory paths are rejected
(the multipart parser may first strip Windows browser path prefixes).

Import job creation and registration of the file's geometry job are one SQLite
transaction. Combined import+mesh creation is also atomic. Repeated identical
combined calls within a single agent turn reuse their result; chat retry keys
include ordered attachment IDs and cannot silently resubmit changed attachments.
A deliberately new chat request can create another mesh version. Worker crashes
retain the existing job scheduler's recovery semantics; native artifact writing
and SQLite completion are not a single atomic transaction. Inspect jobs before
manually recovering a running job after a process crash.

## Limits and operation

| Environment variable | Default | Purpose |
| --- | ---: | --- |
| `SIMASSIST_MAX_UPLOAD_BYTES` | 33554432 (32 MiB) | Maximum original file bytes |
| `SIMASSIST_PROJECT_UPLOAD_QUOTA_BYTES` | 536870912 (512 MiB) | Per-project reserved/original upload bytes |
| `SIMASSIST_ALLOWED_UPLOAD_EXTENSIONS` | `.step,.stp` | Restrict the supported STEP extensions; cannot enable other parsers |
| `SIMASSIST_MAX_CHAT_ATTACHMENTS` | 4 | Maximum attachment references per chat request |

A receive-side limit caps multipart requests at the file limit plus 64 KiB for
multipart framing before Starlette spools them. Uploads copy to disk in bounded
chunks. Quota reservations are serialized; parallel uploads cannot overspend the
original-file quota. Artifact copies, generated meshes and temporary multipart
spool files are not included in that quota. Interrupted/invalid upload handlers
remove temporary files and uncommitted records. A hard process kill can leave an
invisible `uploading` reservation/partial file; after stopping the API, inspect
these records and remove only their corresponding UUID-owned partial/original
files and reservations. No automatic cleanup can delete an active upload.

STEP is parsed in a dedicated subprocess with a 60-second timeout, separate from
the API event loop and worker's Gmsh state. Its launcher and bounded wait run in
an AnyIO worker thread using `subprocess.Popen`, so Windows Uvicorn reload mode
works even when its Selector event loop has no asyncio subprocess support.
Cancellation waits for this bounded operation before cleaning up its source;
timeouts kill and reap the parser process. Symlink/junction storage paths are
rejected. Files are parsed as STEP only, never executed as scripts or commands.
This is process isolation, not a full operating-system sandbox for native CAD
libraries; keep uploads local and Gmsh/OpenCASCADE updated. Models too large or
complex for the limits should be simplified. Geometry import/preview/meshing
still runs in the separate worker.

Install locked dependencies (`uv sync --package simassist-backend`), restart the
API **and worker**, then refresh the frontend. `python-multipart` is now required.
