import json
from uuid import UUID, uuid4

import pytest
from simassist.conversations.budget import ContextBudget
from simassist.conversations.context_service import ConversationContextService
from simassist.projects.workspace import WorkspaceRepository


@pytest.fixture
def conversation(tmp_path):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    chat = UUID(store.new_chat(project)["id"])
    return store, project, chat


def test_roles_isolation_restart_and_current_once(conversation):
    store, project, chat = conversation
    store.append(project, chat, "user", "create annulus")
    store.append(project, chat, "assistant", "job submitted")
    service = ConversationContextService(WorkspaceRepository(store.db_path))
    result = service.build(project, chat, "mesh it", "instructions", [])
    assert [m.role for m in result.messages] == ["user", "assistant", "user"]
    assert [m.text for m in result.messages] == [
        "create annulus",
        "job submitted",
        "mesh it",
    ]
    other = UUID(store.new_chat(project)["id"])
    assert len(service.build(project, other, "hi", "", []).messages) == 1
    with pytest.raises(KeyError):
        service.build(uuid4(), chat, "hi", "", [])


def test_summary_pressure_watermark_and_deletion(conversation):
    store, project, chat = conversation
    for i in range(30):
        store.append(project, chat, "user", f"User parameter {i} mm " * 6)
        store.append(project, chat, "assistant", f"Unverified reference {i} " * 6)
    budget = ContextBudget(window=1400, response=100, safety=100, summary=220)
    service = ConversationContextService(store, budget)
    result = service.build(project, chat, "current", "instructions", [])
    assert result.summary_status == "updated"
    assert result.tokens <= budget.available
    summary = store.summary(project, chat)
    assert summary["watermark"] > 0
    loaded = [m.text for m in result.messages[1:-1]]
    covered = [
        m["content"]
        for m in store.messages(project, chat)
        if m["id"] <= summary["watermark"]
    ]
    assert not set(loaded).intersection(covered)
    again = service.build(project, chat, "current", "instructions", [])
    assert again.watermark == result.watermark
    store.delete_chat(project, chat)
    with store._connect() as db:
        assert not db.execute("SELECT * FROM conversation_summaries").fetchall()
    with pytest.raises(KeyError):
        service.build(project, chat, "hi", "", [])


def test_budget_failure_disabled_and_summary_failure(conversation, monkeypatch):
    store, project, chat = conversation
    service = ConversationContextService(
        store, ContextBudget(window=900, response=100, safety=100)
    )
    with pytest.raises(ValueError, match="Shorten"):
        service.build(project, chat, "X" * 3000, "instructions", [])
    for _ in range(10):
        store.append(project, chat, "user", "keep the existing 0.1 mm sizes " * 15)
        store.append(project, chat, "assistant", "proposal pending " * 15)

    def fail(*args):
        raise RuntimeError("offline")

    monkeypatch.setattr(store, "save_summary", fail)
    result = service.build(project, chat, "current", "", [])
    assert result.summary_status == "failed"
    assert result.tokens <= service.budget.available
    disabled = ConversationContextService(
        store, ContextBudget(window=900, response=100, safety=100, auto_summary=False)
    )
    assert disabled.build(project, chat, "current", "", []).summary_status == "skipped"
    assert store.summary(project, chat) is None


def test_turn_lifecycle_idempotency_concurrency_and_failed_history(conversation):
    store, project, chat = conversation
    request = uuid4()
    assert store.begin_turn(project, chat, request, "mesh it") is None
    # A second repository models another process, sharing the SQLite exclusion.
    second = WorkspaceRepository(store.db_path)
    with pytest.raises(ValueError):
        second.begin_turn(project, chat, uuid4(), "duplicate")
    with pytest.raises(ValueError):
        second.begin_turn(project, chat, request, "mesh it")
    with pytest.raises(ValueError):
        store.delete_chat(project, chat)
    independent = UUID(store.new_chat(project)["id"])
    assert second.begin_turn(project, independent, uuid4(), "other chat") is None
    assert store.context_messages(project, chat) == []
    store.finish_turn(request, "completed", "submitted", ["job-1"])
    store.finish_turn(request, "completed", "duplicate", [])
    replay = second.begin_turn(project, chat, request, "mesh it")
    assert json.loads(replay["job_ids"]) == ["job-1"]
    assert len(store.messages(project, chat)) == 2
    failed = uuid4()
    store.begin_turn(project, chat, failed, "failed requirement")
    store.finish_turn(failed, "failed", None, ["job-2"])
    assert len(store.messages(project, chat)) == 3
    assert len(store.context_messages(project, chat)) == 2
    with pytest.raises(ValueError):
        store.begin_turn(project, chat, failed, "failed requirement")
    store.delete_chat(project, chat)
    with store._connect() as db:
        assert not db.execute(
            "SELECT * FROM conversation_turns WHERE chat_id=?", (str(chat),)
        ).fetchall()


