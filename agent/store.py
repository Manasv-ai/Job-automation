"""Small SQLite state store for the agent layer (separate from jobs_database.db).

Notion is the source of truth for *status*; this store holds what Notion can't:
the job_id <-> page_id mapping, claim timestamps (crash recovery), seen emails.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS job_sync (
                    job_id TEXT PRIMARY KEY,
                    page_id TEXT,
                    status TEXT,
                    claimed_from TEXT,
                    updated_at REAL,
                    resume_path TEXT,
                    rounds INTEGER DEFAULT 0,
                    last_error TEXT,
                    dedupe_key TEXT
                );
                CREATE TABLE IF NOT EXISTS emails_seen (
                    message_id TEXT PRIMARY KEY,
                    processed_at REAL,
                    category TEXT,
                    job_id TEXT
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT, started REAL, finished REAL, ok INTEGER, detail TEXT
                );
                CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
                """
            )
            try:  # migration for DBs created before dedupe_key existed
                c.execute("ALTER TABLE job_sync ADD COLUMN dedupe_key TEXT")
            except sqlite3.OperationalError:
                pass

    # ---- job sync -------------------------------------------------------
    def upsert_job(self, job_id: str, page_id: str, status: str, dedupe_key: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO job_sync (job_id, page_id, status, updated_at, dedupe_key)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET page_id=excluded.page_id,
                   status=excluded.status, updated_at=excluded.updated_at,
                   dedupe_key=COALESCE(excluded.dedupe_key, job_sync.dedupe_key)""",
                (job_id, page_id, status, time.time(), dedupe_key),
            )

    def known_dedupe_keys(self) -> set[str]:
        with self._conn() as c:
            return {r["dedupe_key"] for r in c.execute("SELECT dedupe_key FROM job_sync WHERE dedupe_key IS NOT NULL")}

    def known_job_ids(self) -> set[str]:
        with self._conn() as c:
            return {r["job_id"] for r in c.execute("SELECT job_id FROM job_sync")}

    def get_job(self, job_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM job_sync WHERE job_id=?", (job_id,)).fetchone()
            return dict(r) if r else None

    def jobs_in_statuses(self, statuses: list[str]) -> list[dict]:
        q = ",".join("?" * len(statuses))
        with self._conn() as c:
            return [dict(r) for r in c.execute(f"SELECT * FROM job_sync WHERE status IN ({q})", statuses)]

    def claim(self, job_id: str, new_status: str, claimed_from: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE job_sync SET status=?, claimed_from=?, updated_at=? WHERE job_id=?",
                (new_status, claimed_from, time.time(), job_id),
            )

    def set_status(self, job_id: str, status: str, **fields) -> None:
        allowed = {"resume_path", "rounds", "last_error"}
        sets = ["status=?", "updated_at=?"]
        vals: list = [status, time.time()]
        for k, v in fields.items():
            if k in allowed:
                sets.append(f"{k}=?")
                vals.append(v)
        vals.append(job_id)
        with self._conn() as c:
            c.execute(f"UPDATE job_sync SET {', '.join(sets)} WHERE job_id=?", vals)

    def stuck_claims(self, claim_statuses: list[str], older_than_s: float) -> list[dict]:
        q = ",".join("?" * len(claim_statuses))
        cutoff = time.time() - older_than_s
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM job_sync WHERE status IN ({q}) AND updated_at < ?",
                [*claim_statuses, cutoff],
            )
            return [dict(r) for r in rows]

    # ---- emails ---------------------------------------------------------
    def email_seen(self, message_id: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM emails_seen WHERE message_id=?", (message_id,)).fetchone() is not None

    def mark_email(self, message_id: str, category: str, job_id: str | None) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO emails_seen VALUES (?,?,?,?)",
                (message_id, time.time(), category, job_id),
            )

    # ---- kv / runs ------------------------------------------------------
    def kv_get(self, k: str, default: str | None = None) -> str | None:
        with self._conn() as c:
            r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
            return r["v"] if r else default

    def kv_set(self, k: str, v: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, v))

    def log_run(self, kind: str, started: float, ok: bool, detail: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO runs (kind, started, finished, ok, detail) VALUES (?,?,?,?,?)",
                (kind, started, time.time(), 1 if ok else 0, detail[:2000]),
            )

    def last_run(self, kind: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM runs WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,)).fetchone()
            return dict(r) if r else None
