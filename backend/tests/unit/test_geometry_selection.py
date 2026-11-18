"""CAD selection uses real OCC topology and a local DB, with no model provider."""

import json
import sqlite3
from uuid import uuid4

import gmsh
import pytest
from pydantic import ValidationError
from simassist.agents.context import RoutingContext
from simassist.agents.orchestrator import compose
from simassist.agents.tools.geometry import GeometryTools
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.api.routes.cad_geometry import EntitySelectionRequest
from simassist.core.models.artifact import ArtifactCreate
from simassist.core.models.geometry import GeometrySpec, PrimitiveGeometry
from simassist.jobs.manager import JobManager
from simassist.jobs.models import JobType
from simassist.jobs.repository import JobRepository
from simassist.projects.cad_geometry import CadGeometryService
from simassist.projects.context import ProjectContextRepository
from simassist.simulation.geometry.gmsh_adapter import GmshGeometryAdapter
from simassist.simulation.visualization.gmsh_preview import (
    GeometryPreview,
    GmshPreviewService,
)
from simassist.storage.local import LocalArtifactStore


@pytest.fixture
def cad(tmp_path):
    project = uuid4()
    store = LocalArtifactStore(tmp_path / "artifacts")
    geometry = GmshGeometryAdapter(tmp_path / "geometry", store, project).create(
        GeometrySpec(
            name="Box",
            definition=PrimitiveGeometry(
                primitive="box",
                parameters={"length": 2, "width": 3, "height": 4},
            ),
        )
    )
    previews = GmshPreviewService(tmp_path / "previews", store, project)
    preview_id = previews.generate(geometry.artifact_id, coordinate_units="mm")
    preview = GeometryPreview.model_validate_json(
        store.resolve_path(preview_id).read_text()
    )
    jobs = JobRepository(tmp_path / "jobs.db")
    manager = JobManager(jobs)

    def completed(revision):
        job = manager.submit(project, JobType.GEOMETRY_CREATE, {"units": "mm"})
        jobs.claim_next()
        jobs.complete(
            job.id,
            {"artifact_id": str(revision), "preview_artifact_id": str(preview_id)},
        )
        return job.id

    context = ProjectContextRepository(jobs.db_path, jobs)
    context.set_active_geometry(project, completed(geometry.artifact_id))
    return project, preview, CadGeometryService(store, context), completed, previews


def test_all_dimensions_have_authoritative_metadata_and_pick_provenance(cad):
    project, preview, service, *_ = cad
    assert service.preview(project, preview.geometry_revision_id) == preview
    by_dimension = {
        dim: [entity for entity in preview.entities if entity.dimension == dim]
        for dim in range(4)
    }
    assert [len(by_dimension[dim]) for dim in range(4)] == [8, 12, 6, 1]
    assert {entity.label for entity in by_dimension[0]} == {
        f"Vertex {i}" for i in range(1, 9)
    }
    assert all(
        entity.coordinates is not None and entity.length is None
        for entity in by_dimension[0]
    )
    assert sorted(entity.length for entity in by_dimension[1]) == pytest.approx(
        [2] * 4 + [3] * 4 + [4] * 4
    )
    assert sorted(entity.area for entity in by_dimension[2]) == pytest.approx(
        [6, 6, 8, 8, 12, 12]
    )
    body = by_dimension[3][0]
    assert body.volume == pytest.approx(24)
    assert body.measure_units == "mm^3"
    assert all(face.owner_body_keys == [body.entity_key] for face in by_dimension[2])
    assert set(body.boundary_entity_keys) == {
        face.entity_key for face in by_dimension[2]
    }
    assert len(preview.vertex_point_indices) == 8
    assert len(preview.edge_segments) == len(preview.edge_entity_keys) > 12
    assert len(preview.triangle_face_keys) == len(preview.triangles)
    by_key = {entity.entity_key: entity for entity in preview.entities}
    for index, key in zip(
        preview.vertex_point_indices, preview.vertex_entity_keys, strict=True
    ):
        assert preview.points[index] == pytest.approx(by_key[key].coordinates)
    for segment, key in zip(
        preview.edge_segments, preview.edge_entity_keys, strict=True
    ):
        bounds = by_key[key].bounds
        for index in segment:
            assert all(
                bounds[axis] - 1e-6 <= value <= bounds[axis + 3] + 1e-6
                for axis, value in enumerate(preview.points[index])
            )
    again = cad[-1].generate(preview.geometry_revision_id, coordinate_units="mm")
    regenerated = GeometryPreview.model_validate_json(
        service.store.resolve_path(again).read_text()
    )
    assert regenerated.entities == preview.entities


