from uuid import uuid4

import pytest
from simassist.core.models.geometry import GeometrySpec, PrimitiveGeometry
from simassist.simulation.geometry.gmsh_adapter import GmshGeometryAdapter
from simassist.simulation.visualization.gmsh_preview import (
    GeometryPreview,
    GmshPreviewService,
)
from simassist.storage.local import LocalArtifactStore


def test_selection_api_validates_revision_ownership_and_survives_restart(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient
    from simassist.jobs.manager import JobManager
    from simassist.jobs.models import JobType
    from simassist.main import app
    from simassist.projects.context import ProjectContextRepository
    from simassist.workers.runner import SimulationWorker

    monkeypatch.chdir(tmp_path)
    worker = SimulationWorker(tmp_path / "data")
    manager = JobManager(worker.repository)
    project = uuid4()

    def create():
        job = manager.submit(
            project,
            JobType.GEOMETRY_CREATE,
            {
                "name": "Block",
                "units": "mm",
                "definition": {
                    "source": "primitive",
                    "primitive": "box",
                    "parameters": {"length": 2, "width": 3, "height": 4},
                },
            },
        )
        completed = worker.process_next()
        assert completed.status.value == "completed", completed.error
        return job.id, completed.result["artifact_id"]

    first, revision = create()
    context = ProjectContextRepository(tmp_path / "data/jobs.db", worker.repository)
    context.set_active_geometry(project, first)
    with TestClient(app) as client:
        base = f"/api/projects/{project}"
        faces = client.get(f"{base}/geometries/{revision}/faces")
        assert faces.status_code == 200
        face = faces.json()[0]
        request = {"geometry_revision_id": revision, "face_key": face["face_key"]}
        assert client.put(f"{base}/cad-selection", json=request).status_code == 200
        selected = client.get(f"{base}/cad-selection").json()
        assert selected["selection"] == face
        import json

        from simassist.agents.context import RoutingContext
        from simassist.agents.orchestrator import compose
        from simassist.agents.tools.geometry import GeometryTools
        from simassist.agents.tools.simulation_tools import SimulationTools

        tools = SimulationTools(GeometryTools(manager, project), context)
        composition = compose(
            "Which surface did I select?", RoutingContext(project_id=project), tools
        )
        assert "get_selected_cad_face" in {fn.__name__ for fn in composition.tools}
        assert json.loads(tools.get_selected_cad_face())["selection"] == face
        assert (
            json.loads(tools.inspect_cad_face(revision, face["face_key"]))["face"]
            == face
        )
        assert len(json.loads(tools.list_cad_faces())["faces"]) == 6
        # A new repository/process sees the same valid selection.
        assert (
            ProjectContextRepository(context.db_path, worker.repository)
            .get(project)
            .selected_cad_face_key
            == face["face_key"]
        )
        other = f"/api/projects/{uuid4()}"
        assert client.get(f"{other}/geometries/{revision}/faces").status_code == 404
        assert client.put(f"{other}/cad-selection", json=request).status_code in (
            404,
            409,
        )
        assert (
            client.put(
                f"{base}/cad-selection", json={**request, "face_key": "face:999"}
            ).status_code
            == 409
        )
        second, new_revision = create()
        context.set_active_geometry(project, second)
        assert client.put(f"{base}/cad-selection", json=request).status_code == 409
        assert client.get(f"{base}/geometries/{revision}/faces").status_code == 409
        assert client.get(f"{base}/cad-selection").json()["selection"] is None
        assert json.loads(tools.get_selected_cad_face())["clarification_required"]
        new_face = client.get(f"{base}/geometries/{new_revision}/faces").json()[0]
        assert new_face["face_key"] != face["face_key"]
        assert (
            client.put(
                f"{base}/cad-selection",
                json={
                    "geometry_revision_id": new_revision,
                    "face_key": face["face_key"],
                },
            ).status_code
            == 409
        )
        context.set_active_geometry(project, first)
        assert client.get(f"{base}/cad-selection").json()["selection"] is None


def test_box_preview_has_authoritative_face_provenance(tmp_path):
    project = uuid4()
    store = LocalArtifactStore(tmp_path / "artifacts")
    engine = GmshGeometryAdapter(tmp_path / "geometry", store, project)
    geometry = engine.create(
        GeometrySpec(
            name="Block",
            definition=PrimitiveGeometry(
                primitive="box", parameters={"length": 2, "width": 3, "height": 4}
            ),
        )
    )
    preview_id = GmshPreviewService(tmp_path / "previews", store, project).generate(
        geometry.artifact_id, coordinate_units="mm"
    )
    preview = GeometryPreview.model_validate_json(
        store.resolve_path(preview_id).read_text()
    )
    assert preview.geometry_revision_id == geometry.artifact_id
    assert len(preview.faces) == 6
    assert len(preview.triangle_face_keys) == preview.triangle_count
    assert set(preview.triangle_face_keys) == {face.face_key for face in preview.faces}
    assert sorted(face.area for face in preview.faces) == pytest.approx(
        [6, 6, 8, 8, 12, 12]
    )
    for face in preview.faces:
        assert str(geometry.artifact_id) in face.face_key
        assert face.geometry_revision_id == geometry.artifact_id
        assert face.area_units == "mm^2"
        assert face.geometric_type == "Plane"
        assert sum(n * n for n in face.normal) == pytest.approx(1)
        # Every owning triangle lies in the authoritative OCC face bounds.
        for triangle, key in zip(
            preview.triangles, preview.triangle_face_keys, strict=True
        ):
            if key == face.face_key:
                for index in triangle:
                    assert all(
                        face.bounds[axis] - 1e-6
                        <= value
                        <= face.bounds[axis + 3] + 1e-6
                        for axis, value in enumerate(preview.points[index])
                    )


@pytest.mark.parametrize(
    ("primitive", "parameters", "face_count", "dimension"),
    [
        ("rectangle", {"width": 2, "height": 3}, 1, 2),
        ("cylinder", {"radius": 2, "height": 3}, 3, 3),
    ],
)
def test_planar_and_curved_metadata_without_fem_mesh(
    tmp_path, primitive, parameters, face_count, dimension
):
    import math

    project = uuid4()
    store = LocalArtifactStore(tmp_path / "artifacts")
    geometry = GmshGeometryAdapter(tmp_path / "geometry", store, project).create(
        GeometrySpec(
            name="Surface",
            definition=PrimitiveGeometry(primitive=primitive, parameters=parameters),
        )
    )
    preview_service = GmshPreviewService(tmp_path / "previews", store, project)
    preview_id = preview_service.generate(geometry.artifact_id, coordinate_units="cm")
    preview = GeometryPreview.model_validate_json(
        store.resolve_path(preview_id).read_text()
    )
    assert preview.dimension == dimension
    assert len(preview.faces) == face_count
    assert len(preview.triangle_face_keys) == preview.triangle_count
    assert all(face.area_units == "cm^2" for face in preview.faces)
    if primitive == "rectangle":
        assert preview.faces[0].area == pytest.approx(6)
        assert preview.faces[0].normal is not None
    else:
        wall = next(face for face in preview.faces if face.geometric_type == "Cylinder")
        assert wall.area == pytest.approx(12 * math.pi)
        assert wall.normal is None
        assert "varies" in wall.normal_information
    assert all(item.type.value != "mesh" for item in store.list_by_project(project))
    again = preview_service.generate(geometry.artifact_id, coordinate_units="cm")
    restored = GeometryPreview.model_validate_json(
        store.resolve_path(again).read_text()
    )
    assert restored.faces == preview.faces


def test_legacy_preview_upgrade_preserves_original_artifacts(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient
    from simassist.core.models.artifact import ArtifactCreate
    from simassist.jobs.manager import JobManager
    from simassist.jobs.models import JobType
    from simassist.jobs.repository import JobRepository
    from simassist.main import app
    from simassist.projects.context import ProjectContextRepository

    monkeypatch.chdir(tmp_path)
    project = uuid4()
    store = LocalArtifactStore(tmp_path / "data/artifacts")
    geometry = GmshGeometryAdapter(tmp_path / "geometry", store, project).create(
        GeometrySpec(
            name="Old block",
            definition=PrimitiveGeometry(
                primitive="box", parameters={"length": 2, "width": 3, "height": 4}
            ),
        )
    )
    source = tmp_path / "legacy-preview.json"
    source.write_text(
        json.dumps(
            {"points": [], "triangles": [], "point_count": 0, "triangle_count": 0}
        )
    )
    legacy = store.save(
        ArtifactCreate(
            project_id=project,
            type="geometry_preview",
            source_path=source,
            parent_ids=[geometry.artifact_id],
        )
    )
    original = {
        artifact.id: store.resolve_path(artifact.id).read_bytes()
        for artifact in store.list_by_project(project)
    }
    jobs = JobRepository(tmp_path / "data/jobs.db")
    job = JobManager(jobs).submit(project, JobType.GEOMETRY_CREATE, {"units": "mm"})
    jobs.claim_next()
    jobs.complete(
        job.id,
        {
            "artifact_id": str(geometry.artifact_id),
            "preview_artifact_id": str(legacy.id),
        },
    )
    ProjectContextRepository(jobs.db_path, jobs).set_active_geometry(project, job.id)
    with TestClient(app) as client:
        url = f"/api/projects/{project}/cad-previews/{legacy.id}"
        response = client.get(url)
        assert response.status_code == 200, response.text
        assert len(response.json()["faces"]) == 6
        assert response.json()["geometry_revision_id"] == str(geometry.artifact_id)
        assert len(store.list_by_project(project)) == 3
        assert client.get(url).json() == response.json()
        assert len(store.list_by_project(project)) == 3
    for artifact_id, content in original.items():
        assert store.resolve_path(artifact_id).read_bytes() == content
