"""Score BM25, dense, hybrid, and reranked retrieval. Fake mode downloads nothing."""

import argparse
import json
import tempfile
import time
from pathlib import Path

from evals.common import file_sha256, run_record
from evals.retrieval.metrics import first_rank, summarise
from react_agent.config import Settings
from react_agent.retrieval import FAKE_RERANKER_ID, IndexNotReady, ManualRetriever
from react_agent.store import Store, content_hash, search_tokens

ROOT = Path(__file__).resolve().parents[2]
LABELS = Path(__file__).resolve().parent / "labels.json"
FROZEN = Path(__file__).resolve().parent / "frozen_config.json"
ENGLISH_FIXTURE = ROOT / "evals" / "assetopsbench" / "fixtures" / "english_demo.json"
KNOB_KEYS = ("embedding_model", "reranker_model", "rrf_k", "fused_top_n", "rerank_top_k")
FORMULA = {"method": "reciprocal_rank_fusion", "expression": "1/(k+rank)", "rank_origin": 1,
           "missing_list_contribution": 0, "default_k": 60,
           "citation": "Cormack, Clarke, Buettcher, SIGIR 2009"}


def load_labels():
    return json.loads(LABELS.read_text(encoding="utf-8"))


def load_frozen_config():
    return json.loads(FROZEN.read_text(encoding="utf-8"))


def knob_document(config):
    return {key: config[key] for key in KNOB_KEYS}


def resolve_config(split, embedding_model, reranker_model, rrf_k, fused_top_n, rerank_top_k):
    """Dev may change knobs. Test refuses overrides and an unfrozen file."""
    frozen = load_frozen_config()
    overrides = {"embedding_model": embedding_model, "reranker_model": reranker_model,
                 "rrf_k": rrf_k, "fused_top_n": fused_top_n, "rerank_top_k": rerank_top_k}
    if split == "test":
        if not (frozen.get("frozen") and frozen.get("frozen_before_split") == "test"):
            raise SystemExit("测试集要求 frozen_config.json 已冻结，且 frozen_before_split 为 test。未写入分数。")
        changed = [key for key, value in overrides.items() if value is not None]
        if changed:
            raise SystemExit("测试集不接受调参参数（" + ",".join(changed) + "）。未写入分数。")
        used = knob_document(frozen)
    else:
        used = knob_document(frozen)
        for key, value in overrides.items():
            if value is not None:
                used[key] = value
    return frozen, content_hash(frozen), used, content_hash(used)


def select_split(labels, split):
    chosen = [item for item in labels["queries"] if item.get("split") == split]
    if not chosen:
        raise SystemExit("切分里没有查询：" + split)
    return {**labels, "queries": chosen}


def validate_labels(store, labels):
    manuals = {item["id"]: item for item in store.manuals()}
    allowed_kinds = {"lexical", "paraphrase_no_overlap", "error_code"}
    seen = set()
    splits = set()
    for item in labels["queries"]:
        if item["id"] in seen:
            raise SystemExit("查询编号重复：" + item["id"])
        seen.add(item["id"])
        if item.get("split") not in {"dev", "test"}:
            raise SystemExit("查询必须属于 dev 或 test：" + item["id"])
        splits.add(item["split"])
        if item["kind"] not in allowed_kinds:
            raise SystemExit("未知查询类型：" + item["kind"])
        chunk = manuals.get(item["relevant_ids"][0])
        if chunk is None:
            raise SystemExit("标注指向不存在的手册：" + item["id"])
        device = store.device(item["device_id"])
        if chunk["device_type"] not in {device["type"], "general"}:
            raise SystemExit("标注设备与手册类型不一致：" + item["id"])
        chunk_tokens = set(search_tokens(chunk["title"] + " " + chunk["body"]))
        shared = set(search_tokens(item["query"])) & chunk_tokens
        if item["kind"] == "paraphrase_no_overlap" and shared:
            raise SystemExit(item["id"] + " 与目标手册仍有词面重合")
        if item["kind"] == "lexical" and not shared:
            raise SystemExit(item["id"] + " 与目标手册没有词面重合")
        if item["kind"] == "error_code" and not set(search_tokens(item["query"])).issubset(chunk_tokens):
            raise SystemExit(item["id"] + " 的错误码不在目标手册中")
    if splits != {"dev", "test"}:
        raise SystemExit("标注必须同时包含 dev 和 test。")
    return labels


def prepare(directory: Path, embedder: str, used: dict):
    store = Store(directory / "business.db")
    store.import_fixture(json.loads(ENGLISH_FIXTURE.read_text(encoding="utf-8")))
    settings = Settings(data_dir=directory, retriever="dense", embedder=embedder,
                        embedding_model=used["embedding_model"], reranker_model=used["reranker_model"],
                        rrf_k=used["rrf_k"], retrieval_candidates=used["fused_top_n"])
    retriever = ManualRetriever(settings, store)
    index = retriever.build_index()
    return store, retriever, index


