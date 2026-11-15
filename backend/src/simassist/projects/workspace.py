"""Persistent projects, conversations, and non-destructive geometry management."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4


def now() -> str:
    return datetime.now(UTC).isoformat()


class WorkspaceRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workspace_projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspace_chats (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    title TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workspace_chat_project
                    ON workspace_chats(project_id, created_at);
                CREATE TABLE IF NOT EXISTS workspace_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workspace_message_chat
                    ON workspace_messages(chat_id, id);
                CREATE TABLE IF NOT EXISTS workspace_geometries (
                    project_id TEXT NOT NULL, job_id TEXT NOT NULL,
                    display_name TEXT, deleted INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(project_id, job_id)
                );
                -- Additive memory tables; canonical messages keep their original schema.
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    chat_id TEXT PRIMARY KEY, watermark INTEGER NOT NULL,
                    content TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    request_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL,
                    message TEXT NOT NULL, status TEXT NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT,
                    response TEXT, job_ids TEXT NOT NULL DEFAULT '[]',
                    user_message_id INTEGER, assistant_message_id INTEGER
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_running
                    ON conversation_turns(chat_id) WHERE status='started';
                CREATE INDEX IF NOT EXISTS idx_conversation_user_message
                    ON conversation_turns(user_message_id);
            """)

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def projects(self):
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM workspace_projects ORDER BY created_at DESC"
                )
            ]

    def new_project(self, name="Untitled Project"):
        item = {"id": str(uuid4()), "name": name, "created_at": now()}
        with self._connect() as db:
            db.execute(
                "INSERT INTO workspace_projects VALUES (:id,:name,:created_at)", item
            )
        return item

    def import_legacy(self):
        item = {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "Legacy Demo Project",
            "created_at": now(),
        }
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO workspace_projects VALUES (:id,:name,:created_at)",
                item,
            )
            row = db.execute(
                "SELECT * FROM workspace_projects WHERE id=?", (item["id"],)
            ).fetchone()
        return dict(row)

    def rename_project(self, project_id: UUID, name: str):
        with self._connect() as db:
            result = db.execute(
                "UPDATE workspace_projects SET name=? WHERE id=?",
                (name, str(project_id)),
            )
            if not result.rowcount:
                raise KeyError("Project not found")

    def chats(self, project_id: UUID):
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM workspace_chats WHERE project_id=? ORDER BY created_at DESC",
                    (str(project_id),),
                )
            ]

    def new_chat(self, project_id: UUID):
        item = {
            "id": str(uuid4()),
            "project_id": str(project_id),
            "title": "New chat",
            "created_at": now(),
        }
        with self._connect() as db:
            db.execute(
                "INSERT INTO workspace_chats VALUES (:id,:project_id,:title,:created_at)",
                item,
            )
        return item

    def chat(self, project_id: UUID, chat_id: UUID):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM workspace_chats WHERE id=? AND project_id=?",
                (str(chat_id), str(project_id)),
            ).fetchone()
            if row is None:
                raise KeyError("Chat does not belong to this project")
            return dict(row)

    def rename_chat(self, project_id: UUID, chat_id: UUID, title: str):
        self.chat(project_id, chat_id)
        with self._connect() as db:
            db.execute(
                "UPDATE workspace_chats SET title=? WHERE id=?", (title, str(chat_id))
            )

    def delete_chat(self, project_id: UUID, chat_id: UUID):
        self.chat(project_id, chat_id)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.chat(project_id, chat_id)
            if db.execute(
                "SELECT 1 FROM conversation_turns WHERE chat_id=? AND status='started'",
                (str(chat_id),),
            ).fetchone():
                raise ValueError("Chat has an active or interrupted request")
            db.execute(
                "DELETE FROM conversation_summaries WHERE chat_id=?", (str(chat_id),)
            )
            db.execute(
                "DELETE FROM conversation_turns WHERE chat_id=?", (str(chat_id),)
            )
            # Phase 11.13 uses the legacy project_id column as a chat scope.
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pending_remesh'"
            ).fetchone():
                db.execute(
                    "DELETE FROM pending_remesh WHERE project_id=?", (str(chat_id),)
                )
            db.execute(
                "DELETE FROM workspace_messages WHERE chat_id=?", (str(chat_id),)
            )
            db.execute("DELETE FROM workspace_chats WHERE id=?", (str(chat_id),))

    def messages(self, project_id: UUID, chat_id: UUID):
        self.chat(project_id, chat_id)
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id, role, content, created_at FROM workspace_messages "
                    "WHERE chat_id=? ORDER BY id",
                    (str(chat_id),),
                )
            ]

    def append(self, project_id: UUID, chat_id: UUID, role: str, content: str):
        self.chat(project_id, chat_id)
        if role not in ("user", "assistant"):
            raise ValueError("Invalid chat role")
        with self._connect() as db:
            db.execute(
                "INSERT INTO workspace_messages(chat_id,role,content,created_at) "
                "VALUES (?,?,?,?)",
                (str(chat_id), role, content, now()),
            )
            if role == "user":
                db.execute(
                    "UPDATE workspace_chats SET title=? WHERE id=? AND title='New chat'",
                    (content[:65], str(chat_id)),
                )

    def geometry_overrides(self, project_id: UUID):
        with self._connect() as db:
            return {
                row["job_id"]: dict(row)
                for row in db.execute(
                    "SELECT * FROM workspace_geometries WHERE project_id=?",
                    (str(project_id),),
                )
            }

    def update_geometry(
        self, project_id: UUID, job_id: UUID, *, name=None, deleted=None
    ):
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO workspace_geometries(project_id,job_id) VALUES (?,?)",
                (str(project_id), str(job_id)),
            )
            if name is not None:
                db.execute(
                    "UPDATE workspace_geometries SET display_name=? WHERE project_id=? AND job_id=?",
                    (name, str(project_id), str(job_id)),
                )
            if deleted is not None:
                db.execute(
                    "UPDATE workspace_geometries SET deleted=? WHERE project_id=? AND job_id=?",
                    (int(deleted), str(project_id), str(job_id)),
                )

    def summary(self, project_id, chat_id):
        self.chat(project_id, chat_id)
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM conversation_summaries WHERE chat_id=?", (str(chat_id),)
            ).fetchone()
            return dict(row) if row else None

    def save_summary(self, project_id, chat_id, watermark, content):
        self.chat(project_id, chat_id)
        with self._connect() as db:
            db.execute(
                "INSERT INTO conversation_summaries(chat_id,watermark,content) VALUES (?,?,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET watermark=excluded.watermark, "
                "content=excluded.content, version=version+1 "
                "WHERE excluded.watermark > watermark",
                (str(chat_id), watermark, content),
            )

    def begin_turn(self, project_id, chat_id, request_id, message):
        """Cross-process exclusion and idempotency, atomically with the user message.

        Interrupted process records remain started: fail closed rather than risk
        resubmitting a tool job after a crash. An operator must reconcile them.
        """
        self.chat(project_id, chat_id)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.chat(project_id, chat_id)
            prior = db.execute(
                "SELECT * FROM conversation_turns WHERE request_id=?",
                (str(request_id),),
            ).fetchone()
            if prior:
                if prior["chat_id"] != str(chat_id) or prior["message"] != message:
                    raise ValueError("Request ID was already used with different input")
                if prior["status"] != "completed":
                    raise ValueError(
                        "Request is active, failed or interrupted; inspect project jobs before a new request"
                    )
                return dict(prior)
            if db.execute(
                "SELECT 1 FROM conversation_turns WHERE chat_id=? AND status='started'",
                (str(chat_id),),
            ).fetchone():
                raise ValueError("Chat has an active or interrupted request")
            cursor = db.execute(
                "INSERT INTO workspace_messages(chat_id,role,content,created_at) "
                "VALUES (?,'user',?,?)",
                (str(chat_id), message, now()),
            )
            db.execute(
                "INSERT INTO conversation_turns(request_id,chat_id,message,status,started_at,user_message_id) "
                "VALUES (?,?,?,'started',?,?)",
                (str(request_id), str(chat_id), message, now(), cursor.lastrowid),
            )
            db.execute(
                "UPDATE workspace_chats SET title=? WHERE id=? AND title='New chat'",
                (message[:65], str(chat_id)),
            )
        return None

    def finish_turn(self, request_id, status, response, job_ids):
        import json

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM conversation_turns WHERE request_id=?",
                (str(request_id),),
            ).fetchone()
            if not row or row["status"] != "started":
                return
            assistant_id = None
            if status == "completed":
                cursor = db.execute(
                    "INSERT INTO workspace_messages(chat_id,role,content,created_at) "
                    "VALUES (?,'assistant',?,?)",
                    (row["chat_id"], response, now()),
                )
                assistant_id = cursor.lastrowid
            db.execute(
                "UPDATE conversation_turns SET status=?,finished_at=?,response=?,job_ids=?, "
                "assistant_message_id=? WHERE request_id=?",
                (
                    status,
                    now(),
                    response,
                    json.dumps(job_ids),
                    assistant_id,
                    str(request_id),
                ),
            )

    def context_messages(self, project_id, chat_id):
        """Only committed exchanges enter model history; failed user turns stay visible in UI."""
        self.chat(project_id, chat_id)
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,role,content FROM workspace_messages m WHERE chat_id=? AND NOT EXISTS "
                    "(SELECT 1 FROM conversation_turns t WHERE t.user_message_id=m.id AND t.status!=?) "
                    "ORDER BY id",
                    (str(chat_id), "completed"),
                )
            ]
