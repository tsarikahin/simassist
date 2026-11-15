import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.core.models.geometry import GeometrySpec
from simassist.core.models.mesh import MeshElementFamily, MeshSettings
from simassist.jobs.models import Job, JobStatus, JobType


@pytest.mark.parametrize(
    ("dimension", "expected"),
    [(1, "line"), (2, "triangular"), (3, "tetrahedral")],
)
def test_dimension_based_defaults(dimension, expected):
    assert MeshSettings(dimension=dimension).element_family == expected


def test_2d_quad_allowed_and_3d_hex_never_downgraded():
    assert MeshSettings(dimension=2, element_family="quadrilateral").element_family == (
        MeshElementFamily.QUADRILATERAL
    )
    with pytest.raises(ValueError):
        MeshSettings(dimension=2, element_family="tetrahedral")


def test_square_is_actual_surface_primitive():
    spec = GeometrySpec.model_validate(
        {
            "name": "2D square",
            "definition": {
                "source": "primitive",
                "primitive": "square",
                "parameters": {"size": 1},
            },
        }
    )
    assert spec.definition.primitive == "square"


def test_combined_quad_workflow_propagates_settings():
    geometry = Mock()
    geometry.project_id = uuid4()
    job_a = Job(project_id=geometry.project_id, type=JobType.GEOMETRY_CREATE)
    job_b = Job(
        project_id=geometry.project_id, type=JobType.MESH_GENERATE, depends_on=job_a.id
    )
    geometry.job_manager.submit_geometry_mesh.return_value = (job_a, job_b)
    tool = SimulationTools(geometry)
    response = json.loads(
        tool.create_geometry_and_mesh(
            name="2D square",
            primitive="square",
            parameters={"size": 1},
            dimension=2,
            element_family="quadrilateral",
            min_size=0.1,
            max_size=0.2,
        )
    )
    assert response["ok"] is True
    arguments = geometry.job_manager.submit_geometry_mesh.call_args.kwargs
    assert arguments["mesh_settings"]["dimension"] == 2
    assert arguments["mesh_settings"]["element_family"] == "quadrilateral"
    assert arguments["geometry_payload"]["definition"]["primitive"] == "square"


def test_dimension_mismatch_cannot_be_queued():
    geometry = Mock()
    tool = SimulationTools(geometry)
    response = json.loads(
        tool.create_geometry_and_mesh(
            name="Not a square",
            primitive="box",
            parameters={"length": 1, "width": 1, "height": 1},
            dimension=2,
            element_family="quadrilateral",
        )
    )
    assert response["ok"] is False
    geometry.job_manager.submit_geometry_mesh.assert_not_called()


def test_selected_surface_infers_2d_triangle():
    geometry = Mock()
    geometry.project_id = uuid4()
    job_id = uuid4()
    geometry.get_job_status.return_value = {
        "ok": True,
        "job_type": JobType.GEOMETRY_CREATE,
        "status": "completed",
        "result": {
            "artifact_id": str(uuid4()),
            "metadata": {"dimension": 2, "surface_count": 1},
        },
    }
    geometry.job_manager.submit.return_value = SimpleNamespace(
        id=uuid4(),
        type=JobType.MESH_GENERATE,
        status=JobStatus.QUEUED,
    )
    tool = SimulationTools(geometry)
    response = json.loads(
        tool.generate_mesh(geometry_job_id=str(job_id), min_size=1, max_size=5)
    )
    assert response["ok"] is True
    settings = geometry.job_manager.submit.call_args.kwargs["payload"]["settings"]
    assert settings["dimension"] == 2
    assert settings["element_family"] == "triangular"
