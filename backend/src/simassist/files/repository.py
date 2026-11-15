"""Project-owned immutable STEP originals and atomic import job registration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from simassist.jobs.models import Job, JobType
from simassist.jobs.repository import JobRepository
from simassist.projects.workspace import WorkspaceRepository, now


class FileRepository:
    def __init__(self, data_root: Path):
        self.root = data_root.resolve()
        self.workspace = WorkspaceRepository(self.root / "jobs.db")
        with self.workspace._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS project_files (
                    file_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    filename TEXT NOT NULL, format TEXT NOT NULL, file_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, content_hash TEXT, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, inspection TEXT,
                    imported_geometry_job_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_project_file ON project_files(project_id);
                CREATE TABLE IF NOT EXISTS chat_message_attachments (
                    message_id INTEGER NOT NULL, file_id TEXT NOT NULL, attachment_order INTEGER NOT NULL,
                    PRIMARY KEY(message_id, file_id)
                );
            """)

    def path(self, project_id, file_id, temporary=False):
        # Storage is computed entirely from parsed UUIDs, never display filenames.
        path = (
            self.root
            / "uploads"
            / str(UUID(str(project_id)))
            / (str(UUID(str(file_id))) + (".part" if temporary else ".step"))
        )
        for item in (path.parent.parent, path.parent, path):
            if item.is_symlink() or item.is_junction():
                raise ValueError("Linked upload paths are not permitted")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Invalid upload storage path")
        return path

    def reserve(self, project_id, filename, size):
        quota = int(
            os.getenv("SIMASSIST_PROJECT_UPLOAD_QUOTA_BYTES", str(512 * 1024 * 1024))
        )
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM workspace_projects WHERE id=?", (str(project_id),)
            ).fetchone():
                raise KeyError("Project not found")
            used = db.execute(
                "SELECT COALESCE(SUM(size_bytes),0) FROM project_files WHERE project_id=?",
                (str(project_id),),
            ).fetchone()[0]
            if used + size > quota:
                raise ValueError("Project upload storage quota exceeded")
            file_id = uuid4()
            db.execute(
                "INSERT INTO project_files(file_id,project_id,filename,format,file_type,size_bytes,status,created_at) "
                "VALUES (?,?,?,'step','cad_geometry',?,'uploading',?)",
                (str(file_id), str(project_id), filename, size, now()),
            )
        return file_id

    def discard(self, project_id, file_id):
        with self.workspace._connect() as db:
            db.execute(
                "DELETE FROM project_files WHERE file_id=? AND project_id=? AND status='uploading'",
                (str(file_id), str(project_id)),
            )

    def commit(self, project_id, file_id, size, digest, inspection):
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM workspace_projects WHERE id=?", (str(project_id),)
            ).fetchone():
                raise KeyError("Project not found")
            db.execute(
                "UPDATE project_files SET size_bytes=?,content_hash=?,inspection=?,status='uploaded' "
                "WHERE file_id=? AND project_id=? AND status='uploading'",
                (size, digest, json.dumps(inspection), str(file_id), str(project_id)),
            )
        return self.get(project_id, file_id)

    def get(self, project_id, file_id):
        with self.workspace._connect() as db:
            row = db.execute(
                "SELECT f.* FROM project_files f JOIN workspace_projects p ON p.id=f.project_id "
                "WHERE f.project_id=? AND file_id=? AND status!='uploading'",
                (str(project_id), str(UUID(str(file_id)))),
            ).fetchone()
            if not row:
                raise KeyError("Uploaded file not found in this project")
            item = dict(row)
            item["inspection"] = (
                json.loads(item["inspection"]) if item["inspection"] else None
            )
            if item["imported_geometry_job_id"]:
                job = db.execute(
                    "SELECT status,payload FROM jobs WHERE id=?",
                    (item["imported_geometry_job_id"],),
                ).fetchone()
                if job:
                    payload = json.loads(job["payload"])
                    item["import_status"] = job["status"]
                    item["geometry_result"] = payload.get("result")
                    item["import_error"] = payload.get("error")
            return item

    def list(self, project_id):
        with self.workspace._connect() as db:
            if not db.execute(
                "SELECT 1 FROM workspace_projects WHERE id=?", (str(project_id),)
            ).fetchone():
                raise KeyError("Project not found")
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT file_id FROM project_files WHERE project_id=? AND status!='uploading' ORDER BY created_at",
                    (str(project_id),),
                )
            ]
        return [self.get(project_id, file_id) for file_id in ids]

    def resolve(self, project_id, file_id):
        item = self.get(project_id, file_id)
        path = self.path(project_id, file_id)
        import hashlib

        if not path.is_file():
            raise ValueError(
                "Original upload is missing or changed; upload the file again"
            )
        with path.open("rb") as stream:
            if (
                hashlib.file_digest(stream, "sha256").hexdigest()
                != item["content_hash"]
            ):
                raise ValueError(
                    "Original upload is missing or changed; upload the file again"
                )
        return path

    def submit_import(self, project_id, file_id, mesh_settings=None):
        from simassist.core.models.mesh import MeshSettings

        self.get(project_id, file_id)
        if mesh_settings is not None:
            mesh_settings = MeshSettings.model_validate(mesh_settings).model_dump(
                mode="json"
            )
        repository = JobRepository(self.workspace.db_path)
        with self.workspace._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT f.* FROM project_files f JOIN workspace_projects p ON p.id=f.project_id "
                "WHERE file_id=? AND f.project_id=?",
                (str(file_id), str(project_id)),
            ).fetchone()
            if not row:
                raise KeyError("Uploaded file not found in this project")
            geometry_id = row["imported_geometry_job_id"]
            submitted = []
            if geometry_id:
                geometry = repository.get(UUID(geometry_id))
                if geometry.status.value in ("failed", "cancelled"):
                    raise ValueError(
                        "Previous import failed; inspect the job error and upload a corrected file"
                    )
            else:
                geometry = Job(
                    project_id=project_id,
                    type=JobType.GEOMETRY_CREATE,
                    input={
                        "name": row["filename"] + " [Imported]",
                        "units": "mm",
                        "definition": {"source": "cad_import", "file_id": str(file_id)},
                    },
                )
                repository._insert(db, geometry)
                db.execute(
                    "UPDATE project_files SET imported_geometry_job_id=? WHERE file_id=?",
                    (str(geometry.id), str(file_id)),
                )
                submitted.append(str(geometry.id))
            if mesh_settings is not None:
                mesh = Job(
                    project_id=project_id,
                    type=JobType.MESH_GENERATE,
                    depends_on=geometry.id,
                    input={
                        "geometry_job_id": str(geometry.id),
                        "settings": mesh_settings,
                    },
                )
                repository._insert(db, mesh)
                submitted.append(str(mesh.id))
        return geometry.id, submitted
