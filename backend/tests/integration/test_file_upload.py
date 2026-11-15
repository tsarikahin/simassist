"""STEP upload, chat ownership, import and verified mesh vertical slice."""

import hashlib
import json
from uuid import UUID, uuid4

import gmsh
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from simassist.api.routes import files as file_routes
from simassist.files.repository import FileRepository
from simassist.projects.workspace import WorkspaceRepository


@pytest.fixture
def upload_api(tmp_path, monkeypatch):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    other = UUID(store.new_project()["id"])
    monkeypatch.setattr(file_routes, "get_data_root", lambda: tmp_path)
    app = FastAPI()
    app.add_middleware(file_routes.UploadLimitMiddleware)
    app.include_router(file_routes.router)
    path = tmp_path / "box.step"
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("upload_fixture")
        gmsh.model.occ.addBox(0, 0, 0, 4, 3, 2)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    with TestClient(app) as client:
        yield client, store, project, other, path.read_bytes(), tmp_path


def upload(client, project, data, filename="bracket.step"):
    return client.post(
        f"/api/projects/{project}/files",
        files={"file": (filename, data, "application/octet-stream")},
    )


def test_upload_metadata_original_bytes_and_ownership(upload_api):
    client, store, project, other, data, root = upload_api
    response = upload(client, project, data)
    assert response.status_code == 200, response.text
    item = response.json()
    assert item["inspection"]["dimension"] == 3
    assert item["inspection"]["volume_count"] == 1
    assert item["inspection"]["coordinate_units"] == "mm"
    assert item["content_hash"] == hashlib.sha256(data).hexdigest()
    files = FileRepository(root)
    assert files.resolve(project, item["file_id"]).read_bytes() == data
    assert len(client.get(f"/api/projects/{project}/files").json()) == 1
    assert (
        client.get(f"/api/projects/{other}/files/{item['file_id']}").status_code == 404
    )
    assert client.get(f"/api/projects/{uuid4()}/files").status_code == 404
    assert store.open_default_project()["id"] != str(project)


def test_upload_rejections_do_not_leave_records_or_partial_files(
    upload_api, monkeypatch
):
    client, _, project, _, data, root = upload_api
    for filename, content, status in [
        ("bad.step", b"", 422),
        ("bad.step", b"garbage", 422),
        ("bad.step", b"ISO-10303-21;\ninvalid model\nEND-ISO-10303-21;", 422),
        ("model.msh", data, 415),
        ("model.stl", data, 415),
        ("../model.step", data, 422),
        ("C:/model.step", data, 422),
    ]:
        assert upload(client, project, content, filename).status_code == status
    monkeypatch.setenv("SIMASSIST_MAX_UPLOAD_BYTES", "16")
    assert upload(client, project, data).status_code == 413
    # Limit the raw body while multipart is being consumed, before disk spooling.
    assert upload(client, project, b"X" * 100_000).status_code == 413
    monkeypatch.setenv("SIMASSIST_MAX_UPLOAD_BYTES", str(32 * 1024 * 1024))
    monkeypatch.setenv("SIMASSIST_PROJECT_UPLOAD_QUOTA_BYTES", "1")
    assert upload(client, project, data).status_code == 422
    assert FileRepository(root).list(project) == []
    assert not list((root / "uploads").rglob("*.part"))
    assert not list((root / "uploads").rglob("*.step"))