def test_summary_growth_never_overfills_context(conversation):
    store, project, chat = conversation
    from simassist.conversations.summary import summarize

    for i in range(6):
        store.append(project, chat, "user", f"parameter {i}: " + "a" * 120)
        store.append(project, chat, "assistant", "unverified job reference " * 5)
    budget = ContextBudget(window=1100, response=100, safety=100, summary=300)
    service = ConversationContextService(store, budget)
    for i in range(12):
        result = service.build(project, chat, "current request", "", [])
        assert result.tokens <= budget.available
        store.append(project, chat, "user", f"New engineering intent {i} " * 7)
        store.append(project, chat, "assistant", "clarification " * 10)
    assert (
        summarize(
            None,
            [
                {"id": 1, "role": "user", "content": "password=do-not-store"},
                {"id": 2, "role": "assistant", "content": "Acknowledged"},
            ],
            300,
        )
        == "[]"
    )


def test_configuration_and_schema_overhead(monkeypatch):
    from agent_framework import tool
    from simassist.agents.simulation_agent import (
        SIMULATION_AGENT_INSTRUCTIONS,
        simulation_agent_tools,
    )
    from simassist.agents.tools.geometry import GeometryTools
    from simassist.agents.tools.simulation_tools import SimulationTools

    monkeypatch.setenv("SIMASSIST_CONTEXT_WINDOW_TOKENS", "4096")
    budget = ContextBudget.from_env()
    tools = SimulationTools(GeometryTools(job_manager=None, project_id=uuid4()))
    schemas = [tool(fn).to_json_schema_spec() for fn in simulation_agent_tools(tools)]
    with pytest.raises(ValueError):
        ConversationContextService(None, budget).build(
            uuid4(), None, "hi", SIMULATION_AGENT_INSTRUCTIONS, schemas
        )
    result = ConversationContextService(None, ContextBudget()).build(
        uuid4(), None, "hi", SIMULATION_AGENT_INSTRUCTIONS, schemas
    )
    assert result.tokens <= ContextBudget().available


def test_reasoning_response_reserve_is_budgeted_and_remains_configurable(monkeypatch):
    monkeypatch.delenv("SIMASSIST_RESPONSE_RESERVE_TOKENS", raising=False)
    default = ContextBudget.from_env()
    assert default.response == 2048
    assert default.available + default.response + default.safety == default.window
    monkeypatch.setenv("SIMASSIST_RESPONSE_RESERVE_TOKENS", "1024")
    override = ContextBudget.from_env()
    assert override.response == 1024
    assert override.available == default.available + 1024


def test_additive_migration_preserves_legacy_rows(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    project, chat = uuid4(), uuid4()
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE workspace_projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE workspace_chats(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,title TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE workspace_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE jobs(id TEXT PRIMARY KEY, payload TEXT);
            INSERT INTO jobs VALUES ('keep-job', 'keep-artifact');
        """)
        db.execute(
            "INSERT INTO workspace_projects VALUES (?,?,?)",
            (str(project), "legacy", "today"),
        )
        db.execute(
            "INSERT INTO workspace_chats VALUES (?,?,?,?)",
            (str(chat), str(project), "legacy", "today"),
        )
        db.execute(
            "INSERT INTO workspace_messages(chat_id,role,content,created_at) VALUES (?,?,?,?)",
            (str(chat), "user", "original engineering requirement", "today"),
        )
        db.execute(
            "INSERT INTO workspace_messages(chat_id,role,content,created_at) VALUES (?,?,?,?)",
            (str(chat), "assistant", "original response", "today"),
        )
    store = WorkspaceRepository(db_path)
    assert [m["content"] for m in store.messages(project, chat)] == [
        "original engineering requirement",
        "original response",
    ]
    assert store.summary(project, chat) is None
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT * FROM jobs").fetchall() == [
            ("keep-job", "keep-artifact")
        ]
    assert (
        len(
            ConversationContextService(store)
            .build(project, chat, "next", "", [])
            .messages
        )
        == 3
    )
