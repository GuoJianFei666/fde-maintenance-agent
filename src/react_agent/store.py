"""Persist demo business data and retrieve Chinese manual chunks with FTS5."""

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

from react_agent.models import AlarmEvent, ConflictError, NotFoundError


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def search_tokens(text: str):
    """Use overlapping Chinese bigrams and ASCII terms, not raw FTS query syntax."""
    tokens = []
    for word in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            tokens.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            tokens.append(word)
    return list(dict.fromkeys(tokens))[:80]


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        seed = json.loads(files("react_agent").joinpath("data/seed.json").read_text(encoding="utf-8"))
        self.corpus_version = seed["version"]
        self.corpus_sha256 = content_hash(seed)
        with self.connection() as conn:
            conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS manuals(id TEXT PRIMARY KEY, device_type TEXT NOT NULL,
              title TEXT NOT NULL, body TEXT NOT NULL, source TEXT NOT NULL, version TEXT NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS manual_fts USING fts5(chunk_id UNINDEXED, terms);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
              alarm TEXT NOT NULL, alarm_hash TEXT NOT NULL, status TEXT NOT NULL, proposal TEXT,
              report TEXT, error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, source_run TEXT UNIQUE,
              device_id TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS traces(id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL, at TEXT NOT NULL, node TEXT NOT NULL, data TEXT NOT NULL);
            """)
            if "workflow" not in {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}:
                conn.execute("ALTER TABLE runs ADD COLUMN workflow TEXT NOT NULL DEFAULT 'alarm'")
            current = conn.execute("SELECT value FROM metadata WHERE key='corpus_sha256'").fetchone()
            if current and current["value"] != self.corpus_sha256:
                raise ValueError("Demo corpus changed; use a new OPS_DATA_DIR or explicitly migrate the database")
            if not current:
                for device in seed["devices"]:
                    conn.execute("INSERT INTO devices VALUES(?,?)", (device["id"], canonical_json(device)))
                for manual in seed["manuals"]:
                    conn.execute("INSERT INTO manuals VALUES(?,?,?,?,?,?)", tuple(manual[k] for k in
                                 ("id", "device_type", "title", "body", "source", "version")))
                    tokens = " ".join(search_tokens(manual["title"] + " " + manual["body"]))
                    conn.execute("INSERT INTO manual_fts(chunk_id,terms) VALUES(?,?)", (manual["id"], tokens))
                for order in seed["history"]:
                    conn.execute("INSERT INTO orders VALUES(?,NULL,?,?,?,?)", (
                        order["id"], order["device_id"], order["summary"], order["status"], canonical_json(order)))
                conn.execute("INSERT INTO metadata VALUES('corpus_sha256',?)", (self.corpus_sha256,))

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def devices(self):
        with self.connection() as conn:
            return [json.loads(r["data"]) for r in conn.execute("SELECT data FROM devices ORDER BY id")]

    def device(self, device_id):
        with self.connection() as conn:
            row = conn.execute("SELECT data FROM devices WHERE id=?", (device_id,)).fetchone()
        if not row:
            raise NotFoundError("device_not_found")
        return json.loads(row["data"])

    def manual(self, chunk_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM manuals WHERE id=?", (chunk_id,)).fetchone()
        if not row:
            raise NotFoundError("manual_chunk_not_found")
        return dict(row)

    def search(self, query, device_id, top_k=3):
        device = self.device(device_id)
        tokens = search_tokens(query)
        if not tokens:
            return []
        expression = " OR ".join('"' + token + '"' for token in tokens)
        with self.connection() as conn:
            rows = conn.execute("""
              SELECT m.*, bm25(manual_fts) AS rank FROM manual_fts
              JOIN manuals m ON m.id=manual_fts.chunk_id
              WHERE manual_fts MATCH ? AND m.device_type IN (?, 'general')
              ORDER BY rank, m.id LIMIT ?
            """, (expression, device["type"], top_k)).fetchall()
        return [dict(row) for row in rows]

    def orders(self, device_id=None):
        with self.connection() as conn:
            rows = conn.execute("SELECT data FROM orders WHERE device_id=? ORDER BY id", (device_id,)) \
                if device_id else conn.execute("SELECT data FROM orders ORDER BY id")
            return [json.loads(row["data"]) for row in rows]

    def create_run(self, alarm: AlarmEvent, *, workflow="alarm"):
        payload = alarm.model_dump()
        fingerprint = content_hash(payload if workflow == "alarm" else {"workflow": workflow, "input": payload})
        with self.connection() as conn:
            old = conn.execute("SELECT id,alarm_hash FROM runs WHERE event_id=?", (alarm.event_id,)).fetchone()
            if old:
                if old["alarm_hash"] != fingerprint:
                    raise ConflictError("event_id_reused_with_different_payload")
                return old["id"], False
            run_id = uuid.uuid4().hex
            now = utc_now()
            conn.execute("""INSERT INTO runs(id,event_id,alarm,alarm_hash,status,created_at,updated_at,workflow)
                VALUES(?,?,?,?,?,?,?,?)""", (
                run_id, alarm.event_id, canonical_json(payload), fingerprint, "running", now, now, workflow))
        return run_id, True

    def run(self, run_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise NotFoundError("run_not_found")
        result = dict(row)
        for key in ("alarm", "proposal", "report"):
            result[key] = json.loads(result[key]) if result[key] else None
        return result

    def update_run(self, run_id, status, *, proposal=None, report=None, error_code=None):
        with self.connection() as conn:
            conn.execute("UPDATE runs SET status=?,proposal=?,report=?,error_code=?,updated_at=? WHERE id=?", (
                status, canonical_json(proposal) if proposal is not None else None,
                canonical_json(report) if report is not None else None, error_code, utc_now(), run_id))

    def trace(self, run_id, node, data):
        with self.connection() as conn:
            conn.execute("INSERT INTO traces(run_id,at,node,data) VALUES(?,?,?,?)", (
                run_id, utc_now(), node, canonical_json(data)))

    def traces(self, run_id):
        self.run(run_id)
        with self.connection() as conn:
            rows = conn.execute("SELECT id,at,node,data FROM traces WHERE run_id=? ORDER BY id", (run_id,))
            return [{**dict(row), "data": json.loads(row["data"])} for row in rows]

    def create_order(self, run_id, device_id, proposal, *, data_kind="synthetic_demo"):
        """Insert once even if the graph replays this node after a crash."""
        with self.connection() as conn:
            old = conn.execute("SELECT data FROM orders WHERE source_run=?", (run_id,)).fetchone()
            if old:
                return json.loads(old["data"])
            order = {"id": "WO-" + run_id[:12].upper(), "source_run": run_id,
                     "device_id": device_id, "summary": proposal["summary"], "status": "open",
                     "proposal": proposal, "created_at": utc_now(), "data_kind": data_kind}
            conn.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)", (
                order["id"], run_id, device_id, order["summary"], "open", canonical_json(order)))
        return order

    def import_fixture(self, payload):
        """Add a labelled demo fixture without replacing the packaged corpus hash."""
        if payload.get("kind") != "adapted_synthetic_demo":
            raise ValueError("fixture_must_be_labelled_adapted_synthetic_demo")
        with self.connection() as conn:
            for device in payload["devices"]:
                if conn.execute("SELECT 1 FROM devices WHERE id=?", (device["id"],)).fetchone():
                    raise ValueError("fixture_device_exists:" + device["id"])
                conn.execute("INSERT INTO devices VALUES(?,?)", (device["id"], canonical_json(device)))
            for manual in payload["manuals"]:
                if conn.execute("SELECT 1 FROM manuals WHERE id=?", (manual["id"],)).fetchone():
                    raise ValueError("fixture_manual_exists:" + manual["id"])
                conn.execute("INSERT INTO manuals VALUES(?,?,?,?,?,?)", tuple(manual[k] for k in
                             ("id", "device_type", "title", "body", "source", "version")))
                tokens = " ".join(search_tokens(manual["title"] + " " + manual["body"]))
                conn.execute("INSERT INTO manual_fts(chunk_id,terms) VALUES(?,?)", (manual["id"], tokens))
            for order in payload.get("history", []):
                if conn.execute("SELECT 1 FROM orders WHERE id=?", (order["id"],)).fetchone():
                    raise ValueError("fixture_order_exists:" + order["id"])
                conn.execute("INSERT INTO orders VALUES(?,NULL,?,?,?,?)", (
                    order["id"], order["device_id"], order["summary"], order["status"], canonical_json(order)))
        return {"devices": [item["id"] for item in payload["devices"]],
                "manuals": [item["id"] for item in payload["manuals"]],
                "label": payload.get("label", "")}