def test_import_mesh_pipeline_and_explicit_settings(upload_api):
    from simassist.agents.tools.geometry import GeometryTools
    from simassist.agents.tools.simulation_tools import SimulationTools
    from simassist.jobs.manager import JobManager
    from simassist.jobs.models import JobStatus, JobType
    from simassist.projects.context import ProjectContextRepository
    from simassist.workers.runner import SimulationWorker

    client, _store, project, other, data, root = upload_api
    item = upload(client, project, data).json()
    worker = SimulationWorker(root)
    manager = JobManager(worker.repository)
    context = ProjectContextRepository(root / "jobs.db", worker.repository)
    tools = SimulationTools(GeometryTools(manager, project), context, uuid4())
    assert (
        json.loads(tools.inspect_uploaded_file(item["file_id"]))["file"]["inspection"][
            "volume_count"
        ]
        == 1
    )
    assert json.loads(tools.mesh_uploaded_geometry(item["file_id"]))[
        "clarification_required"
    ]
    assert manager.list_by_project(project) == []
    assert not json.loads(
        tools.mesh_uploaded_geometry(item["file_id"], 0.5, 1, "mm", "hexahedral")
    )["ok"]
    assert manager.list_by_project(project) == []
    result = json.loads(
        tools.mesh_uploaded_geometry(item["file_id"], 0.05, 0.1, "cm", "tetrahedral")
    )
    assert result["ok"]
    assert len(manager.list_by_project(project)) == 2
    assert result["normalized_settings_mm"]["min_size"] == 0.5
    # A repeated model tool call in this request cannot queue a duplicate workflow.
    tools.mesh_uploaded_geometry(item["file_id"], 0.05, 0.1, "cm", "tetrahedral")
    assert len(manager.list_by_project(project)) == 2
    geometry = worker.process_next()
    assert geometry.status == JobStatus.COMPLETED, geometry.error
    assert geometry.type == JobType.GEOMETRY_CREATE
    assert geometry.result["source_file_id"] == item["file_id"]
    assert geometry.result["source_content_hash"] == item["content_hash"]
    assert geometry.result["preview_artifact_id"]
    mesh = worker.process_next()
    assert mesh.status == JobStatus.COMPLETED, mesh.error
    assert mesh.result["metadata"]["node_count"] > 0
    assert mesh.result["metadata"]["volume_element_types"]
    # Import-only is durable/idempotent, while each deliberate remesh creates a version.
    assert FileRepository(root).submit_import(project, UUID(item["file_id"])) == (
        geometry.id,
        [],
    )
    tools.mesh_uploaded_geometry(item["file_id"], 0.8, 1.2, "mm", "tetrahedral")
    second = worker.process_next()
    assert second.status == JobStatus.COMPLETED, second.error
    assert second.result["artifact_id"] != mesh.result["artifact_id"]
    assert FileRepository(root).resolve(project, item["file_id"]).read_bytes() == data
    other_tools = SimulationTools(GeometryTools(manager, other), context, uuid4())
    assert not json.loads(other_tools.inspect_uploaded_file(item["file_id"]))["ok"]
    assert not json.loads(other_tools.import_uploaded_geometry(item["file_id"]))["ok"]
    context.set_active_geometry(project, geometry.id)
    assert json.loads(tools.get_active_mesh_info())["mesh_version_count"] == 2
    assert (
        FileRepository(root).get(project, item["file_id"])["import_status"]
        == "completed"
    )


def test_persistent_attachment_history_and_retry_identity(upload_api):
    from simassist.api.routes.chat import ChatRequest
    from simassist.conversations.context_service import ConversationContextService

    client, store, project, other, data, root = upload_api
    item = upload(client, project, data).json()
    a, b = [UUID(store.new_chat(project)["id"]) for _ in range(2)]
    request_id = uuid4()
    store.begin_turn(project, a, request_id, "mesh this file", [item["file_id"]])
    store.finish_turn(request_id, "completed", "Please confirm sizes and units", [])
    restored = WorkspaceRepository(root / "jobs.db")
    message = restored.messages(project, a)[0]
    assert message["content"] == "mesh this file"
    assert message["attachments"][0]["filename"] == "bracket.step"
    assert restored.messages(project, b) == []
    context = ConversationContextService(restored).build(
        project, a, "0.5 to 1 mm", "", []
    )
    assert item["file_id"] in context.messages[0].text
    other_context = ConversationContextService(restored).build(project, b, "hi", "", [])
    assert item["file_id"] not in str(other_context.messages)
    assert (
        restored.begin_turn(
            project, a, request_id, "mesh this file", [item["file_id"]]
        )["status"]
        == "completed"
    )
    with pytest.raises(ValueError, match="different attachments"):
        restored.begin_turn(project, a, request_id, "mesh this file", [])
    foreign_chat = UUID(store.new_chat(other)["id"])
    with pytest.raises(KeyError):
        store.begin_turn(
            other, foreign_chat, uuid4(), "use foreign file", [item["file_id"]]
        )
    assert store.messages(other, foreign_chat) == []
    with pytest.raises(ValueError):
        ChatRequest(
            project_id=project,
            message="hi",
            attachments=[{"file_id": item["file_id"]}] * 5,
        )
    restored.delete_chat(project, a)
    with restored._connect() as db:
        assert not db.execute("SELECT * FROM chat_message_attachments").fetchall()
    assert FileRepository(root).resolve(project, item["file_id"]).read_bytes() == data


