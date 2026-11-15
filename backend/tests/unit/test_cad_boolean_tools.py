from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.core.models.geometry import GeometrySpec
from simassist.jobs.models import JobType

ANNULUS_OPERANDS = [
    {"primitive": "disk", "parameters": {"radius": 2}},
    {"primitive": "disk", "parameters": {"radius": 1}},
]


def test_annulus_definition_is_valid_and_2d():
    spec = GeometrySpec.model_validate(
        {
            "name": "annulus",
            "definition": {
                "source": "csg",
                "operation": "cut",
                "operands": ANNULUS_OPERANDS,
            },
        }
    )
    assert spec.definition.operation == "cut"
    assert len(spec.definition.operands) == 2
    assert spec.definition.operands[0].parameters["radius"] == 2


@pytest.mark.parametrize("operation", ["cut", "fuse", "intersect"])
def test_valid_boolean_operations_submit_geometry(operation):
    geometry = Mock()
    geometry.create_geometry.return_value = {
        "ok": True,
        "job_id": str(uuid4()),
        "status": "queued",
    }
    tools = SimulationTools(geometry)
    result = json.loads(
        tools.create_boolean_geometry(
            name="boolean 2D",
            operation=operation,
            operands=ANNULUS_OPERANDS,
        )
    )
    assert result["ok"] is True
    assert result["dimension"] == 2
    payload = geometry.create_geometry.call_args.args[0]
    assert payload["definition"]["source"] == "csg"
    assert payload["definition"]["operation"] == operation
    assert tools.submitted_job_ids == [result["job_id"]]


def test_annulus_2d_triangular_workflow_queues_atomic_pair():
    geometry = Mock()
    geometry.project_id = uuid4()
    geometry.job_manager.submit_geometry_mesh.return_value = (
        SimpleNamespace(id=uuid4(), type=JobType.GEOMETRY_CREATE),
        SimpleNamespace(id=uuid4(), type=JobType.MESH_GENERATE),
    )
    tools = SimulationTools(geometry)
    result = json.loads(
        tools.create_boolean_geometry_and_mesh(
            name="Annulus R2-r1",
            operation="cut",
            operands=ANNULUS_OPERANDS,
            dimension=2,
            element_family="triangular",
            min_size=0.1,
            max_size=0.2,
        )
    )
    assert result["ok"] is True
    assert len(tools.submitted_job_ids) == 2
    kwargs = geometry.job_manager.submit_geometry_mesh.call_args.kwargs
    assert kwargs["mesh_settings"]["dimension"] == 2
    assert kwargs["mesh_settings"]["element_family"] == "triangular"
    assert kwargs["geometry_payload"]["definition"]["operation"] == "cut"
    assert kwargs["geometry_payload"]["definition"]["operands"][1]["parameters"] == {
        "radius": 1.0
    }


@pytest.mark.parametrize(
    "operands, expected_message",
    [
        ([{"primitive": "disk", "parameters": {"radius": 2}}], "At least two"),
        (
            [
                ANNULUS_OPERANDS[0],
                {
                    "primitive": "box",
                    "parameters": {
                        "length": 1,
                        "width": 1,
                        "height": 1,
                    },
                },
            ],
            "share a 2D or 3D",
        ),
        (
            [ANNULUS_OPERANDS[0], {"primitive": "disk", "parameters": {"radius": -1}}],
            "positive finite",
        ),
        (
            [
                ANNULUS_OPERANDS[0],
                {
                    "primitive": "disk",
                    "parameters": {"radius": 1},
                    "origin": {"x": float("nan")},
                },
            ],
            "finite numbers",
        ),
    ],
)
def test_invalid_boolean_is_rejected_before_jobs(operands, expected_message):
    geometry = Mock()
    tools = SimulationTools(geometry)
    result = json.loads(
        tools.create_boolean_geometry_and_mesh(
            name="invalid",
            operation="cut",
            operands=operands,
        )
    )
    assert result["ok"] is False
    assert expected_message in result["error"]
    assert tools.submitted_job_ids == []
    geometry.job_manager.submit_geometry_mesh.assert_not_called()


def test_hexahedral_boolean_rejected_without_job():
    geometry = Mock()
    tools = SimulationTools(geometry)
    result = json.loads(
        tools.create_boolean_geometry_and_mesh(
            name="bad hex",
            operation="cut",
            operands=ANNULUS_OPERANDS,
            dimension=2,
            element_family="hexahedral",
        )
    )
    assert result["ok"] is False
    geometry.job_manager.submit_geometry_mesh.assert_not_called()


def test_boolean_model_rejects_mixed_dimensions():
    with pytest.raises(ValueError, match="same dimension"):
        GeometrySpec.model_validate(
            {
                "name": "mixed",
                "definition": {
                    "source": "csg",
                    "operation": "cut",
                    "operands": [
                        ANNULUS_OPERANDS[0],
                        {"primitive": "sphere", "parameters": {"radius": 1}},
                    ],
                },
            }
        )


def test_boolean_3d_box_cylinder_workflow():
    geometry = Mock()
    geometry.project_id = uuid4()
    geometry.job_manager.submit_geometry_mesh.return_value = (
        SimpleNamespace(id=uuid4(), type=JobType.GEOMETRY_CREATE),
        SimpleNamespace(id=uuid4(), type=JobType.MESH_GENERATE),
    )
    tools = SimulationTools(geometry)
    result = json.loads(
        tools.create_boolean_geometry_and_mesh(
            name="Drilled block",
            operation="cut",
            operands=[
                {
                    "primitive": "box",
                    "parameters": {"length": 10, "width": 10, "height": 5},
                },
                {
                    "primitive": "cylinder",
                    "parameters": {"radius": 1, "height": 5},
                    "origin": {"x": 5, "y": 5},
                },
            ],
        )
    )
    assert result["ok"] is True
    assert result["dimension"] == 3
    kwargs = geometry.job_manager.submit_geometry_mesh.call_args.kwargs
    assert kwargs["mesh_settings"]["element_family"] == "tetrahedral"