def test_selection_persists_all_dimensions_and_keeps_face_contract(cad):
    project, preview, service, *_ = cad
    for dimension in range(4):
        entity = next(item for item in preview.entities if item.dimension == dimension)
        result = service.select_entity(
            project, preview.geometry_revision_id, dimension, entity.tag
        )
        assert result["selection"] == entity
        restarted = ProjectContextRepository(
            service.context.db_path, service.context.job_repository
        )
        state = restarted.get(project)
        assert (
            state.selected_cad_revision_id,
            state.selected_cad_dimension,
            state.selected_cad_tag,
        ) == (preview.geometry_revision_id, dimension, entity.tag)
        assert (
            CadGeometryService(service.store, restarted).entity_selection(project)[
                "selection"
            ]
            == entity
        )
        if dimension == 2:
            assert service.selection(project)["selection"].face_key == entity.entity_key
            assert (
                service.select(
                    project, preview.geometry_revision_id, entity.entity_key
                )["selection"].area
                == entity.area
            )
        else:
            assert service.selection(project)["selection"] is None
    assert (
        service.select_entity(project, preview.geometry_revision_id, None, None)[
            "selection"
        ]
        is None
    )
    assert service.context.get(project).selected_cad_tag is None


def test_selection_rejects_stale_foreign_and_nonexistent_entities(cad):
    project, preview, service, completed, _ = cad
    revision = preview.geometry_revision_id
    face = preview.faces[0]
    service.select(project, revision, face.face_key)
    with pytest.raises(KeyError):
        service.select_entity(uuid4(), revision, 2, face.local_gmsh_tag)
    with pytest.raises(ValueError, match="does not belong"):
        service.select_entity(project, revision, 1, 99999)
    new_revision = uuid4()
    service.context.set_active_geometry(project, completed(new_revision))
    assert service.entity_selection(project)["selection"] is None
    with pytest.raises(ValueError, match="stale"):
        service.context.set_entity_selection(project, revision, 2, face.local_gmsh_tag)
    # Returning to an old geometry does not resurrect an old selection.
    service.context.set_active_geometry(project, completed(revision))
    assert service.entity_selection(project)["selection"] is None


def test_selection_compare_and_set_rejects_geometry_change_during_inspection(
    cad, monkeypatch
):
    project, preview, service, completed, _ = cad
    entity = preview.entities[0]
    original = service.inspect_entity

    def inspect(*args):
        result = original(*args)
        service.context.set_active_geometry(project, completed(uuid4()))
        return result

    monkeypatch.setattr(service, "inspect_entity", inspect)
    with pytest.raises(ValueError, match="stale"):
        service.select_entity(
            project, preview.geometry_revision_id, entity.dimension, entity.tag
        )
    assert service.context.get(project).selected_cad_dimension is None


def test_legacy_face_selection_is_migrated_and_agent_reads_generic_selection(cad):
    project, preview, service, *_ = cad
    face = preview.faces[0]
    service.select(project, preview.geometry_revision_id, face.face_key)
    with sqlite3.connect(service.context.db_path) as conn:
        conn.execute(
            "UPDATE project_context SET selected_cad_dimension=NULL,selected_cad_tag=NULL"
        )
    restarted = ProjectContextRepository(
        service.context.db_path, service.context.job_repository
    )
    assert restarted.get(project).selected_cad_dimension == 2
    assert restarted.get(project).selected_cad_tag == face.local_gmsh_tag
    tools = SimulationTools(GeometryTools(None, project), restarted)
    for dimension in range(4):
        entity = next(item for item in preview.entities if item.dimension == dimension)
        service.select_entity(
            project, preview.geometry_revision_id, dimension, entity.tag
        )
        result = json.loads(tools.get_geometry_selection())
        assert result["selection"]["entity_id"] == str(entity.entity_id)
        assert result["selection"]["label"] == entity.label
        composition = compose(
            f"Which {['vertex', 'edge', 'face', 'body'][dimension]} did I select?",
            RoutingContext(project_id=project),
            tools,
        )
        assert "get_geometry_selection" in {fn.__name__ for fn in composition.tools}


@pytest.mark.parametrize(
    "change",
    [
        {"dimension": 0},
        {"tag": 2},
        {"dimension": 4, "tag": 1},
        {"dimension": 1, "tag": 0},
    ],
)
def test_incomplete_or_invalid_selection_requests_are_rejected(change):
    with pytest.raises(ValidationError):
        EntitySelectionRequest(geometry_revision_id=uuid4(), **change)


@pytest.mark.parametrize(
    "message",
    [
        "What is the current selection?",
        "What did I select?",
        "Inspect selected vertices",
        "Which body did I pick?",
    ],
)
def test_generic_selection_questions_expose_current_selection_tool(message):
    project = uuid4()
    tools = SimulationTools(GeometryTools(None, project))
    composition = compose(message, RoutingContext(project_id=project), tools)
    assert "get_geometry_selection" in {fn.__name__ for fn in composition.tools}