def test_attachment_references_through_sync_and_stream_chat(upload_api, monkeypatch):
    from types import SimpleNamespace

    from simassist.api.dependencies import (
        get_job_manager,
        get_project_context_repository,
    )
    from simassist.api.routes import chat as chat_routes

    client, store, project, other, data, root = upload_api
    file = upload(client, project, data).json()
    chat = UUID(store.new_chat(project)["id"])
    app = client.app
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_job_manager] = lambda: None
    app.dependency_overrides[get_project_context_repository] = lambda: SimpleNamespace(
        db_path=root / "jobs.db"
    )
    monkeypatch.setattr(chat_routes, "_workspace", lambda: store)
    agents = []

    class Stream:
        async def __aiter__(self):
            yield SimpleNamespace(text="Please confirm sizes")

        async def get_final_response(self):
            return SimpleNamespace(text="Please confirm sizes")

    class Agent:
        closed = False

        def run(self, messages, stream=False, options=None):
            self.messages = messages
            if stream:
                return Stream()

            async def result():
                return SimpleNamespace(text="Please confirm sizes")

            return result()

        async def close(self):
            self.closed = True

    def build(**kwargs):
        agent = Agent()
        agents.append(agent)
        return agent

    monkeypatch.setattr(chat_routes, "build_simulation_agent", build)
    body = {
        "project_id": str(project),
        "chat_id": str(chat),
        "request_id": str(uuid4()),
        "message": "Mesh the attached CAD",
        "attachments": [{"file_id": file["file_id"]}],
    }
    for endpoint in ("/api/chat", "/api/chat/stream"):
        body["request_id"] = str(uuid4())
        response = client.post(endpoint, json=body)
        assert response.status_code == 200, response.text
        assert agents[-1].closed
        current = agents[-1].messages[-1].text
        assert current.count(file["file_id"]) == 1
        assert "ISO-10303-21" not in current
        assert (
            store.messages(project, chat)[-2]["attachments"][0]["file_id"]
            == file["file_id"]
        )
        # The same key/attachments returns the committed response without running an agent.
        count = len(agents)
        assert client.post(endpoint, json=body).status_code == 200
        assert len(agents) == count
    foreign = UUID(store.new_chat(other)["id"])
    body.update(project_id=str(other), chat_id=str(foreign), request_id=str(uuid4()))
    assert client.post("/api/chat", json=body).status_code == 404
    assert store.messages(other, foreign) == []


def test_changed_original_and_symlink_paths_are_not_imported(upload_api):
    client, _, project, _, data, root = upload_api
    file = upload(client, project, data).json()
    files = FileRepository(root)
    original = files.path(project, file["file_id"])
    original.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        files.resolve(project, file["file_id"])
    # Exercise the same guard Windows junctions/symlinks use without requiring
    # Windows developer mode/privileges to create an actual symlink in the test.
    from unittest.mock import patch

    with (
        patch("pathlib.Path.is_symlink", return_value=True),
        pytest.raises(ValueError, match="Linked"),
    ):
        files.path(project, file["file_id"])


