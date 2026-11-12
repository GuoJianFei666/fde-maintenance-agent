"""Score the frozen retrieval config on TechManualQA-700 or TechQA-RAG-Eval.

Dense ranking is an exact dot product of the same L2-normalised embeddings the
in-domain retriever uses. sqlite-vec 0.1.9 refuses a KNN k above 4096, and the
TechQA corpus is larger than that, so this script does not claim a sqlite-vec
scan. BM25 still uses SQLite FTS5. The five frozen knobs are not overridden on
the test split.
"""

import argparse
import json
import tempfile
import time
from pathlib import Path

from evals.common import run_record
from evals.retrieval.metrics import summarise
from evals.retrieval.public_corpus import index_tokens, load_fixture, load_official, select_split
from evals.retrieval.public_source import dataset_meta
from evals.retrieval.run import FORMULA, knob_document, resolve_config
from react_agent.config import Settings
from react_agent.retrieval import load_embedder, load_reranker, passage_text, reciprocal_rank_fusion
from react_agent.store import Store, canonical_json, content_hash

ROOT = Path(__file__).resolve().parents[2]
DEVICE_ID = "BENCH"


def dataset_record(dataset, passages, queries, selected):
    meta = dataset_meta(dataset)
    answerable = [item for item in selected if item["answerable"]]
    return {
        "name": meta["name"],
        "license": meta["license"],
        "revision": meta["revision"],
        "languages": ["en"],
        "passage_count": len(passages),
        "query_count": len(selected),
        "answerable_count": len(answerable),
        "unanswerable_count": len(selected) - len(answerable),
        "dev_count": sum(item["split"] == "dev" for item in queries),
        "test_count": sum(item["split"] == "test" for item in queries),
        "split_rule": meta["split_rule"],
        "passage_rule": meta["passage_rule"],
        "query_ids": [item["id"] for item in selected],
    }


def prepare_store(directory: Path, passages):
    store = Store(directory / "business.db")
    device = {"id": DEVICE_ID, "name": "public retrieval bench", "type": "benchmark",
              "location": "eval", "owner_team": "eval", "status": "running", "data_kind": "public_eval"}
    with store.connection() as conn:
        conn.execute("DELETE FROM manual_fts")
        conn.execute("DELETE FROM manuals")
        conn.execute("INSERT INTO devices VALUES(?,?)", (DEVICE_ID, canonical_json(device)))
        conn.executemany("INSERT INTO manuals VALUES(?,?,?,?,?,?)", (
            (item["id"], item["device_type"], item["title"], item["body"], "public_eval", "v1")
            for item in passages))
        conn.executemany("INSERT INTO manual_fts(chunk_id,terms) VALUES(?,?)", (
            (item["id"], " ".join(index_tokens(item["title"] + " " + item["body"]))) for item in passages))
    return store


def embed_passages(embedder, passages):
    texts = [passage_text(item) for item in passages]
    if getattr(embedder, "model_id", None):
        prepared = [embedder._passage(text) for text in texts]
        matrix = embedder._model.encode(prepared, batch_size=32, normalize_embeddings=True, show_progress_bar=True)
        return [[float(value) for value in row] for row in matrix]
    return embedder.embed_passages(texts)


def top_ids(matrix, query, ids, pool):
    if not matrix:
        return []
    try:
        import numpy as np
        scores = np.asarray(matrix, dtype="float32").dot(np.asarray(query, dtype="float32")).tolist()
    except ImportError:
        scores = [sum(left * right for left, right in zip(row, query, strict=True)) for row in matrix]
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], ids[index]))
    return [ids[index] for index in order[:pool]]


def passage_lookup(passages):
    return {item["id"]: item for item in passages}


def score_queries_fast(store, embedder, reranker, passages, matrix, queries, *, rrf_k, pool, top_k):
    """Same scoring, with passage lookup instead of list.index."""
    by_id = passage_lookup(passages)
    ids = [item["id"] for item in passages]
    modes = ("bm25", "dense", "hybrid", "hybrid_rerank")
    rows = {mode: [] for mode in modes}
    if reranker is not None:
        reranker.score("warmup", ["warmup passage"])
    for number, item in enumerate(queries, start=1):
        if number == 1 or number % 50 == 0:
            print(f"query {number}/{len(queries)}", flush=True)
        started = time.perf_counter()
        lexical = [hit["id"] for hit in store.search(item["query"], DEVICE_ID, pool)]
        after_lexical = time.perf_counter()
        vector = embedder.embed_query(item["query"])
        dense = top_ids(matrix, vector, ids, pool)
        after_dense = time.perf_counter()
        fused, _scores = reciprocal_rank_fusion([lexical, dense], rrf_k)
        after_hybrid = time.perf_counter()
        rerank_ids = fused[:pool]
        if reranker and rerank_ids:
            texts = [passage_text(by_id[chunk_id]) for chunk_id in rerank_ids]
            scores = reranker.score(item["query"], texts)
            order = sorted(range(len(rerank_ids)), key=lambda index: (-scores[index], rerank_ids[index]))
            reranked = [rerank_ids[index] for index in order[:top_k]]
        else:
            reranked = fused[:top_k]
        finished = time.perf_counter()
        lists = {
            "bm25": (lexical[:top_k], (after_lexical - started) * 1000),
            "dense": (dense[:top_k], (after_dense - after_lexical) * 1000),
            "hybrid": (fused[:top_k], (after_hybrid - started) * 1000),
            "hybrid_rerank": (reranked, (finished - started) * 1000),
        }
        for mode, (retrieved, elapsed) in lists.items():
            rank = None
            relevant = item["relevant_ids"]
            if relevant:
                for index, chunk_id in enumerate(retrieved, start=1):
                    if chunk_id in relevant:
                        rank = index
                        break
            rows[mode].append({"id": item["id"], "kind": item["kind"], "answerable": item["answerable"],
                               "rank": rank, "latency_ms": round(elapsed, 3), "retrieved_ids": retrieved})
    scored = {}
    for mode, mode_rows in rows.items():
        answerable = [row for row in mode_rows if row["answerable"]]
        metrics = summarise([row["rank"] for row in answerable], [row["latency_ms"] for row in mode_rows])
        metrics["answerable_count"] = len(answerable)
        metrics["unanswerable_count"] = len(mode_rows) - len(answerable)
        by_kind = {}
        for kind in sorted({row["kind"] for row in answerable}):
            chosen = [row for row in answerable if row["kind"] == kind]
            by_kind[kind] = summarise([row["rank"] for row in chosen], [row["latency_ms"] for row in chosen])
        scored[mode] = {"metrics": metrics, "by_kind": by_kind, "queries": mode_rows}
    return scored


