from uuid import UUID, uuid4

import pytest
from simassist.projects.workspace import WorkspaceRepository


def test_independent_chats_and_delete(tmp_path):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    chat_a = UUID(store.new_chat(project)["id"])
    chat_b = UUID(store.new_chat(project)["id"])
    store.append(project, chat_a, "user", "Create an annulus")
    store.append(project, chat_a, "assistant", "Done")
    assert len(store.messages(project, chat_a)) == 2
    assert store.messages(project, chat_b) == []
    assert store.chats(project)[1]["title"] == "Create an annulus"
    store.delete_chat(project, chat_a)
    assert len(store.chats(project)) == 1
    with pytest.raises(KeyError):
        store.messages(project, chat_a)


def test_cross_project_chat_access_forbidden(tmp_path):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    a = UUID(store.new_project("A")["id"])
    b = UUID(store.new_project("B")["id"])
    chat = UUID(store.new_chat(a)["id"])
    with pytest.raises(KeyError):
        store.messages(b, chat)
    with pytest.raises(KeyError):
        store.delete_chat(b, chat)


def test_geometry_soft_delete_and_rename(tmp_path):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    job = uuid4()
    store.update_geometry(project, job, name="Annulus 2D")
    assert store.geometry_overrides(project)[str(job)]["display_name"] == "Annulus 2D"
    store.update_geometry(project, job, deleted=True)
    assert store.geometry_overrides(project)[str(job)]["deleted"] == 1
    # A soft delete does not touch job or artifact tables.


def test_legacy_import_idempotent(tmp_path):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    assert store.import_legacy()["id"] == store.import_legacy()["id"]
    assert len(store.projects()) == 1


def test_default_project_reuses_empty_chats_and_preserves_content(tmp_path):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    empty = store.new_project()
    store.new_chat(UUID(empty["id"]))  # The UI creates this automatically.
    populated = store.new_project()
    chat = store.new_chat(UUID(populated["id"]))
    store.append(
        UUID(populated["id"]), UUID(chat["id"]), "user", "Keep this discussion"
    )
    assert store.open_default_project()["id"] == empty["id"]
    assert len(store.projects()) == 2
    # Naming the empty project makes it intentional, so startup leaves it alone.
    store.rename_project(UUID(empty["id"]), "Wing study")
    fresh = store.open_default_project()
    assert fresh["id"] not in (empty["id"], populated["id"])
    assert store.open_default_project()["id"] == fresh["id"]
    assert (
        store.messages(UUID(populated["id"]), UUID(chat["id"]))[0]["content"]
        == "Keep this discussion"
    )


def test_default_project_does_not_reuse_projects_with_engineering_data(tmp_path):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    jobs_project = store.new_project()
    geometry_project = store.new_project()
    selected_project = store.new_project()
    with store._connect() as db:
        db.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY,project_id TEXT)")
        db.execute("INSERT INTO jobs VALUES (?,?)", (str(uuid4()), jobs_project["id"]))
        db.execute(
            "CREATE TABLE project_context(project_id TEXT PRIMARY KEY, "
            "active_geometry_job_id TEXT, active_geometry_artifact_id TEXT)"
        )
        db.execute(
            "INSERT INTO project_context VALUES (?,?,?)",
            (selected_project["id"], str(uuid4()), str(uuid4())),
        )
    store.update_geometry(UUID(geometry_project["id"]), uuid4(), deleted=True)
    assert store.open_default_project()["id"] not in {
        jobs_project["id"],
        geometry_project["id"],
        selected_project["id"],
    }


