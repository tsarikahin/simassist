from __future__ import annotations

from unittest.mock import Mock
from uuid import uuid4

import meshio
import numpy as np
import pytest
from fastapi import HTTPException
from simassist.api.routes.mesh_previews import (
    build_tetra_surface_preview,
    get_latest_mesh_preview,
)
from simassist.core.models.artifact import ArtifactType
from simassist.jobs.models import Job, JobStatus, JobType


def make_mesh(path):
    # Two tetrahedra share face (0, 1, 2): eight total faces,
    # two shared face occurrences, six exterior triangles.
    meshio.write(
        path,
        meshio.Mesh(
            points=np.array(
                [
                    [0, 0, 0],
                    [1, 0, 0],
                    [0, 1, 0],
                    [0, 0, 1],
                    [0, 0, -1],
                ],
                dtype=float,
            ),
            cells=[("tetra", np.array([[0, 1, 2, 3], [0, 2, 1, 4]]))],
        ),
        file_format="gmsh22",
    )


def test_extracts_only_exterior_tetra_faces(tmp_path):
    path = tmp_path / "test.msh"
    make_mesh(path)
    preview = build_tetra_surface_preview(path)
    assert preview["triangle_count"] == 6
    assert preview["point_count"] == 5
    assert preview["volume_element_count"] == 2
    assert len(preview["points"]) == 5
    assert max(max(t) for t in preview["triangles"]) == 4


def test_rejects_mesh_without_tetrahedra(tmp_path):
    path = tmp_path / "surface.msh"
    meshio.write(
        path,
        meshio.Mesh(
            points=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
            cells=[("triangle", np.array([[0, 1, 2]]))],
        ),
        file_format="gmsh22",
    )
    with pytest.raises(ValueError, match="no tetrahedral"):
        build_tetra_surface_preview(path)


def test_mesh_preview_lookup_uses_selected_geometry(tmp_path):
    path = tmp_path / "test.msh"
    make_mesh(path)
    project_id = uuid4()
    geometry_id = uuid4()
    geometry_artifact = uuid4()
    mesh_artifact = uuid4()
    geometry_job = Job(
        id=geometry_id,
        project_id=project_id,
        type=JobType.GEOMETRY_CREATE,
        status=JobStatus.COMPLETED,
        result={"artifact_id": str(geometry_artifact)},
    )
    mesh_job = Job(
        project_id=project_id,
        type=JobType.MESH_GENERATE,
        status=JobStatus.COMPLETED,
        input={"geometry_artifact_id": str(geometry_artifact)},
        result={
            "geometry_artifact_id": str(geometry_artifact),
            "artifact_id": str(mesh_artifact),
        },
    )
    manager = Mock()
    manager.get.return_value = geometry_job
    manager.list_by_project.return_value = [mesh_job, geometry_job]
    store = Mock()
    store.get.return_value = Mock(
        project_id=project_id,
        type=ArtifactType.MESH,
        parent_ids=[geometry_artifact],
    )
    store.resolve_path.return_value = path
    import json

    response = get_latest_mesh_preview(project_id, geometry_id, manager, store)
    result = json.loads(response.body)
    assert result["mesh_job_id"] == str(mesh_job.id)
    assert result["triangle_count"] == 6


def test_missing_mesh_returns_404():
    project_id = uuid4()
    geometry_id = uuid4()
    geometry = Job(
        id=geometry_id,
        project_id=project_id,
        type=JobType.GEOMETRY_CREATE,
        status=JobStatus.COMPLETED,
        result={"artifact_id": str(uuid4())},
    )
    manager = Mock()
    manager.get.return_value = geometry
    manager.list_by_project.return_value = []
    with pytest.raises(HTTPException) as exc:
        get_latest_mesh_preview(project_id, geometry_id, manager, Mock())
    assert exc.value.status_code == 404
