from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

current_thread_id: ContextVar[str] = ContextVar("current_thread_id", default="")

_PREF_KEYS = ("home_city", "cabin", "currency", "adults", "notes")
_LABELS = {
    "home_city": "Origem habitual",
    "cabin": "Classe",
    "currency": "Moeda",
    "adults": "Adultos",
    "notes": "Outras",
}


class Preferences:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_prefs (
                    thread_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, thread_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM user_prefs WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if not row:
            return {}
        try:
            data = json.loads(row[0])
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def update(self, thread_id: str, **fields: Any) -> dict[str, Any]:
        current = self.get(thread_id)
        for key, value in fields.items():
            if key not in _PREF_KEYS or value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            current[key] = value
        payload = json.dumps(current, ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_prefs (thread_id, data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (thread_id, payload, now),
            )
            conn.commit()
        return current

    def prompt_block(self, thread_id: str) -> str:
        prefs = self.get(thread_id)
        lines = [
            f"- {label}: {prefs[key]}"
            for key, label in _LABELS.items()
            if key in prefs and prefs[key] not in (None, "")
        ]
        if not lines:
            return "Nenhuma preferência salva ainda para este chat."
        return "\n".join(lines)


@dataclass
class AgentMemory:
    path: Path
    prefs: Preferences
    checkpointer: AsyncSqliteSaver | None = None
    _cm: Any = None

    @classmethod
    def create(cls, path: Path) -> AgentMemory:
        return cls(path=path, prefs=Preferences(path))

    async def start(self) -> AgentMemory:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cm = AsyncSqliteSaver.from_conn_string(str(self.path))
        self.checkpointer = await self._cm.__aenter__()
        await self.checkpointer.setup()
        return self

    async def close(self) -> None:
        if self._cm is None:
            return
        await self._cm.__aexit__(None, None, None)
        self._cm = None
        self.checkpointer = None


@asynccontextmanager
async def open_memory(path: Path) -> AsyncIterator[AgentMemory]:
    memory = AgentMemory.create(path)
    await memory.start()
    try:
        yield memory
    finally:
        await memory.close()
