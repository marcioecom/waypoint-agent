from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

current_thread_id: ContextVar[str] = ContextVar("current_thread_id", default="")

# Sync stores (prefs/trips) must not share a file with AsyncSqliteSaver.
# On Railway/volume FS, concurrent writers on the same sqlite file lock easily.
_CONNECT_TIMEOUT_S = 30.0
_BUSY_TIMEOUT_MS = 30_000

_PREF_KEYS = ("home_city", "cabin", "currency", "adults", "notes")
_LABELS = {
    "home_city": "Origem habitual",
    "cabin": "Classe",
    "currency": "Moeda",
    "adults": "Adultos",
    "notes": "Outras",
}

_TRIP_KEYS = (
    "origin",
    "destination",
    "trip_type",
    "date_from",
    "date_to",
    "return_from",
    "return_to",
    "cabin",
    "adults",
    "currency",
    "status",
    "notes",
)
_TRIP_LABELS = {
    "origin": "Origem",
    "destination": "Destino",
    "trip_type": "Tipo",
    "date_from": "Ida de",
    "date_to": "Ida até",
    "return_from": "Volta de",
    "return_to": "Volta até",
    "cabin": "Classe",
    "adults": "Adultos",
    "currency": "Moeda",
    "status": "Status",
    "notes": "Notas",
}


def state_db_path(checkpoint_path: Path) -> Path:
    """Prefs/trips live beside the checkpointer DB, never in the same file."""
    return checkpoint_path.with_name(f"{checkpoint_path.stem}-state.sqlite")


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=_CONNECT_TIMEOUT_S, check_same_thread=False)
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class Preferences:
    def __init__(self, path: Path, lock: threading.Lock | None = None):
        self.path = path
        self._lock = lock or threading.Lock()
        with self._locked_conn() as conn:
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

    @contextmanager
    def _locked_conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = _connect(self.path)
            try:
                yield conn
            finally:
                conn.close()

    def get(self, thread_id: str) -> dict[str, Any]:
        with self._locked_conn() as conn:
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
        with self._locked_conn() as conn:
            row = conn.execute(
                "SELECT data FROM user_prefs WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            current: dict[str, Any] = {}
            if row:
                try:
                    loaded = json.loads(row[0])
                    if isinstance(loaded, dict):
                        current = loaded
                except json.JSONDecodeError:
                    current = {}
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


class TripBrief:
    """Pedido ativo da conversa — sobrevive a trim/histórico longo."""

    def __init__(self, path: Path, lock: threading.Lock | None = None):
        self.path = path
        self._lock = lock or threading.Lock()
        with self._locked_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trip_briefs (
                    thread_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @contextmanager
    def _locked_conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = _connect(self.path)
            try:
                yield conn
            finally:
                conn.close()

    def get(self, thread_id: str) -> dict[str, Any]:
        with self._locked_conn() as conn:
            row = conn.execute(
                "SELECT data FROM trip_briefs WHERE thread_id = ?",
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
        with self._locked_conn() as conn:
            row = conn.execute(
                "SELECT data FROM trip_briefs WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            current: dict[str, Any] = {}
            if row:
                try:
                    loaded = json.loads(row[0])
                    if isinstance(loaded, dict):
                        current = loaded
                except json.JSONDecodeError:
                    current = {}
            for key, value in fields.items():
                if key not in _TRIP_KEYS or value is None:
                    continue
                if isinstance(value, str):
                    value = value.strip()
                    if not value:
                        continue
                current[key] = value
            if "status" not in current:
                current["status"] = "collecting"
            payload = json.dumps(current, ensure_ascii=False)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO trip_briefs (thread_id, data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (thread_id, payload, now),
            )
            conn.commit()
        return current

    def clear(self, thread_id: str) -> None:
        with self._locked_conn() as conn:
            conn.execute("DELETE FROM trip_briefs WHERE thread_id = ?", (thread_id,))
            conn.commit()

    def prompt_block(self, thread_id: str) -> str:
        brief = self.get(thread_id)
        lines = [
            f"- {label}: {brief[key]}"
            for key, label in _TRIP_LABELS.items()
            if key in brief and brief[key] not in (None, "")
        ]
        if not lines:
            return "Nenhum pedido ativo ainda."
        return "\n".join(lines)


@dataclass
class AgentMemory:
    path: Path
    state_path: Path
    prefs: Preferences
    trips: TripBrief
    checkpointer: AsyncSqliteSaver | None = None
    _cm: Any = None

    @classmethod
    def create(cls, path: Path) -> AgentMemory:
        state_path = state_db_path(path)
        lock = threading.Lock()
        return cls(
            path=path,
            state_path=state_path,
            prefs=Preferences(state_path, lock=lock),
            trips=TripBrief(state_path, lock=lock),
        )

    async def start(self) -> AgentMemory:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
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
