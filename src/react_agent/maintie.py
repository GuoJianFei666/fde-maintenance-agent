"""Load the pinned public corpus and index case texts, never repair instructions."""

import hashlib
import json
import re
import sqlite3
from collections import Counter
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from react_agent.models import ConflictError, NotFoundError
from react_agent.store import search_tokens

CATEGORIES = ("PhysicalObject", "State", "Process", "Activity", "Property")
PLACEHOLDERS = re.compile(r"<(?:id|num|date|sensitive)>", re.I)
# Small, explicit query aliases. This is lexical retrieval, not a translation model.
ALIASES = {
    "泵": "pump pumps", "泄漏": "leak leaking leaks", "漏油": "oil leak leaking",
    "渗漏": "leak leaking", "电机": "motor", "轴承": "bearing bearings",
    "输送带": "conveyor belt", "软管": "hose", "密封": "seal seals",
    "损坏": "broken failed damaged", "更换": "change replace replacement",
    "过热": "hot overheating", "温度": "temperature", "阀": "valve",
}


class GoldEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    type: str


class GoldRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    head: int = Field(ge=0)
    tail: int = Field(ge=0)
    type: str


class GoldRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1)
    tokens: list[str] = Field(min_length=1)
    entities: list[GoldEntity]
    relations: list[GoldRelation]

    @model_validator(mode="after")
    def check_annotations(self):
        for entity in self.entities:
            if not 0 <= entity.start < entity.end <= len(self.tokens):
                raise ValueError("invalid_gold_span")
            if entity.type.split("/")[0] not in CATEGORIES:
                raise ValueError("unknown_gold_entity_category")
        for relation in self.relations:
            if max(relation.head, relation.tail) >= len(self.entities):
                raise ValueError("invalid_gold_relation_endpoint")
        return self


def normalized_text(text):
    """Group identical normalized descriptions even when placeholders differ."""
    return " ".join(re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*|[\u4e00-\u9fff]",
                               PLACEHOLDERS.sub(" ", text.lower())))


def text_fingerprint(text):
    return hashlib.sha256(normalized_text(text).encode()).hexdigest()


def split_for(text):
    return "evaluation" if int(text_fingerprint(text)[:8], 16) % 5 == 0 else "reference"


def query_terms(query):
    clean = PLACEHOLDERS.sub(" ", query)
    aliases = " ".join(value for key, value in ALIASES.items() if key in clean)
    stop = {"the", "a", "an", "on", "in", "of", "for", "to", "and", "is", "with", "at"}
    return [term for term in search_tokens(clean + " " + aliases) if term not in stop]


def load_corpus():
    root = files("react_agent").joinpath("data/maintie")
    manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    for filename, expected in manifest["files"].items():
        raw = root.joinpath(filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected["sha256"] or len(raw) != expected["bytes"]:
            raise ValueError("maintie_file_hash_mismatch:" + filename)
    records = [GoldRecord.model_validate(row).model_dump()
               for row in json.loads(root.joinpath("gold_release.json").read_text(encoding="utf-8"))]
    if len(records) != manifest["record_count"]:
        raise ValueError("maintie_record_count_mismatch")
    return manifest, records


class MaintIEIndex:
    """Separate immutable public references from demo-device histories and evaluation rows."""

    def __init__(self, path: Path):
        self.path = path
        self.manifest, self.records = load_corpus()
        self.rows = {f"MAINTIE-GOLD-{i:04d}": row for i, row in enumerate(self.records)}
        path.parent.mkdir(parents=True, exist_ok=True)
        fingerprint = self.manifest["files"]["gold_release.json"]["sha256"]
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, row_index INTEGER NOT NULL,
                    body TEXT NOT NULL, text_sha256 TEXT NOT NULL, split TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS case_fts USING fts5(case_id UNINDEXED, terms);
            """)
            current = conn.execute("SELECT value FROM metadata WHERE key='corpus_sha256'").fetchone()
            if current and current[0] != fingerprint:
                raise ConflictError("maintie_corpus_changed_use_new_data_directory")
            if not current:
                with conn:
                    for i, (case_id, row) in enumerate(self.rows.items()):
                        split = split_for(row["text"])
                        conn.execute("INSERT INTO cases VALUES(?,?,?,?,?)", (
                            case_id, i, row["text"], text_fingerprint(row["text"]), split))
                        if split == "reference":
                            conn.execute("INSERT INTO case_fts VALUES(?,?)", (
                                case_id, " ".join(query_terms(row["text"]))))
                    conn.execute("INSERT INTO metadata VALUES('corpus_sha256',?)", (fingerprint,))

    def connection(self):
        # sqlite3's context manager commits/rolls back but does not close the handle.
        from contextlib import closing

        return closing(sqlite3.connect(self.path, timeout=15))

    def metadata(self):
        counts = Counter(split_for(row["text"]) for row in self.records)
        return {**self.manifest, "split_counts": dict(counts),
                "split_policy": "normalized-text SHA256 first 8 hex modulo 5: 0=evaluation; others=reference",
                "retrieval": "SQLite FTS5 / BM25, reference rows only, exact normalized query excluded",
                "query_aliases": ALIASES, "index_version": "maintie-lexical-v1"}

    def record(self, case_id, *, annotations=False):
        if case_id not in self.rows:
            raise NotFoundError("maintie_record_not_found")
        row = self.rows[case_id]
        i = int(case_id.rsplit("-", 1)[1])
        result = {"id": case_id, "row_index": i, "body": row["text"], "tokens": row["tokens"],
                  "split": split_for(row["text"]), "text_sha256": text_fingerprint(row["text"]),
                  "source": self.manifest["source_url"] + f"#record-{i}",
                  "version": self.manifest["revision"], "data_kind": "public_maintie_short_text",
                  "raw_sha256": self.manifest["files"]["gold_release.json"]["sha256"]}
        if annotations:
            result.update({"entities": row["entities"], "relations": row["relations"]})
        return result

    def evaluation_records(self):
        unique = {}
        for case_id in self.rows:
            row = self.record(case_id, annotations=True)
            if row["split"] == "evaluation":
                unique.setdefault(row["text_sha256"], row)
        return sorted(unique.values(), key=lambda row: row["text_sha256"])

    def search(self, query, top_k=3):
        terms = query_terms(query)
        if not terms:
            return []
        expression = " OR ".join('"' + term + '"' for term in terms)
        with self.connection() as conn:
            hits = conn.execute("""
                SELECT c.id, bm25(case_fts) AS rank FROM case_fts JOIN cases c ON c.id=case_fts.case_id
                WHERE case_fts MATCH ? AND c.split='reference' AND c.text_sha256 != ?
                ORDER BY rank, c.id LIMIT ?
            """, (expression, text_fingerprint(query), top_k)).fetchall()
        # Gold labels are deliberately absent from the retrieval response.
        return [{**self.record(case_id), "rank": rank} for case_id, rank in hits]