def test_simultaneous_startup_claims_one_default_project(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "jobs.db"
    store = WorkspaceRepository(db_path)

    def startup(_):
        return WorkspaceRepository(db_path).open_default_project()["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(startup, range(8)))
    assert len(set(ids)) == 1
    assert len(store.projects()) == 1


def test_default_project_and_rename_api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from simassist.api.routes import workspace

    store = WorkspaceRepository(tmp_path / "jobs.db")
    monkeypatch.setattr(workspace, "repo", lambda: store)
    app = FastAPI()
    app.include_router(workspace.router)
    with TestClient(app) as client:
        first = client.post("/api/workspace/projects/default").json()
        assert (
            client.post("/api/workspace/projects/default").json()["id"] == first["id"]
        )
        response = client.patch(
            f"/api/workspace/projects/{first['id']}", json={"name": "  Wing study  "}
        )
        assert response.status_code == 200
        assert WorkspaceRepository(store.db_path).projects()[0]["name"] == "Wing study"
        assert (
            client.post("/api/workspace/projects/default").json()["id"] != first["id"]
        )
        # Explicit New Project still always creates a new project.
        explicit = client.post(
            "/api/workspace/projects", json={"name": "Untitled Project"}
        ).json()
        assert explicit["id"] != first["id"]


def test_project_delete_cleans_owned_memory_and_preserves_engineering_records(tmp_path):
    from simassist.projects.remesh_proposals import RemeshProposalStore

    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project("Delete me")["id"])
    other = UUID(store.new_project("Keep me")["id"])
    chat = UUID(store.new_chat(project)["id"])
    other_chat = UUID(store.new_chat(other)["id"])
    request = uuid4()
    store.begin_turn(project, chat, request, "Create a mesh")
    store.finish_turn(request, "completed", "Submitted job", ["keep-job"])
    store.save_summary(project, chat, 2, "[]")
    store.append(other, other_chat, "user", "Keep my conversation")
    proposals = RemeshProposalStore(store.db_path)
    proposals.save(chat, {"intent": "delete scoped proposal"})
    proposals.save(project, {"intent": "delete legacy project proposal"})
    proposals.save(other_chat, {"intent": "keep scoped proposal"})
    store.update_geometry(project, uuid4(), name="Deleted project geometry")
    with store._connect() as db:
        db.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY, project_id TEXT)")
        db.execute("INSERT INTO jobs VALUES (?,?)", ("keep-job", str(project)))
        db.execute(
            "CREATE TABLE project_context(project_id TEXT PRIMARY KEY, active_geometry_job_id TEXT)"
        )
        db.execute(
            "INSERT INTO project_context VALUES (?,?)", (str(project), "keep-job")
        )
    artifact = tmp_path / "saved-simulation.step"
    artifact.write_text("preserved engineering artifact")
    store.delete_project(project)
    assert [p["id"] for p in store.projects()] == [str(other)]
    assert store.messages(other, other_chat)[0]["content"] == "Keep my conversation"
    assert proposals.get(chat) is None
    assert proposals.get(project) is None
    assert proposals.get(other_chat) is not None
    with store._connect() as db:
        for table in ("conversation_summaries", "conversation_turns"):
            assert not db.execute(
                f"SELECT 1 FROM {table} WHERE chat_id=?", (str(chat),)
            ).fetchall()
        assert not db.execute(
            "SELECT 1 FROM workspace_messages WHERE chat_id=?", (str(chat),)
        ).fetchall()
        assert not db.execute(
            "SELECT 1 FROM workspace_chats WHERE id=?", (str(chat),)
        ).fetchall()
        assert not db.execute(
            "SELECT 1 FROM workspace_geometries WHERE project_id=?", (str(project),)
        ).fetchall()
        assert not db.execute(
            "SELECT 1 FROM project_context WHERE project_id=?", (str(project),)
        ).fetchall()
        assert (
            db.execute(
                "SELECT id FROM jobs WHERE project_id=?", (str(project),)
            ).fetchone()[0]
            == "keep-job"
        )
    assert artifact.read_text() == "preserved engineering artifact"
    for action in (
        lambda: store.delete_project(project),
        lambda: store.new_chat(project),
        lambda: store.chats(project),
        lambda: store.messages(project, chat),
    ):
        with pytest.raises(KeyError):
            action()


def test_project_delete_blocks_active_turn_without_partial_deletion(tmp_path):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    chat = UUID(store.new_chat(project)["id"])
    request = uuid4()
    store.begin_turn(project, chat, request, "Still running")
    with pytest.raises(ValueError, match="active or interrupted"):
        WorkspaceRepository(store.db_path).delete_project(project)
    assert len(store.projects()) == 1
    assert len(store.messages(project, chat)) == 1
    store.finish_turn(request, "interrupted", None, [])
    store.delete_project(project)
    assert store.projects() == []


def test_project_delete_api_errors_and_deleted_chat_cannot_be_recreated(
    tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from simassist.api.routes import workspace

    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    chat = UUID(store.new_chat(project)["id"])
    request = uuid4()
    store.begin_turn(project, chat, request, "Still running")
    monkeypatch.setattr(workspace, "repo", lambda: store)
    app = FastAPI()
    app.include_router(workspace.router)
    with TestClient(app) as client:
        path = f"/api/workspace/projects/{project}"
        assert client.delete(path).status_code == 409
        store.finish_turn(request, "failed", None, [])
        assert client.delete(path).status_code == 200
        assert client.get("/api/workspace/projects").json() == []
        assert client.delete(path).status_code == 404
        assert client.post(f"{path}/chats").status_code == 404
        assert client.get(f"{path}/chats").status_code == 404
        assert client.get(f"{path}/chats/{chat}/messages").status_code == 404
        assert client.delete("/api/workspace/projects/not-a-uuid").status_code == 422
        assert client.post("/api/workspace/projects/default").json()["id"] != str(
            project
        )
