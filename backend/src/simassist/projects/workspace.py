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
                CREATE TABLE IF NOT EXISTS chat_message_attachments (
                    message_id INTEGER NOT NULL, file_id TEXT NOT NULL, attachment_order INTEGER NOT NULL,
                    PRIMARY KEY(message_id, file_id)
                );
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

    def open_default_project(self):
        """Reuse an untouched default project, including auto-created empty chats.

        Claim/create in one write transaction so simultaneous page loads do not
        create duplicate defaults. Existing projects and engineering data stay intact.
        Optional engineering tables may not exist in a new workspace database yet.
        """
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            candidates = db.execute(
                "SELECT * FROM workspace_projects WHERE name='Untitled Project' COLLATE NOCASE "
                "ORDER BY created_at DESC, id DESC"
            ).fetchall()
            for project in candidates:
                project_id = project["id"]
                has_messages = db.execute(
                    "SELECT 1 FROM workspace_messages m JOIN workspace_chats c ON c.id=m.chat_id "
                    "WHERE c.project_id=? LIMIT 1",
                    (project_id,),
                ).fetchone()
                if has_messages:
                    continue
                # Identifiers below are fixed internal schema names, never user input.
                content_tables = [
                    ("jobs", "project_id"),
                    ("workspace_geometries", "project_id"),
                    ("project_files", "project_id"),
                ]
                if any(
                    table in tables
                    and db.execute(
                        f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (project_id,)
                    ).fetchone()
                    for table, column in content_tables
                ):
                    continue
                if (
                    "project_context" in tables
                    and db.execute(
                        "SELECT 1 FROM project_context WHERE project_id=? AND "
                        "(active_geometry_job_id IS NOT NULL OR active_geometry_artifact_id IS NOT NULL)",
                        (project_id,),
                    ).fetchone()
                ):
                    continue
                return dict(project)
            item = {"id": str(uuid4()), "name": "Untitled Project", "created_at": now()}
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
            if not db.execute(
                "SELECT 1 FROM workspace_projects WHERE id=?", (str(project_id),)
            ).fetchone():
                raise KeyError("Project not found")
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
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM workspace_projects WHERE id=?", (str(project_id),)
            ).fetchone():
                raise KeyError("Project not found")
            db.execute(
                "INSERT INTO workspace_chats VALUES (:id,:project_id,:title,:created_at)",
                item,
            )
        return item

    def delete_project(self, project_id: UUID):
        """Delete workspace ownership and dialogue atomically, retaining jobs/files.

        The same write lock as begin_turn/new_chat prevents deletion racing with
        accepted requests or leaving a newly created orphan chat behind.
        """
        project_key = str(project_id)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM workspace_projects WHERE id=?", (project_key,)
            ).fetchone():
                raise KeyError("Project not found")
            if db.execute(
                "SELECT 1 FROM conversation_turns t JOIN workspace_chats c ON c.id=t.chat_id "
                "WHERE c.project_id=? AND t.status='started' LIMIT 1",
                (project_key,),
            ).fetchone():
                raise ValueError(
                    "Project has an active or interrupted chat request. Finish or reconcile it before deleting the project."
                )
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "pending_remesh" in tables:
                db.execute(
                    "DELETE FROM pending_remesh WHERE project_id=? OR project_id IN "
                    "(SELECT id FROM workspace_chats WHERE project_id=?)",
                    (project_key, project_key),
                )
            db.execute(
                "DELETE FROM chat_message_attachments WHERE message_id IN "
                "(SELECT m.id FROM workspace_messages m JOIN workspace_chats c ON c.id=m.chat_id WHERE c.project_id=?)",
                (project_key,),
            )
            for table in (
                "conversation_summaries",
                "conversation_turns",
                "workspace_messages",
            ):
                db.execute(
                    f"DELETE FROM {table} WHERE chat_id IN "
                    "(SELECT id FROM workspace_chats WHERE project_id=?)",
                    (project_key,),
                )
            db.execute("DELETE FROM workspace_chats WHERE project_id=?", (project_key,))
            db.execute(
                "DELETE FROM workspace_geometries WHERE project_id=?", (project_key,)
            )
            if "project_context" in tables:
                db.execute(
                    "DELETE FROM project_context WHERE project_id=?", (project_key,)
                )
            db.execute("DELETE FROM workspace_projects WHERE id=?", (project_key,))

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
                "DELETE FROM chat_message_attachments WHERE message_id IN "
                "(SELECT id FROM workspace_messages WHERE chat_id=?)",
                (str(chat_id),),
            )
            db.execute(
                "DELETE FROM workspace_messages WHERE chat_id=?", (str(chat_id),)
            )
            db.execute("DELETE FROM workspace_chats WHERE id=?", (str(chat_id),))

    def attachment_metadata(self, message_id):
        with self._connect() as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='project_files'"
            ).fetchone()
            if not exists:
                return []
            return [
                dict(row)
                for row in db.execute(
                    "SELECT f.file_id,f.filename,f.format,f.size_bytes FROM chat_message_attachments a "
                    "JOIN project_files f ON f.file_id=a.file_id WHERE a.message_id=? ORDER BY attachment_order",
                    (message_id,),
                )
            ]

    def messages(self, project_id: UUID, chat_id: UUID):
        self.chat(project_id, chat_id)
        with self._connect() as db:
            items = [
                dict(row)
                for row in db.execute(
                    "SELECT id, role, content, created_at FROM workspace_messages "
                    "WHERE chat_id=? ORDER BY id",
                    (str(chat_id),),
                )
            ]

        for item in items:
            item["attachments"] = self.attachment_metadata(item["id"])
        return items

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

    def begin_turn(self, project_id, chat_id, request_id, message, attachment_ids=()):
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
                prior_files = [
                    row[0]
                    for row in db.execute(
                        "SELECT file_id FROM chat_message_attachments WHERE message_id=? ORDER BY attachment_order",
                        (prior["user_message_id"],),
                    )
                ]
                if prior_files != [str(file_id) for file_id in attachment_ids]:
                    raise ValueError(
                        "Request ID was already used with different attachments"
                    )
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
            for file_id in attachment_ids:
                if not db.execute(
                    "SELECT 1 FROM project_files WHERE file_id=? AND project_id=? AND status='uploaded'",
                    (str(file_id), str(project_id)),
                ).fetchone():
                    raise KeyError("Uploaded file not found in this project")
            cursor = db.execute(
                "INSERT INTO workspace_messages(chat_id,role,content,created_at) "
                "VALUES (?,'user',?,?)",
                (str(chat_id), message, now()),
            )
            for order, file_id in enumerate(attachment_ids):
                db.execute(
                    "INSERT INTO chat_message_attachments VALUES (?,?,?)",
                    (cursor.lastrowid, str(file_id), order),
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

    def latest_context_user(self, project_id, chat_id):
        """Bounded routing hint, excluding current, failed and interrupted turns."""
        messages = self.recent_context_users(project_id, chat_id, limit=1)
        return messages[0] if messages else None

    def recent_context_users(self, project_id, chat_id, *, limit=4):
        """Bounded chat-local intent chain; never include unfinished turns."""
        if not 1 <= limit <= 4:
            raise ValueError("Routing history limit must be between 1 and 4")
        self.chat(project_id, chat_id)
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,content FROM workspace_messages m WHERE chat_id=? AND role='user' "
                "AND NOT EXISTS (SELECT 1 FROM conversation_turns t "
                "WHERE t.user_message_id=m.id AND t.status!='completed') ORDER BY id DESC LIMIT ?",
                (str(chat_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def context_messages(self, project_id, chat_id):
        """Only committed exchanges enter model history; failed user turns stay visible in UI."""
        self.chat(project_id, chat_id)
        with self._connect() as db:
            items = [
                dict(row)
                for row in db.execute(
                    "SELECT id,role,content FROM workspace_messages m WHERE chat_id=? AND NOT EXISTS "
                    "(SELECT 1 FROM conversation_turns t WHERE t.user_message_id=m.id AND t.status!=?) "
                    "ORDER BY id",
                    (str(chat_id), "completed"),
                )
            ]
        import json

        for item in items:
            attachments = self.attachment_metadata(item["id"])
            if attachments:
                item["content"] += (
                    "\nUntrusted attachment display metadata; inspect files using tools: "
                    + json.dumps(attachments)
                )
        return items
