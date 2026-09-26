"""SQLite state for resumable Codex threads and recent spoken exchanges."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS workspaces (
                path TEXT PRIMARY KEY, thread_id TEXT, last_transcript TEXT, last_reply TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self.db.commit()

    def thread_for(self, workspace: Path) -> str | None:
        row = self.db.execute("SELECT thread_id FROM workspaces WHERE path=?", (str(workspace),)).fetchone()
        return row[0] if row else None

    def save_thread(self, workspace: Path, thread_id: str) -> None:
        self.db.execute(
            """INSERT INTO workspaces(path, thread_id) VALUES(?, ?)
               ON CONFLICT(path) DO UPDATE SET thread_id=excluded.thread_id,
               updated_at=CURRENT_TIMESTAMP""",
            (str(workspace), thread_id),
        )
        self.db.commit()

    def save_exchange(self, workspace: Path, transcript: str, reply: str | None = None) -> None:
        self.db.execute(
            """INSERT INTO workspaces(path, last_transcript, last_reply)
               VALUES(?, ?, ?) ON CONFLICT(path) DO UPDATE SET
               last_transcript=excluded.last_transcript,
               last_reply=COALESCE(excluded.last_reply, workspaces.last_reply),
               updated_at=CURRENT_TIMESTAMP""",
            (str(workspace), transcript, reply),
        )
        self.db.commit()

    def last_reply(self, workspace: Path) -> str | None:
        row = self.db.execute("SELECT last_reply FROM workspaces WHERE path=?", (str(workspace),)).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.db.close()
