from pathlib import Path
from typing import Protocol
from uuid import UUID

from simassist.core.models.artifact import Artifact, ArtifactCreate


class ArtifactStore(Protocol):
    def save(self, request: ArtifactCreate) -> Artifact:
        """Save an artifact and register its metadata."""
        ...

    def get(self, artifact_id: UUID) -> Artifact:
        """Retrieve artifact metadata."""
        ...

    def resolve_path(self, artifact_id: UUID) -> Path:
        """Resolve the stored artifact to a local file."""
        ...

    def list_by_project(self, project_id: UUID) -> list[Artifact]:
        """List artifacts belonging to a project."""
        ...
