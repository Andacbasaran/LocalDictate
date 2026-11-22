"""Local SQLite dictation history and productivity statistics."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import get_history_db_path


@dataclass
class HistoryEntry:
    id: int
    created_at: str
    raw_text: str
    final_text: str
    language: str
    model_size: str
    audio_duration_sec: float
    inference_sec: float
    word_count: int
    used_llm: bool


@dataclass
class UsageStats:
    total_dictations: int
    total_words: int
    total_audio_sec: float
    avg_inference_sec: float
    estimated_minutes_saved: float


class HistoryStore:
    """Thread-safe local SQLite storage for dictation history."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_history_db_path()
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dictations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    final_text TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT '',
                    model_size TEXT NOT NULL DEFAULT '',
                    audio_duration_sec REAL NOT NULL DEFAULT 0.0,
                    inference_sec REAL NOT NULL DEFAULT 0.0,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    used_llm INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def add(
        self,
        raw_text: str,
        final_text: str,
        language: str = "",
        model_size: str = "",
        audio_duration_sec: float = 0.0,
        inference_sec: float = 0.0,
        used_llm: bool = False,
    ) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        word_count = len(final_text.split())
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO dictations (
                    created_at, raw_text, final_text, language, model_size,
                    audio_duration_sec, inference_sec, word_count, used_llm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    raw_text,
                    final_text,
                    language,
                    model_size,
                    float(audio_duration_sec),
                    float(inference_sec),
                    word_count,
                    1 if used_llm else 0,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_recent(self, limit: int = 100, query: str = "") -> list[HistoryEntry]:
        q = query.strip()
        with self._lock, self._connect() as conn:
            if q:
                like = f"%{q}%"
                rows = conn.execute(
                    """
                    SELECT * FROM dictations
                    WHERE final_text LIKE ? OR raw_text LIKE ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (like, like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM dictations ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        return [
            HistoryEntry(
                id=r["id"],
                created_at=r["created_at"],
                raw_text=r["raw_text"],
                final_text=r["final_text"],
                language=r["language"],
                model_size=r["model_size"],
                audio_duration_sec=r["audio_duration_sec"],
                inference_sec=r["inference_sec"],
                word_count=r["word_count"],
                used_llm=bool(r["used_llm"]),
            )
            for r in rows
        ]

    def delete(self, entry_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM dictations WHERE id = ?", (entry_id,))
            conn.commit()

    def clear(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM dictations")
            conn.commit()

    def get_stats(self) -> UsageStats:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS cnt,
                    COALESCE(SUM(word_count), 0) AS words,
                    COALESCE(SUM(audio_duration_sec), 0.0) AS audio_sec,
                    COALESCE(AVG(inference_sec), 0.0) AS avg_inf
                FROM dictations
                """
            ).fetchone()

        total_words = int(row["words"])
        total_audio_sec = float(row["audio_sec"])
        # Estimate typing time at 40 WPM minus actual dictation speaking time
        typing_minutes = total_words / 40.0
        speaking_minutes = total_audio_sec / 60.0
        saved_minutes = max(0.0, typing_minutes - speaking_minutes)

        return UsageStats(
            total_dictations=int(row["cnt"]),
            total_words=total_words,
            total_audio_sec=total_audio_sec,
            avg_inference_sec=float(row["avg_inf"]),
            estimated_minutes_saved=saved_minutes,
        )
