from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path
from uuid import UUID

from simassist.core.models.artifact import (
    Artifact,
    ArtifactCreate,
)


class LocalArtifactStore:
    """Filesystem storage with a SQLite metadata index."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

        self.files_dir = self.root / "files"
        self.files_dir.mkdir(exist_ok=True)

        self.db_path = self.root / "artifacts.db"
        self._initialize_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30)

    def _initialize_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_artifacts_project
                ON artifacts(project_id)
            """)

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)

        return digest.hexdigest()

    def save(self, request: ArtifactCreate) -> Artifact:
        source = request.source_path.resolve()

        if not source.is_file():
            raise FileNotFoundError(source)

        # Never allow a filename to determine a parent directory.
        filename = source.name

        artifact = Artifact(
            project_id=request.project_id,
            type=request.type,
            filename=filename,
            relative_path="",
            size_bytes=0,
            sha256="",
            parent_ids=request.parent_ids,
        )

        relative_path = Path(str(request.project_id)) / str(artifact.id) / filename

        destination = self.files_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)

        temporary = destination.with_name(destination.name + ".tmp")

        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)

            artifact = artifact.model_copy(
                update={
                    "relative_path": relative_path.as_posix(),
                    "size_bytes": destination.stat().st_size,
                    "sha256": self._checksum(destination),
                }
            )

            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO artifacts (id, project_id, metadata)
                    VALUES (?, ?, ?)
                    """,
                    (
                        str(artifact.id),
                        str(artifact.project_id),
                        artifact.model_dump_json(),
                    ),
                )

        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

        return artifact

    def get(self, artifact_id: UUID) -> Artifact:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT metadata FROM artifacts WHERE id = ?",
                (str(artifact_id),),
            ).fetchone()

        if row is None:
            raise KeyError(f"Artifact not found: {artifact_id}")

        return Artifact.model_validate_json(row[0])

    def resolve_path(self, artifact_id: UUID) -> Path:
        artifact = self.get(artifact_id)

        path = (self.files_dir / artifact.relative_path).resolve()

        if not path.is_relative_to(self.files_dir.resolve()):
            raise ValueError("Invalid artifact path")

        if not path.is_file():
            raise FileNotFoundError(path)

        return path

    def list_by_project(self, project_id: UUID) -> list[Artifact]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT metadata FROM artifacts
                WHERE project_id = ?
                ORDER BY rowid
                """,
                (str(project_id),),
            ).fetchall()

        return [Artifact.model_validate_json(row[0]) for row in rows]