def test_corrupt_pick_provenance_is_rejected(cad):
    _, preview, service, *_ = cad
    invalid = preview.model_copy(
        update={"edge_entity_keys": ["invented"] * len(preview.edge_segments)}
    )
    with pytest.raises(ValueError, match="picking provenance"):
        service._validate_preview(invalid, preview.geometry_revision_id)


@pytest.mark.parametrize(
    "primitive,parameters,dimension",
    [
        ("line", {"length": 5}, 1),
        ("rectangle", {"width": 2, "height": 3}, 2),
        ("cylinder", {"radius": 2, "height": 3}, 3),
    ],
)
def test_curve_shell_and_curved_solid_topology(
    tmp_path, primitive, parameters, dimension
):
    project = uuid4()
    store = LocalArtifactStore(tmp_path / "artifacts")
    geometry = GmshGeometryAdapter(tmp_path / "geometry", store, project).create(
        GeometrySpec(
            name="CAD",
            definition=PrimitiveGeometry(primitive=primitive, parameters=parameters),
        )
    )
    preview_id = GmshPreviewService(tmp_path / "previews", store, project).generate(
        geometry.artifact_id
    )
    preview = GeometryPreview.model_validate_json(
        store.resolve_path(preview_id).read_text()
    )
    CadGeometryService._validate_preview(preview, geometry.artifact_id)
    assert preview.dimension == dimension
    assert all(entity.measure_units in (None, "unknown") for entity in preview.entities)
    assert preview.vertex_entity_keys and preview.edge_entity_keys
    if dimension < 3:
        assert not any(entity.dimension == 3 for entity in preview.entities)
        assert all(
            not face.owner_body_keys for face in preview.entities if face.dimension == 2
        )
    if primitive == "line":
        assert next(
            entity for entity in preview.entities if entity.dimension == 1
        ).length == pytest.approx(5)
    if primitive == "cylinder":
        wall = next(
            entity for entity in preview.entities if entity.geometric_type == "Cylinder"
        )
        assert wall.normal is None
        assert "varies" in wall.normal_information


def test_old_preview_is_upgraded_without_changing_legacy_artifact(cad, monkeypatch):
    project, preview, service, _, generator = cad
    old = next(
        item
        for item in service.store.list_by_project(project)
        if item.type.value == "geometry_preview"
    )
    path = service.store.resolve_path(old.id)
    legacy = preview.model_dump(
        exclude={
            "topology_version",
            "entities",
            "vertex_point_indices",
            "vertex_entity_keys",
            "edge_segments",
            "edge_entity_keys",
        },
        mode="json",
    )
    path.write_text(json.dumps(legacy), encoding="utf-8")
    original = path.read_bytes()
    upgrades = []

    def regenerate(command, **kwargs):
        upgrades.append(command)
        generator.generate(preview.geometry_revision_id, coordinate_units="mm")

    monkeypatch.setattr("simassist.projects.cad_geometry.subprocess.run", regenerate)
    assert (
        service.preview(project, preview.geometry_revision_id).entities
        == preview.entities
    )
    assert path.read_bytes() == original
    assert (
        service.preview(project, preview.geometry_revision_id).entities
        == preview.entities
    )
    assert len(upgrades) == 1


def test_multibody_face_ownership_matches_the_actual_volume(tmp_path):
    project = uuid4()
    path = tmp_path / "two-bodies.step"
    gmsh.initialize()
    try:
        gmsh.model.add("Two bodies")
        gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
        gmsh.model.occ.addBox(3, 0, 0, 2, 2, 2)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    store = LocalArtifactStore(tmp_path / "artifacts")
    revision = store.save(
        ArtifactCreate(project_id=project, type="geometry", source_path=path)
    ).id
    preview_id = GmshPreviewService(tmp_path / "previews", store, project).generate(
        revision
    )
    preview = GeometryPreview.model_validate_json(
        store.resolve_path(preview_id).read_text()
    )
    bodies = {
        entity.entity_key: entity
        for entity in preview.entities
        if entity.dimension == 3
    }
    assert len(bodies) == 2
    assert sorted(body.volume for body in bodies.values()) == pytest.approx([1, 8])
    for face in (entity for entity in preview.entities if entity.dimension == 2):
        assert len(face.owner_body_keys) == 1
        body = bodies[face.owner_body_keys[0]]
        assert face.entity_key in body.boundary_entity_keys
        assert all(
            body.bounds[axis] - 1e-6 <= face.bounds[axis]
            and face.bounds[axis + 3] <= body.bounds[axis + 3] + 1e-6
            for axis in range(3)
        )
