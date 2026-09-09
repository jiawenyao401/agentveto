"""SQLite storage.

Why SQLite and not ClickHouse/Postgres: this is a local recorder that has to
work on a laptop, in a CI job, and inside a customer's VPC with zero setup.
A single file with WAL mode handles thousands of spans per second, which is
far beyond what one agent process generates. Migrating to a columnar store is
a year-two problem, and the schema below is shaped so that migration is a
straight copy.

Threading: one connection per thread (``check_same_thread=False`` plus a
thread-local connection), writes serialised by a lock. SQLite is fine with
concurrent readers; concurrent writers are the thing to avoid.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    started_at    REAL NOT NULL,
    ended_at      REAL,
    status        TEXT NOT NULL DEFAULT 'running',
    total_cost    REAL NOT NULL DEFAULT 0,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    span_count    INTEGER NOT NULL DEFAULT 0,
    meta          TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);

CREATE TABLE IF NOT EXISTS spans (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    parent_id    TEXT,
    seq          INTEGER NOT NULL,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'span',
    started_at   REAL NOT NULL,
    ended_at     REAL,
    duration_ms  REAL,
    status       TEXT NOT NULL DEFAULT 'running',
    model        TEXT,
    input        TEXT,
    output       TEXT,
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    cost         REAL NOT NULL DEFAULT 0,
    pricing_known INTEGER NOT NULL DEFAULT 1,
    replayed     INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    attributes   TEXT
);
CREATE INDEX IF NOT EXISTS idx_spans_run ON spans(run_id, seq);

CREATE TABLE IF NOT EXISTS recordings (
    key         TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    model       TEXT,
    request     TEXT NOT NULL,
    response    TEXT NOT NULL,
    created_at  REAL NOT NULL
);

-- Prove layer: an explicit, hash-chained attestation of recorded runs.
-- One row per run in chain order. ``hash`` links to ``prev_hash`` so any
-- later edit to a covered run/span is detectable. ``signature`` (base64
-- Ed25519) and ``public_key`` are set only when the chain head was signed.
-- This table is written on demand (``agentveto prove sign``), never by the
-- tracing hot path, so recording stays fast and stdlib-only.
CREATE TABLE IF NOT EXISTS evidence (
    pos          INTEGER PRIMARY KEY,
    run_id       TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    run_digest   TEXT NOT NULL,
    hash         TEXT NOT NULL,
    signature    TEXT,
    public_key   TEXT,
    signed_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence(run_id);
"""

# A flight recorder stores everything, but a single pathological 8MB prompt
# should not be allowed to balloon the database. Truncate with a visible marker
# rather than silently dropping data.
MAX_FIELD_CHARS = 200_000


def default_db_path() -> str:
    explicit = os.environ.get("AGENTVETO_DB")
    if explicit:
        return os.path.abspath(explicit)
    return os.path.abspath(os.path.join(os.getcwd(), "agentveto.db"))


