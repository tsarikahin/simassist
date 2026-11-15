import json
from unittest.mock import Mock
from uuid import uuid4

import pytest
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.core.models.mesh import MeshRequest, MeshSettings
from simassist.jobs.models import Job, JobStatus, JobType
from simassist.verification.service import (
    VerificationError,
    VerificationService,
)


def test_default_mesh_family_is_tetrahedral():
    settings = MeshSettings()

    assert settings.element_family.value == "tetrahedral"


def test_hexahedral_request_creates_no_mesh_job():
    geometry = Mock()
    tools = SimulationTools(geometry)

    response = json.loads(
        tools.generate_mesh(
            geometry_job_id=str(uuid4()),
            dimension=3,
            min_size=1,
            max_size=3,
            element_family="hexahedral",
        )
    )

    assert response["ok"] is False
    assert "not supported" in response["error"].lower()
    assert tools.submitted_job_ids == []

    geometry.get_job_status.assert_not_called()
    geometry.job_manager.submit.assert_not_called()


def test_hexahedral_workflow_creates_no_jobs():
    geometry = Mock()
    tools = SimulationTools(geometry)

    response = json.loads(
        tools.create_geometry_and_mesh(
            name="Hex Cylinder",
            primitive="cylinder",
            parameters={
                "radius": 20,
                "height": 80,
            },
            element_family="hexahedral",
        )
    )

    assert response["ok"] is False
    assert tools.submitted_job_ids == []

    geometry.job_manager.submit_geometry_mesh.assert_not_called()


def test_tetrahedral_workflow_keeps_element_family():
    geometry = Mock()
    geometry.project_id = uuid4()

    geometry_job = Job(
        project_id=geometry.project_id,
        type=JobType.GEOMETRY_CREATE,
    )

    mesh_job = Job(
        project_id=geometry.project_id,
        type=JobType.MESH_GENERATE,
        depends_on=geometry_job.id,
    )

    geometry.job_manager.submit_geometry_mesh.return_value = (
        geometry_job,
        mesh_job,
    )

    tools = SimulationTools(geometry)

    response = json.loads(
        tools.create_geometry_and_mesh(
            name="Tet Cylinder",
            primitive="cylinder",
            parameters={
                "radius": 20,
                "height": 80,
            },
            element_family="tetrahedral",
        )
    )

    assert response["ok"] is True

    kwargs = geometry.job_manager.submit_geometry_mesh.call_args.kwargs

    assert kwargs["mesh_settings"]["element_family"] == "tetrahedral"


@pytest.mark.parametrize(
    ("element_family", "volume_types", "should_pass"),
    [
        (
            "tetrahedral",
            {"Tetrahedron 4": 100},
            True,
        ),
        (
            "tetrahedral",
            {"Hexahedron 8": 100},
            False,
        ),
        (
            "hexahedral",
            {"Tetrahedron 4": 100},
            False,
        ),
        (
            "hexahedral",
            {"Hexahedron 8": 100},
            True,
        ),
        (
            "tetrahedral",
            {
                "Tetrahedron 4": 80,
                "Hexahedron 8": 20,
            },
            False,
        ),
    ],
)
def test_volume_element_family_verification(
    element_family,
    volume_types,
    should_pass,
    tmp_path,
):
    project_id = uuid4()
    geometry_id = uuid4()
    mesh_id = uuid4()

    geometry_path = tmp_path / "geometry.step"
    geometry_path.write_text("STEP DATA")

    mesh_path = tmp_path / "mesh.msh"
    mesh_path.write_text("MESH DATA")

    artifacts = {
        geometry_id: (
            Mock(
                project_id=project_id,
                type="geometry",
                parent_ids=[],
            ),
            geometry_path,
        ),
        mesh_id: (
            Mock(
                project_id=project_id,
                type="mesh",
                parent_ids=[geometry_id],
            ),
            mesh_path,
        ),
    }

    store = Mock()
    store.get.side_effect = lambda artifact_id: artifacts[artifact_id][0]
    store.resolve_path.side_effect = lambda artifact_id: artifacts[artifact_id][1]

    job = Job(
        project_id=project_id,
        type=JobType.MESH_GENERATE,
        status=JobStatus.RUNNING,
        input=MeshRequest(
            geometry_artifact_id=geometry_id,
            settings=MeshSettings(
                element_family=element_family,
            ),
        ).model_dump(mode="json"),
    )

    result = {
        "engine": "gmsh",
        "artifact_id": str(mesh_id),
        "geometry_artifact_id": str(geometry_id),
        "metadata": {
            "node_count": 200,
            "element_count": sum(volume_types.values()),
            "element_types": volume_types,
            "volume_element_types": volume_types,
        },
    }

    verifier = VerificationService(store)

    if should_pass:
        verifier.verify(job, result)
    else:
        with pytest.raises(VerificationError):
            verifier.verify(job, result)