def score_mode(retriever, labels, mode, top_k):
    retriever.mode = mode
    if mode != "bm25":
        retriever._embedder_model()
    if mode == "hybrid_rerank":
        retriever._reranker_model()
    rows = []
    for item in labels["queries"]:
        started = time.perf_counter()
        hits, label = retriever.search(item["query"], item["device_id"], top_k)
        elapsed = (time.perf_counter() - started) * 1000
        retrieved = [hit["id"] for hit in hits]
        rows.append({"id": item["id"], "kind": item["kind"],
                     "rank": first_rank(retrieved, item["relevant_ids"]),
                     "latency_ms": elapsed, "retrieved_ids": retrieved, "retrieval": label})
    by_kind = {}
    for kind in sorted({row["kind"] for row in rows}):
        chosen = [row for row in rows if row["kind"] == kind]
        by_kind[kind] = summarise([row["rank"] for row in chosen], [row["latency_ms"] for row in chosen])
    overall = summarise([row["rank"] for row in rows], [row["latency_ms"] for row in rows])
    return {"metrics": overall, "by_kind": by_kind, "queries": rows}


def run_eval(directory, *, split, embedder, embedding_model=None, reranker_model=None, rrf_k=None,
             fused_top_n=None, rerank_top_k=None, modes, seed):
    frozen, frozen_hash, used, used_hash = resolve_config(
        split, embedding_model, reranker_model, rrf_k, fused_top_n, rerank_top_k)
    store, retriever, index = prepare(directory, embedder, used)
    labels = validate_labels(store, load_labels())
    selected = select_split(labels, split)
    mode_scores = {mode: score_mode(retriever, selected, mode, used["rerank_top_k"]) for mode in modes}
    model_id = index["embedder_id"]
    if retriever._reranker is not None:
        reranker_id = retriever._reranker.name
    elif embedder == "fake":
        reranker_id = FAKE_RERANKER_ID
    else:
        reranker_id = used["reranker_model"]
    counts = {name: sum(item["split"] == name for item in labels["queries"]) for name in ("dev", "test")}
    record = run_record(
        root=ROOT, model_id=model_id, prompt_version="retrieval-rrf-v1",
        prompt_sha256=content_hash(FORMULA),
        dataset={"name": labels["version"], "languages": ["zh", "en"],
                 "chinese_manuals": "packaged synthetic demo",
                 "english_manuals": "adapted_synthetic_demo",
                 "label_version": labels["version"], "label_sha256": file_sha256(LABELS),
                 "query_count": len(selected["queries"]),
                 "query_ids": [item["id"] for item in selected["queries"]],
                 "dev_count": counts["dev"], "test_count": counts["test"]},
        seed=seed, split=split,
        extra={"embedder": embedder, "embedding_model": used["embedding_model"],
               "reranker_model": reranker_id, "index": index, "config": used,
               "config_sha256": used_hash, "frozen_config_sha256": frozen_hash,
               "config_matches_frozen": used_hash == content_hash(knob_document(frozen)),
               "modes": mode_scores,
               "scores_are_model_results": embedder == "sentence-transformers",
               "note": "Tuning knobs are applied on dev only. The test split refuses overrides. "
                       "config_sha256 hashes the five knobs actually used. "
                       "frozen_config_sha256 hashes the whole frozen file. "
                       "A fake embedder does not produce model scores."},
    )
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description="评测手册检索的四种模式")
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--embedder", choices=["fake", "sentence-transformers"], default="fake")
    parser.add_argument("--model", default=None, help="开发集可改嵌入模型。测试集拒绝此参数。")
    parser.add_argument("--reranker", default=None, help="开发集可改重排序模型。测试集拒绝此参数。")
    parser.add_argument("--rrf-k", type=int, default=None)
    parser.add_argument("--candidates", type=int, default=None, help="融合后送去重排序的前 N 条。")
    parser.add_argument("--top-k", type=int, default=None, help="重排序后保留的条数，也是评测名次的深度。")
    parser.add_argument("--modes", default="bm25,dense,hybrid,hybrid_rerank")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    unknown = [item for item in modes if item not in {"bm25", "dense", "hybrid", "hybrid_rerank"}]
    if unknown:
        raise SystemExit("未知检索模式：" + ",".join(unknown))
    if args.split == "test" and args.embedder == "sentence-transformers" and args.out.exists():
        raise SystemExit("该测试结果文件已存在，不再覆盖。请换一个 --out。")
    if args.embedder == "sentence-transformers":
        try:
            import importlib
            importlib.import_module("sentence_transformers")
        except ImportError:
            raise SystemExit(
                "未安装 sentence-transformers，未写入分数。"
                "本地安装：py -3 -m pip install \"sentence-transformers>=3,<6\"") from None
    try:
        with tempfile.TemporaryDirectory() as directory:
            record = run_eval(Path(directory), split=args.split, embedder=args.embedder,
                              embedding_model=args.model, reranker_model=args.reranker,
                              rrf_k=args.rrf_k, fused_top_n=args.candidates, rerank_top_k=args.top_k,
                              modes=modes, seed=args.seed)
    except IndexNotReady as exc:
        raise SystemExit("模型或索引不可用，未写入分数：" + str(exc)) from None
    except Exception as exc:
        if args.embedder != "sentence-transformers":
            raise
        raise SystemExit("模型未能加载，未写入分数：" + type(exc).__name__) from None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
