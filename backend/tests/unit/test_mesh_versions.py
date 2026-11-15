from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from simassist.api.routes.mesh_versions import (
    find_mesh_versions,
    get_mesh_version_preview,
)
from simassist.jobs.models import JobStatus, JobType


def fake_job(project_id, job_type, status, result=None, payload=None, job_id=None):
    return SimpleNamespace(
        id=job_id or uuid4(),
        project_id=project_id,
        type=job_type,
        status=status,
        result=result or {},
        input=payload or {},
    )


def test_find_mesh_versions_filters_other_geometries_and_failed_jobs():
    project_id = uuid4()
    geometry_job_id = uuid4()
    geometry_artifact_id = uuid4()
    geometry = fake_job(
        project_id,
        JobType.GEOMETRY_CREATE,
        JobStatus.COMPLETED,
        {"artifact_id": str(geometry_artifact_id)},
    )
    good = fake_job(
        project_id,
        JobType.MESH_GENERATE,
        JobStatus.COMPLETED,
        {
            "artifact_id": str(uuid4()),
            "geometry_artifact_id": str(geometry_artifact_id),
        },
    )
    wrong = fake_job(
        project_id,
        JobType.MESH_GENERATE,
        JobStatus.COMPLETED,
        {"artifact_id": str(uuid4()), "geometry_artifact_id": str(uuid4())},
    )
    failed = fake_job(
        project_id,
        JobType.MESH_GENERATE,
        JobStatus.FAILED,
        {
            "artifact_id": str(uuid4()),
            "geometry_artifact_id": str(geometry_artifact_id),
        },
    )
    manager = Mock()
    manager.get.return_value = geometry
    manager.list_by_project.return_value = [good, wrong, failed]
    assert find_mesh_versions(project_id, geometry_job_id, manager) == [good]


def test_cannot_preview_mesh_version_from_another_geometry():
    project_id = uuid4()
    geom_id = uuid4()
    manager = Mock()
    manager.get.return_value = fake_job(
        project_id,
        JobType.GEOMETRY_CREATE,
        JobStatus.COMPLETED,
        {"artifact_id": str(uuid4())},
    )
    manager.list_by_project.return_value = []
    store = Mock()
    with pytest.raises(HTTPException) as exc:
        get_mesh_version_preview(project_id, geom_id, uuid4(), manager, store)
    assert exc.value.status_code == 404
    store.get.assert_not_called()