def test_cancelled_upload_cleans_uncommitted_metadata(upload_api, monkeypatch):
    import asyncio
    from io import BytesIO

    from starlette.datastructures import UploadFile

    _, _, project, _, data, root = upload_api

    async def cancelled_parser(path):
        raise asyncio.CancelledError()

    monkeypatch.setattr(file_routes, "parse_step", cancelled_parser)

    async def exercise():
        file = UploadFile(BytesIO(data), filename="cancelled.step", size=len(data))
        with pytest.raises(asyncio.CancelledError):
            await file_routes.upload_file(project, file)
        assert file.file.closed

    asyncio.run(exercise())
    files = FileRepository(root)
    assert files.list(project) == []
    with files.workspace._connect() as db:
        assert not db.execute("SELECT * FROM project_files").fetchall()
    assert not list((root / "uploads").rglob("*.part"))
    assert not list((root / "uploads").rglob("*.step"))


def test_step_source_units_normalized_by_cad_parser(upload_api):
    client, _, project, _, data, _ = upload_api
    assert b"SI_UNIT(.MILLI.,.METRE.)" in data
    meters = data.replace(b"SI_UNIT(.MILLI.,.METRE.)", b"SI_UNIT($,.METRE.)")
    response = upload(client, project, meters, "declared-meters.step")
    assert response.status_code == 200, response.text
    inspection = response.json()["inspection"]
    assert inspection["coordinate_units"] == "mm"
    assert inspection["bounding_box_max"]["x"] == pytest.approx(4000, abs=1e-3)


def test_concurrent_import_registration_and_upload_quotas(upload_api, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    client, _, project, other, data, root = upload_api
    file = upload(client, project, data).json()

    def import_once(_):
        return FileRepository(root).submit_import(project, UUID(file["file_id"]))

    with ThreadPoolExecutor(max_workers=4) as pool:
        imports = list(pool.map(import_once, range(8)))
    assert len({str(geometry_id) for geometry_id, _ in imports}) == 1
    assert sum(len(jobs) for _, jobs in imports) == 1
    monkeypatch.setenv("SIMASSIST_PROJECT_UPLOAD_QUOTA_BYTES", "20")

    def reserve(_):
        try:
            FileRepository(root).reserve(other, "candidate.step", 20)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(8))) == 1


def test_step_parser_works_on_windows_selector_event_loop(upload_api):
    """Reproduce Uvicorn reload's loop, rather than TestClient's Proactor loop."""
    import asyncio

    *_, root = upload_api
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        result = runner.run(file_routes.parse_step(root / "box.step"))
    assert result["dimension"] == 3
    assert result["volume_count"] == 1


def test_step_parser_timeout_kills_and_reaps_process(tmp_path, monkeypatch):
    import asyncio
    import subprocess
    from unittest.mock import MagicMock

    process = MagicMock()
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("cad-inspector", 60),
        (b"", None),
    ]
    popen = MagicMock()
    popen.return_value.__enter__.return_value = process
    monkeypatch.setattr(file_routes.subprocess, "Popen", popen)
    with pytest.raises(ValueError, match="timed out"):
        asyncio.run(file_routes.parse_step(tmp_path / "model.step"))
    process.kill.assert_called_once()
    assert process.communicate.call_count == 2


def test_parser_launch_failure_returns_actionable_http_error(upload_api, monkeypatch):
    client, _, project, _, data, root = upload_api

    def unavailable(*args, **kwargs):
        raise OSError("Cannot launch parser")

    monkeypatch.setattr(file_routes.subprocess, "Popen", unavailable)
    response = upload(client, project, data)
    assert response.status_code == 503
    assert "File processing is unavailable" in response.json()["detail"]
    assert FileRepository(root).list(project) == []
    assert not list((root / "uploads").rglob("*.part"))
