"""Local SQLite dictation history with Turkish-aware search, pinning, auto-migration, and export."""

from __future__ import annotations

import csv
import json
import sqlite3
import threading
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import get_history_db_path

# Turkish-specific folding map so 'İ'/'ı'/'ş'/'ğ'/'ü'/'ö'/'ç' match ASCII search terms
_TR_FOLD_MAP = str.maketrans(
    {
        "İ": "i",
        "I": "i",
        "ı": "i",
        "Ş": "s",
        "ş": "s",
        "Ğ": "g",
        "ğ": "g",
        "Ü": "u",
        "ü": "u",
        "Ö": "o",
        "ö": "o",
        "Ç": "c",
        "ç": "c",
    }
)


def normalize_search_text(text: str) -> str:
    """Fold Turkish diacritics and Unicode accents to lowercase ASCII for fast LIKE matching."""
    if not text:
        return ""
    translated = text.translate(_TR_FOLD_MAP).lower()
    decomposed = unicodedata.normalize("NFKD", translated)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


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
    target_app: str = ""
    mode: str = "cleanup"
    pinned: bool = False

    @property
    def wpm(self) -> int:
        if self.audio_duration_sec <= 0.05:
            return 0
        return int(round((self.word_count / self.audio_duration_sec) * 60.0))


@dataclass
class UsageStats:
    total_dictations: int
    total_words: int
    total_audio_sec: float
    avg_inference_sec: float
    estimated_minutes_saved: float


class HistoryStore:
    """Thread-safe local SQLite storage with persistent WAL connection and auto-migration."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_history_db_path()
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn = conn
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
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
                    used_llm INTEGER NOT NULL DEFAULT 0,
                    target_app TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'cleanup',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    search_norm TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # Seamless auto-migration for databases created by LocalDictate v0.1/v0.2
            existing_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(dictations)").fetchall()
            }
            migrations = [
                ("target_app", "TEXT NOT NULL DEFAULT ''"),
                ("mode", "TEXT NOT NULL DEFAULT 'cleanup'"),
                ("pinned", "INTEGER NOT NULL DEFAULT 0"),
                ("search_norm", "TEXT NOT NULL DEFAULT ''"),
            ]
            migrated_search = False
            for col_name, col_def in migrations:
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE dictations ADD COLUMN {col_name} {col_def}")
                    if col_name == "search_norm":
                        migrated_search = True

            if migrated_search:
                rows = conn.execute(
                    "SELECT id, raw_text, final_text, target_app FROM dictations"
                ).fetchall()
                for r in rows:
                    norm = normalize_search_text(
                        f"{r['final_text']} {r['raw_text']} {r['target_app']}"
                    )
                    conn.execute(
                        "UPDATE dictations SET search_norm = ? WHERE id = ?",
                        (norm, r["id"]),
                    )

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dictations_pinned_id ON dictations(pinned DESC, id DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dictations_mode ON dictations(mode)"
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
        target_app: str = "",
        mode: str = "cleanup",
        pinned: bool = False,
        created_at: Optional[str] = None,
    ) -> int:
        now = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        word_count = len(final_text.split())
        search_norm = normalize_search_text(f"{final_text} {raw_text} {target_app} {mode}")
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute(
                """
                INSERT INTO dictations (
                    created_at, raw_text, final_text, language, model_size,
                    audio_duration_sec, inference_sec, word_count, used_llm,
                    target_app, mode, pinned, search_norm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    target_app or "",
                    mode or "cleanup",
                    1 if pinned else 0,
                    search_norm,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def _row_to_entry(self, r: sqlite3.Row) -> HistoryEntry:
        return HistoryEntry(
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
            target_app=r["target_app"],
            mode=r["mode"],
            pinned=bool(r["pinned"]),
        )

    def list_recent(
        self,
        limit: int = 100,
        query: str = "",
        mode_filter: str = "",
        pinned_only: bool = False,
    ) -> list[HistoryEntry]:
        q_norm = normalize_search_text(query.strip())
        clauses: list[str] = []
        params: list[object] = []

        if q_norm:
            like = f"%{q_norm}%"
            clauses.append("(search_norm LIKE ? OR final_text LIKE ? OR raw_text LIKE ?)")
            params.extend([like, f"%{query.strip()}%", f"%{query.strip()}%"])
        if mode_filter and mode_filter != "all":
            clauses.append("mode = ?")
            params.append(mode_filter)
        if pinned_only:
            clauses.append("pinned = 1")

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM dictations {where_sql} ORDER BY pinned DESC, id DESC LIMIT ?"
        params.append(int(limit))

        with self._lock:
            rows = self._get_conn().execute(sql, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def toggle_pin(self, entry_id: int) -> bool:
        """Toggle pinned flag for an entry and return the new pinned state."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT pinned FROM dictations WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                return False
            new_val = 0 if int(row["pinned"]) else 1
            conn.execute(
                "UPDATE dictations SET pinned = ? WHERE id = ?", (new_val, entry_id)
            )
            conn.commit()
            return bool(new_val)

    def delete(self, entry_id: int) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM dictations WHERE id = ?", (entry_id,))
            conn.commit()

    def clear(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM dictations")
            conn.commit()

    def get_stats(self) -> UsageStats:
        with self._lock:
            row = self._get_conn().execute(
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

    def export_entries(
        self,
        dest_path: Path | str,
        fmt: str = "md",
        entries: Optional[list[HistoryEntry]] = None,
    ) -> Path:
        """Export dictation history to Markdown (.md), CSV (.csv), plain text (.txt), or JSON (.json)."""
        out_path = Path(dest_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        items = entries if entries is not None else self.list_recent(limit=10_000)
        kind = fmt.strip().lower().lstrip(".")

        if kind == "json":
            out_path.write_text(
                json.dumps([asdict(e) for e in items], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        elif kind == "csv":
            with out_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "id",
                        "created_at",
                        "target_app",
                        "mode",
                        "language",
                        "model_size",
                        "audio_duration_sec",
                        "inference_sec",
                        "word_count",
                        "used_llm",
                        "pinned",
                        "final_text",
                        "raw_text",
                    ]
                )
                for e in items:
                    writer.writerow(
                        [
                            e.id,
                            e.created_at,
                            e.target_app,
                            e.mode,
                            e.language,
                            e.model_size,
                            f"{e.audio_duration_sec:.2f}",
                            f"{e.inference_sec:.3f}",
                            e.word_count,
                            int(e.used_llm),
                            int(e.pinned),
                            e.final_text,
                            e.raw_text,
                        ]
                    )
        elif kind == "txt":
            blocks = []
            for e in items:
                header = f"[{e.created_at}] ({e.mode} | {e.language or 'auto'} | {e.target_app or 'Desktop'})"
                blocks.append(f"{header}\n{e.final_text}")
            out_path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")
        else:
            # Markdown (.md)
            lines = ["# LocalDictate History Export", ""]
            for e in items:
                pin = "Pinned · " if e.pinned else ""
                app_tag = f" · `{e.target_app}`" if e.target_app else ""
                lines.append(
                    f"### {pin}{e.created_at} — `{e.mode}`{app_tag} ({e.inference_sec:.2f}s)"
                )
                lines.append("")
                lines.append(e.final_text)
                if e.raw_text.strip() != e.final_text.strip():
                    lines.append("")
                    lines.append(f"> Raw: {e.raw_text}")
                lines.append("")
            out_path.write_text("\n".join(lines), encoding="utf-8")

        return out_path
