import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Session:
    id: str
    name: str
    command: str
    created: str
    last_active: str
    raw_offset: int


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.logs_dir = self.data_dir / "logs"
        self.raw_dir = self.data_dir / "raw"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        self.raw_dir.mkdir(exist_ok=True)
        self.db_path = self.data_dir / "sessions.db"
        self._next_seq: Dict[str, int] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    command TEXT NOT NULL,
                    created TEXT NOT NULL,
                    last_active TEXT NOT NULL,
                    raw_offset INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def create_session(self, session_id: str, name: str, command: str) -> Session:
        now = utc_timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, name, command, now, now, 0),
            )
        self._next_seq[session_id] = 1
        return Session(session_id, name, command, now, now, 0)

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return Session(**dict(row)) if row else None

    def list_sessions(self) -> List[Session]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY created"
            ).fetchall()
        return [Session(**dict(row)) for row in rows]

    def touch(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET last_active = ? WHERE id = ?",
                (utc_timestamp(), session_id),
            )

    def set_raw_offset(self, session_id: str, offset: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET raw_offset = ?, last_active = ? WHERE id = ?",
                (offset, utc_timestamp(), session_id),
            )

    def delete_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._next_seq.pop(session_id, None)

    def raw_path(self, session_id: str) -> Path:
        return self.raw_dir / (session_id + ".stream")

    def log_path(self, session_id: str) -> Path:
        return self.logs_dir / (session_id + ".jsonl")

    def _calculate_next_seq(self, session_id: str) -> int:
        events = self.replay_after(session_id, 0)
        return events[-1]["seq"] + 1 if events else 1

    def append_output(self, session_id: str, data: str) -> dict:
        if session_id not in self._next_seq:
            self._next_seq[session_id] = self._calculate_next_seq(session_id)
        event = {
            "seq": self._next_seq[session_id],
            "type": "output",
            "data": data,
            "ts": utc_timestamp(),
        }
        with self.log_path(session_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
        self._next_seq[session_id] += 1
        return event

    def replay_after(self, session_id: str, after_seq: int) -> List[dict]:
        path = self.log_path(session_id)
        if not path.exists():
            return []
        events = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                event = json.loads(line)
                if event["seq"] > after_seq:
                    events.append(event)
        return events

