from pathlib import Path
from typing import Annotated

from fastapi import Depends

from simassist.storage.local import LocalArtifactStore


def get_data_root() -> Path:
    """Return the local SimAssist data directory."""
    return Path.cwd() / "data"


def get_artifact_store() -> LocalArtifactStore:
    """Provide the local artifact store."""
    return LocalArtifactStore(get_data_root() / "artifacts")


ArtifactStoreDep = Annotated[
    LocalArtifactStore,
    Depends(get_artifact_store),
]
