from pathlib import Path
from typing import Annotated

from fastapi import Depends

from simassist.core.paths import resolve_data_root
from simassist.jobs.manager import JobManager
from simassist.jobs.repository import JobRepository
from simassist.projects.context import ProjectContextRepository
from simassist.storage.local import LocalArtifactStore


def get_data_root() -> Path:
    """Local SimAssist data directory."""
    return resolve_data_root()


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


def get_project_context_repository(
    repository: Annotated[
        JobRepository,
        Depends(get_job_repository),
    ],
) -> ProjectContextRepository:
    return ProjectContextRepository(
        db_path=get_data_root() / "jobs.db",
        job_repository=repository,
    )


ArtifactStoreDep = Annotated[
    LocalArtifactStore,
    Depends(get_artifact_store),
]

JobManagerDep = Annotated[
    JobManager,
    Depends(get_job_manager),
]

ProjectContextDep = Annotated[
    ProjectContextRepository,
    Depends(get_project_context_repository),
]
