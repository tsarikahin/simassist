from pathlib import Path
from typing import Annotated

from fastapi import Depends

from simassist.jobs.manager import JobManager
from simassist.jobs.repository import JobRepository
from simassist.storage.local import LocalArtifactStore


def get_data_root() -> Path:
    """Local SimAssist data directory."""
    return Path.cwd() / "data"


def get_artifact_store() -> LocalArtifactStore:
    return LocalArtifactStore(get_data_root() / "artifacts")


def get_job_repository() -> JobRepository:
    return JobRepository(get_data_root() / "jobs.db")


def get_job_manager(
    repository: Annotated[
        JobRepository,
        Depends(get_job_repository),
    ],
) -> JobManager:
    return JobManager(repository)


ArtifactStoreDep = Annotated[
    LocalArtifactStore,
    Depends(get_artifact_store),
]

JobManagerDep = Annotated[
    JobManager,
    Depends(get_job_manager),
]
