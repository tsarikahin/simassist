from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


class RemeshProposalStore:
    """Persist one unconfirmed remesh proposal per project across chat requests."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS pending_remesh (
                    project_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30)

    def save(self, project_id: UUID, proposal: dict[str, Any]) -> dict[str, Any]:
        record = {**proposal, "proposal_id": str(uuid4())}
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO pending_remesh (project_id, proposal_id, payload, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    proposal_id = excluded.proposal_id,
                    payload = excluded.payload,
                    created_at = excluded.created_at""",
                (
                    str(project_id),
                    record["proposal_id"],
                    json.dumps(record),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return record

    def get(self, project_id: UUID) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM pending_remesh WHERE project_id = ?",
                (str(project_id),),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def clear(self, project_id: UUID, proposal_id: str | None = None) -> None:
        with self._connect() as connection:
            if proposal_id is None:
                connection.execute(
                    "DELETE FROM pending_remesh WHERE project_id = ?",
                    (str(project_id),),
                )
            else:
                connection.execute(
                    "DELETE FROM pending_remesh WHERE project_id = ? AND proposal_id = ?",
                    (str(project_id), proposal_id),
                )
