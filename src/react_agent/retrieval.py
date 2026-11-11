"""BM25, sqlite-vec dense search, reciprocal rank fusion, and cross-encoder rerank.

The default mode is BM25 and does not load an embedding model. Dense modes read
an index built offline by scripts/build_manual_index.py. Vectors live in the
same business database. sqlite-vec 0.1.9 rejects a device-type filter inside a
KNN query, so the search asks for every indexed row and keeps the device type
in Python. The demo corpus is small enough that this is an exact scan.
"""

import hashlib
import math
import sqlite3
import threading
from datetime import datetime, timezone

from react_agent.store import content_hash, search_tokens

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
RERANKER_MODEL = "BAAI/bge-reranker-base"
FAKE_EMBEDDER_ID = "fake-hash-v1"
FAKE_RERANKER_ID = "fake-token-overlap-v1"


class IndexNotReady(Exception):
    """Dense search was asked for before a matching offline index existed."""


def reciprocal_rank_fusion(rankings, k=60):
    """Fuse ranked id lists. Rank starts at 1. A missing list adds nothing.

    score(d) = sum over lists that contain d of 1 / (k + rank). This is the
    Reciprocal Rank Fusion score from Cormack, Clarke, and Buettcher, SIGIR 2009.
    Ties break on the chunk id so the order is stable.
    """
    if k < 1:
        raise ValueError("rrf_k_must_be_positive")
    scores = {}
    for ranking in rankings:
        for index, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + index + 1)
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return ordered, scores


def _l2_normalize(vector):
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        vector = vector[:]
        vector[0] = 1.0
        norm = 1.0
    return [value / norm for value in vector]


def cosine_from_l2(distance):
    """Cosine of two L2-normalised vectors, recovered from their L2 distance."""
    return 1.0 - (distance * distance) / 2.0


