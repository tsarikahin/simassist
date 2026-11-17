from uuid import uuid4

import pytest
from simassist.agents.context import RoutingContext
from simassist.agents.remesh import explicit_mesh_request


@pytest.mark.parametrize(
    "message",
    [
        "Remesh it using min 0.5 mm and max 1 mm",
        "min 0.5 max 1 mm",
        "Use 0.5–1 mm.",
    ],
)
def test_explicit_bounds_are_preserved(message):
    context = RoutingContext(uuid4(), pending_remesh=True)
    assert explicit_mesh_request(message, context) == {
        "min_size": 0.5,
        "max_size": 1.0,
        "min_unit": "mm",
        "max_unit": "mm",
    }


@pytest.mark.parametrize(
    "message",
    [
        "yes",
        "confirm",
        "no",
        "cancel",
        "Do not remesh it using min 0.5 max 1 mm",
        "Could we remesh it using min 0.5 max 1 mm?",
        "Remesh it using min 0.5 max 1 mm after I confirm",
        "Remesh it using min 0.5 max 1 mm and delete the box",
        "Remesh another geometry using min 0.5 max 1 mm",
    ],
)
def test_confirmation_and_ambiguous_commands_stay_with_agent(message):
    assert (
        explicit_mesh_request(message, RoutingContext(uuid4(), pending_remesh=True))
        is None
    )


def test_parameter_reply_requires_chat_local_intent():
    assert explicit_mesh_request("min 0.5 max 1 mm", RoutingContext(uuid4())) is None


def test_missing_bounds_are_not_defaulted():
    assert explicit_mesh_request("Make it finer.", RoutingContext(uuid4())) == {}


def test_stale_pending_geometry_requires_clarification():
    context = RoutingContext(uuid4(), pending_remesh=True, issues=("stale_proposal",))
    assert explicit_mesh_request("min 0.5 max 1 mm", context) is None
