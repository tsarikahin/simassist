"""Persistent projects, conversations, and non-destructive geometry management."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel


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
            """)

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def projects(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM workspace_projects ORDER BY created_at DESC')]

    def new_project(self, name='Untitled Project'):
        item = dict(id=str(uuid4()), name=name, created_at=now())
        with self._connect() as db:
            db.execute('INSERT INTO workspace_projects VALUES (:id,:name,:created_at)', item)
        return item

    def import_legacy(self):
        item = dict(id="11111111-1111-4111-8111-111111111111",
                    name="Legacy Demo Project", created_at=now())
        with self._connect() as db:
            db.execute('INSERT OR IGNORE INTO workspace_projects VALUES (:id,:name,:created_at)', item)
            row = db.execute('SELECT * FROM workspace_projects WHERE id=?',
                             (item['id'],)).fetchone()
        return dict(row)

    def rename_project(self, project_id: UUID, name: str):
        with self._connect() as db:
            result = db.execute('UPDATE workspace_projects SET name=? WHERE id=?',
                                (name, str(project_id)))
            if not result.rowcount:
                raise KeyError('Project not found')

    def chats(self, project_id: UUID):
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM workspace_chats WHERE project_id=? ORDER BY created_at DESC',
                (str(project_id),))]

    def new_chat(self, project_id: UUID):
        item = dict(id=str(uuid4()), project_id=str(project_id),
                    title='New chat', created_at=now())
        with self._connect() as db:
            db.execute('INSERT INTO workspace_chats VALUES (:id,:project_id,:title,:created_at)', item)
        return item

    def chat(self, project_id: UUID, chat_id: UUID):
        with self._connect() as db:
            row = db.execute('SELECT * FROM workspace_chats WHERE id=? AND project_id=?',
                             (str(chat_id), str(project_id))).fetchone()
            if row is None:
                raise KeyError('Chat does not belong to this project')
            return dict(row)

    def rename_chat(self, project_id: UUID, chat_id: UUID, title: str):
        self.chat(project_id, chat_id)
        with self._connect() as db:
            db.execute('UPDATE workspace_chats SET title=? WHERE id=?',
                       (title, str(chat_id)))

    def delete_chat(self, project_id: UUID, chat_id: UUID):
        self.chat(project_id, chat_id)
        with self._connect() as db:
            db.execute('DELETE FROM workspace_messages WHERE chat_id=?', (str(chat_id),))
            db.execute('DELETE FROM workspace_chats WHERE id=?', (str(chat_id),))

    def messages(self, project_id: UUID, chat_id: UUID):
        self.chat(project_id, chat_id)
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT id, role, content, created_at FROM workspace_messages '
                'WHERE chat_id=? ORDER BY id', (str(chat_id),))]

    def append(self, project_id: UUID, chat_id: UUID, role: str, content: str):
        self.chat(project_id, chat_id)
        if role not in ('user', 'assistant'):
            raise ValueError('Invalid chat role')
        with self._connect() as db:
            db.execute('INSERT INTO workspace_messages(chat_id,role,content,created_at) '
                       'VALUES (?,?,?,?)', (str(chat_id), role, content, now()))
            if role == 'user':
                db.execute("UPDATE workspace_chats SET title=? WHERE id=? AND title='New chat'",
                           (content[:65], str(chat_id)))

    def geometry_overrides(self, project_id: UUID):
        with self._connect() as db:
            return {row['job_id']: dict(row) for row in db.execute(
                'SELECT * FROM workspace_geometries WHERE project_id=?', (str(project_id),))}

    def update_geometry(self, project_id: UUID, job_id: UUID, *, name=None, deleted=None):
        with self._connect() as db:
            db.execute('INSERT OR IGNORE INTO workspace_geometries(project_id,job_id) VALUES (?,?)',
                       (str(project_id), str(job_id)))
            if name is not None:
                db.execute('UPDATE workspace_geometries SET display_name=? WHERE project_id=? AND job_id=?',
                           (name, str(project_id), str(job_id)))
            if deleted is not None:
                db.execute('UPDATE workspace_geometries SET deleted=? WHERE project_id=? AND job_id=?',
                           (int(deleted), str(project_id), str(job_id)))