def run_dataset(directory, dataset, passages, queries, *, split, embedder_name, embedding_model=None,
                reranker_model=None, rrf_k=None, fused_top_n=None, rerank_top_k=None, seed=7):
    frozen, frozen_hash, used, used_hash = resolve_config(
        split, embedding_model, reranker_model, rrf_k, fused_top_n, rerank_top_k)
    selected = select_split(queries, split)
    store = prepare_store(directory, passages)
    settings = Settings(data_dir=directory, embedder=embedder_name, embedding_model=used["embedding_model"],
                        reranker_model=used["reranker_model"], rrf_k=used["rrf_k"],
                        retrieval_candidates=used["fused_top_n"])
    embedder = load_embedder(embedder_name, settings.embedding_model)
    print(f"embedding {len(passages)} passages", flush=True)
    matrix = embed_passages(embedder, passages)
    reranker = load_reranker(embedder_name, settings.reranker_model)
    modes = score_queries_fast(
        store, embedder, reranker, passages, matrix, selected, rrf_k=used["rrf_k"],
        pool=used["fused_top_n"], top_k=used["rerank_top_k"])
    record = run_record(
        root=ROOT, model_id=embedder.name, prompt_version="retrieval-rrf-v1",
        prompt_sha256=content_hash(FORMULA), dataset=dataset_record(dataset, passages, queries, selected),
        seed=seed, split=split,
        extra={"embedder": embedder_name, "embedding_model": used["embedding_model"],
               "reranker_model": reranker.name, "config": used, "config_sha256": used_hash,
               "frozen_config_sha256": frozen_hash,
               "config_matches_frozen": used_hash == content_hash(knob_document(frozen)),
               "modes": modes, "scores_are_model_results": embedder_name == "sentence-transformers",
               "dense_ranking": "exact_dot_product_of_l2_normalised_embeddings",
               "bm25": "SQLite FTS5. Documents keep every token. Queries use the production 80-token cap.",
               "note": "Test split refuses knob overrides. Unanswerable questions are excluded from "
                       "Recall, MRR, and nDCG. sqlite-vec is not used because its KNN k limit is 4096."},
    )
    return record


def write_record(path: Path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="用冻结配置评测公开英文检索集")
    parser.add_argument("--dataset", choices=["techmanualqa", "techqa"], required=True)
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--embedder", choices=["fake", "sentence-transformers"], default="fake")
    parser.add_argument("--fixture", action="store_true", help="只用仓库里的小样例，不下载。")
    parser.add_argument("--questions", type=Path, default=None)
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--reranker", default=None)
    parser.add_argument("--rrf-k", type=int, default=None)
    parser.add_argument("--candidates", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.split == "test" and args.embedder == "sentence-transformers" and args.out.exists():
        raise SystemExit("该测试结果文件已存在，不再覆盖。请换一个 --out。")
    if args.embedder == "sentence-transformers":
        try:
            import importlib
            importlib.import_module("sentence_transformers")
        except ImportError:
            raise SystemExit("未安装 sentence-transformers，未写入分数。") from None
    if args.fixture:
        passages, queries = load_fixture(args.dataset)
    else:
        if args.questions is None:
            raise SystemExit("正式评测需要 --questions，或改用 --fixture。")
        passages, queries = load_official(args.dataset, args.questions, args.corpus)
    with tempfile.TemporaryDirectory() as directory:
        record = run_dataset(
            Path(directory), args.dataset, passages, queries, split=args.split, embedder_name=args.embedder,
            embedding_model=args.model, reranker_model=args.reranker, rrf_k=args.rrf_k,
            fused_top_n=args.candidates, rerank_top_k=args.top_k, seed=args.seed)
    write_record(args.out, record)
    print(args.out)


if __name__ == "__main__":
    main()