class HashEmbedder:
    """Bag-of-token hashing. Deterministic, offline, and not a semantic model."""

    name = FAKE_EMBEDDER_ID
    dimension = 32

    def embed_passages(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)

    def _embed(self, text):
        vector = [0.0] * self.dimension
        tokens = search_tokens(text) or ["_empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode()).digest()
            bucket = digest[0] % self.dimension
            sign = 1.0 if digest[1] % 2 == 0 else -1.0
            vector[bucket] += sign
        return _l2_normalize(vector)


class OverlapReranker:
    """Token Jaccard. Used only when EMBEDDER=fake, so CI never downloads weights."""

    name = FAKE_RERANKER_ID

    def score(self, query, texts):
        query_tokens = set(search_tokens(query))
        scored = []
        for text in texts:
            tokens = set(search_tokens(text))
            union = len(query_tokens | tokens)
            scored.append((len(query_tokens & tokens) / union) if union else 0.0)
        return scored


class SentenceTransformerEmbedder:
    def __init__(self, model_id):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise IndexNotReady("sentence_transformers_not_installed") from exc
        self.model_id = model_id
        self.name = model_id
        self._model = SentenceTransformer(model_id, device="cpu")
        dimension = getattr(self._model, "get_embedding_dimension", None)
        if dimension is None:
            dimension = self._model.get_sentence_embedding_dimension
        self.dimension = int(dimension())

    def embed_passages(self, texts):
        prepared = [self._passage(text) for text in texts]
        return self._encode(prepared)

    def embed_query(self, text):
        return self._encode([self._query(text)])[0]

    def _query(self, text):
        if "e5" in self.model_id.lower():
            return "query: " + text
        return text

    def _passage(self, text):
        if "e5" in self.model_id.lower():
            return "passage: " + text
        return text

    def _encode(self, texts):
        matrix = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [[float(value) for value in row] for row in matrix]


class CrossEncoderReranker:
    def __init__(self, model_id):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise IndexNotReady("sentence_transformers_not_installed") from exc
        self.name = model_id
        self._model = CrossEncoder(model_id, device="cpu")

    def score(self, query, texts):
        if not texts:
            return []
        raw = self._model.predict([(query, text) for text in texts], show_progress_bar=False)
        try:
            return [float(value) for value in raw]
        except TypeError:
            return [float(raw)]


def load_embedder(kind, model_id):
    if kind == "fake":
        return HashEmbedder()
    if kind == "sentence-transformers":
        return SentenceTransformerEmbedder(model_id)
    raise ValueError("unknown_embedder")


def load_reranker(kind, model_id):
    if kind == "fake":
        return OverlapReranker()
    if kind == "sentence-transformers":
        return CrossEncoderReranker(model_id)
    raise ValueError("unknown_reranker")


def passage_text(manual):
    return manual["title"] + "\n" + manual["body"]


def corpus_fingerprint(manuals):
    payload = [{"id": item["id"], "device_type": item["device_type"], "title": item["title"],
                "body": item["body"]} for item in sorted(manuals, key=lambda item: item["id"])]
    return content_hash(payload)


class ManualRetriever:
    def __init__(self, settings, store):
        self.settings = settings
        self.store = store
        self.mode = settings.retriever
        self._lock = threading.Lock()
        self._embedder = None
        self._reranker = None

    @classmethod
    def from_env(cls, store):
        import os

        from react_agent.config import Settings

        settings = Settings(
            data_dir=store.path.parent,
            retriever=os.getenv("RETRIEVER", "bm25").strip() or "bm25",
            rrf_k=int(os.getenv("RRF_K", "60")),
            retrieval_candidates=int(os.getenv("RETRIEVAL_CANDIDATES", "20")),
            embedding_model=os.getenv("EMBEDDING_MODEL", EMBEDDING_MODEL).strip() or EMBEDDING_MODEL,
            reranker_model=os.getenv("RERANKER_MODEL", RERANKER_MODEL).strip() or RERANKER_MODEL,
            embedder=os.getenv("EMBEDDER", "sentence-transformers").strip() or "sentence-transformers",
        )
        return cls(settings, store)

    def label(self):
        if self.mode == "bm25":
            return "SQLite FTS5 / BM25"
        if self.mode == "dense":
            return "sqlite-vec dense"
        if self.mode == "hybrid":
            return f"RRF k={self.settings.rrf_k} bm25+dense"
        return f"RRF k={self.settings.rrf_k} bm25+dense, cross-encoder rerank"

    def search(self, query, device_id, top_k=3):
        if self.mode == "bm25":
            return self.store.search(query, device_id, top_k), self.label()
        pool = max(top_k, self.settings.retrieval_candidates)
        manuals = {item["id"]: item for item in self.store.manuals()}
        device_type = self.store.device(device_id)["type"]
        allowed = {device_type, "general"}
        dense_ids, dense_scores = self._dense_ids(query, manuals, allowed)
        if self.mode == "dense":
            chosen = dense_ids[:top_k]
            hits = [_hit(manuals[chunk_id], dense_scores[chunk_id]) for chunk_id in chosen]
            return hits, self.label()
        lexical_ids = [row["id"] for row in self.store.search(query, device_id, pool)]
        fused_ids, fused_scores = reciprocal_rank_fusion(
            [lexical_ids[:pool], dense_ids[:pool]], self.settings.rrf_k)
        if self.mode == "hybrid":
            chosen = fused_ids[:top_k]
            hits = [_hit(manuals[chunk_id], fused_scores[chunk_id], rrf_score=fused_scores[chunk_id])
                    for chunk_id in chosen]
            return hits, self.label()
        rerank_ids = fused_ids[:pool]
        texts = [passage_text(manuals[chunk_id]) for chunk_id in rerank_ids]
        rerank_scores = self._reranker_model().score(query, texts)
        order = sorted(range(len(rerank_ids)),
                       key=lambda index: (-rerank_scores[index], rerank_ids[index]))
        hits = []
        for index in order[:top_k]:
            chunk_id = rerank_ids[index]
            hits.append(_hit(manuals[chunk_id], rerank_scores[index], rrf_score=fused_scores[chunk_id],
                             rerank_score=rerank_scores[index]))
        return hits, self.label()

    def build_index(self):
        manuals = self.store.manuals()
        embedder = self._embedder_model()
        vectors = embedder.embed_passages([passage_text(item) for item in manuals]) if manuals else []
        if vectors and len(vectors[0]) != embedder.dimension:
            raise IndexNotReady("embedder_dimension_mismatch")
        fingerprint = corpus_fingerprint(manuals)
        now = datetime.now(timezone.utc).isoformat()
        with self._vector_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS manual_index_meta(
                key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
            conn.execute("DROP TABLE IF EXISTS manual_vec")
            dimension = int(embedder.dimension)
            conn.execute("CREATE VIRTUAL TABLE manual_vec USING vec0("
                         "chunk_id TEXT PRIMARY KEY, embedding float[" + str(dimension) + "])")
            from sqlite_vec import serialize_float32
            conn.executemany("INSERT INTO manual_vec(chunk_id, embedding) VALUES(?,?)", (
                (item["id"], serialize_float32(vector)) for item, vector in zip(manuals, vectors, strict=True)))
            for key, value in (("embedder_id", embedder.name), ("dimension", str(embedder.dimension)),
                               ("fingerprint", fingerprint), ("built_at", now), ("count", str(len(manuals)))):
                conn.execute("INSERT INTO manual_index_meta(key, value) VALUES(?,?) "
                             "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        return {"embedder_id": embedder.name, "dimension": embedder.dimension,
                "fingerprint": fingerprint, "count": len(manuals)}

    def _dense_ids(self, query, manuals, allowed):
        embedder = self._embedder_model()
        vector = embedder.embed_query(query)
        from sqlite_vec import serialize_float32
        with self._vector_connection() as conn:
            meta = self._read_meta(conn)
            if meta.get("embedder_id") != embedder.name or meta.get("dimension") != str(embedder.dimension):
                raise IndexNotReady("manual_index_model_mismatch")
            if meta.get("fingerprint") != corpus_fingerprint(list(manuals.values())):
                raise IndexNotReady("manual_index_stale")
            count = conn.execute("SELECT count(*) FROM manual_vec").fetchone()[0]
            if count == 0:
                raise IndexNotReady("manual_index_missing")
            rows = conn.execute(
                "SELECT chunk_id, distance FROM manual_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (serialize_float32(vector), count)).fetchall()
        ranked = []
        for row in rows:
            manual = manuals.get(row["chunk_id"])
            if manual and manual["device_type"] in allowed:
                ranked.append((row["chunk_id"], cosine_from_l2(row["distance"])))
        return [chunk_id for chunk_id, _score in ranked], dict(ranked)

    def _read_meta(self, conn):
        found = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='manual_index_meta' AND type='table'").fetchone()
        if not found:
            raise IndexNotReady("manual_index_missing")
        return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM manual_index_meta")}

    def _embedder_model(self):
        with self._lock:
            if self._embedder is None:
                self._embedder = load_embedder(self.settings.embedder, self.settings.embedding_model)
            return self._embedder

    def _reranker_model(self):
        with self._lock:
            if self._reranker is None:
                self._reranker = load_reranker(self.settings.embedder, self.settings.reranker_model)
            return self._reranker

    def _vector_connection(self):
        return _VectorConnection(self.store.path)


def _hit(manual, score, rrf_score=None, rerank_score=None):
    hit = dict(manual)
    hit["score"] = score
    if rrf_score is not None:
        hit["rrf_score"] = rrf_score
    if rerank_score is not None:
        hit["rerank_score"] = rerank_score
    return hit


class _VectorConnection:
    def __init__(self, path):
        self.path = path
        self.conn = None

    def __enter__(self):
        try:
            import sqlite_vec
        except ImportError as exc:
            raise IndexNotReady("manual_index_extension_unavailable") from exc
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except (AttributeError, sqlite3.OperationalError) as exc:
            conn.close()
            raise IndexNotReady("manual_index_extension_unavailable") from exc
        self.conn = conn
        return conn

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()
