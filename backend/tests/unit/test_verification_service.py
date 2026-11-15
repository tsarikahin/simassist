import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from simassist.core.models.artifact import ArtifactType
from simassist.jobs.models import Job, JobStatus, JobType
from simassist.verification.service import (
    VerificationError,
    VerificationService,
)


def make_store(artifacts):
    store = Mock()
    store.get.side_effect = lambda artifact_id: artifacts[artifact_id][0]
    store.resolve_path.side_effect = lambda artifact_id: artifacts[artifact_id][1]
    return store


def test_valid_geometry_passes(tmp_path):
    project_id = uuid4()
    geometry_id = uuid4()
    preview_id = uuid4()

    step = tmp_path / "geometry.step"
    step.write_text("STEP DATA", encoding="utf-8")

    preview = tmp_path / "preview.json"
    preview.write_text(
        json.dumps(
            {
                "points": [
                    [0, 0, 0],
                    [1, 0, 0],
                    [0, 1, 0],
                ],
                "triangles": [[0, 1, 2]],
                "point_count": 3,
                "triangle_count": 1,
            }
        ),
        encoding="utf-8",
    )

    store = make_store(
        {
            geometry_id: (
                SimpleNamespace(
                    project_id=project_id,
                    type=ArtifactType.GEOMETRY,
                    parent_ids=[],
                ),
                step,
            ),
            preview_id: (
                SimpleNamespace(
                    project_id=project_id,
                    type=ArtifactType.GEOMETRY_PREVIEW,
                    parent_ids=[geometry_id],
                ),
                preview,
            ),
        }
    )

    job = Job(
        project_id=project_id,
        type=JobType.GEOMETRY_CREATE,
        status=JobStatus.RUNNING,
    )

    result = {
        "geometry_id": str(uuid4()),
        "engine": "gmsh",
        "artifact_id": str(geometry_id),
        "preview_artifact_id": str(preview_id),
        "metadata": {
            "volume_count": 1,
            "surface_count": 1,
        },
    }

    VerificationService(store).verify(job, result)


def test_invalid_preview_triangle_rejected(tmp_path):
    project_id = uuid4()
    geometry_id = uuid4()
    preview_id = uuid4()

    step = tmp_path / "geometry.step"
    step.write_text("STEP DATA", encoding="utf-8")

    preview = tmp_path / "preview.json"
    preview.write_text(
        json.dumps(
            {
                "points": [
                    [0, 0, 0],
                    [1, 0, 0],
                    [0, 1, 0],
                ],
                "triangles": [[0, 1, 99]],
                "point_count": 3,
                "triangle_count": 1,
            }
        ),
        encoding="utf-8",
    )

    store = make_store(
        {
            geometry_id: (
                SimpleNamespace(
                    project_id=project_id,
                    type=ArtifactType.GEOMETRY,
                    parent_ids=[],
                ),
                step,
            ),
            preview_id: (
                SimpleNamespace(
                    project_id=project_id,
                    type=ArtifactType.GEOMETRY_PREVIEW,
                    parent_ids=[geometry_id],
                ),
                preview,
            ),
        }
    )

    job = Job(
        project_id=project_id,
        type=JobType.GEOMETRY_CREATE,
        status=JobStatus.RUNNING,
    )

    result = {
        "geometry_id": str(uuid4()),
        "engine": "gmsh",
        "artifact_id": str(geometry_id),
        "preview_artifact_id": str(preview_id),
        "metadata": {
            "volume_count": 1,
            "surface_count": 1,
        },
    }

    with pytest.raises(
        VerificationError,
        match="invalid triangle indices",
    ):
        VerificationService(store).verify(job, result)


def test_valid_mesh_passes(tmp_path):
    project_id = uuid4()
    geometry_id = uuid4()
    mesh_id = uuid4()

    step = tmp_path / "geometry.step"
    step.write_text("STEP DATA", encoding="utf-8")

    mesh_file = tmp_path / "mesh.msh"
    mesh_file.write_text("MESH DATA", encoding="utf-8")

    store = make_store(
        {
            geometry_id: (
                SimpleNamespace(
                    project_id=project_id,
                    type=ArtifactType.GEOMETRY,
                    parent_ids=[],
                ),
                step,
            ),
            mesh_id: (
                SimpleNamespace(
                    project_id=project_id,
                    type=ArtifactType.MESH,
                    parent_ids=[geometry_id],
                ),
                mesh_file,
            ),
        }
    )

    job = Job(
        project_id=project_id,
        type=JobType.MESH_GENERATE,
        status=JobStatus.RUNNING,
        input={
            "geometry_artifact_id": str(geometry_id),
            "settings": {
                "dimension": 3,
                "min_size": 1,
                "max_size": 5,
            },
        },
    )

    result = {
        "engine": "gmsh",
        "artifact_id": str(mesh_id),
        "geometry_artifact_id": str(geometry_id),
        "metadata": {
            "node_count": 100,
            "element_count": 250,
            "element_types": {"Tetrahedron 4": 250},
        },
    }

    VerificationService(store).verify(job, result)


def test_empty_mesh_rejected(tmp_path):
    project_id = uuid4()
    geometry_id = uuid4()

    job = Job(
        project_id=project_id,
        type=JobType.MESH_GENERATE,
        status=JobStatus.RUNNING,
        input={
            "geometry_artifact_id": str(geometry_id),
        },
    )

    result = {
        "engine": "gmsh",
        "artifact_id": str(uuid4()),
        "geometry_artifact_id": str(geometry_id),
        "metadata": {
            "node_count": 0,
            "element_count": 0,
        },
    }

    with pytest.raises(
        VerificationError,
        match="no nodes",
    ):
        VerificationService(Mock()).verify(job, result)