def _dump(value: Any) -> str | None:
    """Serialise a span payload. Never raises - tracing must not break the host app."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = repr(value)
    if len(text) > MAX_FIELD_CHARS:
        text = text[:MAX_FIELD_CHARS] + "\n\n...[truncated by agentveto]"
    return text


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or default_db_path()
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._seq: dict[str, int] = {}
        self._seq_lock = threading.Lock()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA)
            conn.commit()
            self._local.conn = conn
        return conn

    def _next_seq(self, run_id: str) -> int:
        with self._seq_lock:
            self._seq[run_id] = self._seq.get(run_id, 0) + 1
            return self._seq[run_id]

    def create_run(self, run_id: str, name: str, started_at: float, meta: dict | None = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO runs (id, name, started_at, ended_at, status, meta)"
                " VALUES (?, ?, ?, NULL, 'running', ?)",
                (run_id, name, started_at, _dump(meta)),
            )
            self.conn.commit()

    def finish_run(self, run_id: str, ended_at: float, status: str) -> None:
        with self._lock:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(cost),0) AS cost,"
                " COALESCE(SUM(tokens_in),0) AS ti,"
                " COALESCE(SUM(tokens_out),0) AS to_,"
                " COUNT(*) AS n FROM spans WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            self.conn.execute(
                "UPDATE runs SET ended_at=?, status=?, total_cost=?, tokens_in=?,"
                " tokens_out=?, span_count=? WHERE id=?",
                (ended_at, status, row["cost"], row["ti"], row["to_"], row["n"], run_id),
            )
            self.conn.commit()

    def insert_span(
        self,
        span_id: str,
        run_id: str,
        parent_id: str | None,
        name: str,
        kind: str,
        started_at: float,
        attributes: dict | None = None,
    ) -> int:
        seq = self._next_seq(run_id)
        with self._lock:
            self.conn.execute(
                "INSERT INTO spans (id, run_id, parent_id, seq, name, kind, started_at,"
                " status, attributes) VALUES (?,?,?,?,?,?,?,'running',?)",
                (span_id, run_id, parent_id, seq, name, kind, started_at, _dump(attributes)),
            )
            self.conn.commit()
        return seq

    def finish_span(
        self,
        span_id: str,
        ended_at: float,
        duration_ms: float,
        status: str,
        *,
        model: str | None = None,
        input: Any = None,
        output: Any = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
        pricing_known: bool = True,
        replayed: bool = False,
        error: str | None = None,
        attributes: dict | None = None,
    ) -> None:
        if attributes is not None:
            with self._lock:
                self.conn.execute(
                    "UPDATE spans SET attributes=? WHERE id=?",
                    (_dump(attributes), span_id),
                )
                self.conn.commit()
        with self._lock:
            self.conn.execute(
                "UPDATE spans SET ended_at=?, duration_ms=?, status=?, model=?, input=?,"
                " output=?, tokens_in=?, tokens_out=?, cost=?, pricing_known=?,"
                " replayed=?, error=? WHERE id=?",
                (
                    ended_at,
                    duration_ms,
                    status,
                    model,
                    _dump(input),
                    _dump(output),
                    tokens_in,
                    tokens_out,
                    cost,
                    1 if pricing_known else 0,
                    1 if replayed else 0,
                    error,
                    span_id,
                ),
            )
            self.conn.commit()

    def get_run(self, run_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def get_spans(self, run_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM spans WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return [dict(r) for r in rows]

    def list_runs(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def latest_run(self) -> dict | None:
        runs = self.list_runs(limit=1)
        return runs[0] if runs else None

    def list_runs_asc(self) -> list[dict]:
        """All runs in chain order (oldest first). SQLite ``rowid`` is the
        monotonic insertion order assigned by the engine, which is the only
        tie-break that survives two runs sharing a ``started_at`` (random
        hex ``id`` would otherwise scramble the chain)."""
        rows = self.conn.execute("SELECT * FROM runs ORDER BY rowid ASC").fetchall()
        return [dict(r) for r in rows]

    def save_evidence(
        self,
        blocks: list[dict],
        *,
        signature: str | None = None,
        public_key: str | None = None,
        signed_at: float | None = None,
    ) -> None:
        """Persist an attested chain. ``signature``/``public_key`` are stored on
        every row (same value) so a DB verification is self-contained."""
        with self._lock:
            self.conn.execute("DELETE FROM evidence")
            for b in blocks:
                self.conn.execute(
                    "INSERT INTO evidence (pos, run_id, prev_hash, run_digest, hash,"
                    " signature, public_key, signed_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        b["pos"],
                        b["run_id"],
                        b["prev_hash"],
                        b["run_digest"],
                        b["hash"],
                        signature,
                        public_key,
                        signed_at,
                    ),
                )
            self.conn.commit()

    def evidence_rows(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM evidence ORDER BY pos ASC").fetchall()
        return [dict(r) for r in rows]

    def save_recording(self, key: str, provider: str, model: str | None, request: Any, response: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO recordings (key, provider, model, request, response, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (key, provider, model, _dump(request), response, time.time()),
            )
            self.conn.commit()

    def get_recording(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM recordings WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def delete_run(self, run_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM spans WHERE run_id=?", (run_id,))
            self.conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
            self.conn.commit()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
