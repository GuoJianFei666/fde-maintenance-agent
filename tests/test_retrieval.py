import json
from pathlib import Path

import pytest

from evals.retrieval.metrics import summarise
from evals.retrieval.run import content_hash, knob_document, load_frozen_config, resolve_config, run_eval
from mcp_server import server
from react_agent.config import Settings
from react_agent.mcp_client import _retrieval_env
from react_agent.retrieval import IndexNotReady, ManualRetriever, reciprocal_rank_fusion
from react_agent.service import AgentService
from react_agent.store import Store
from react_agent.tools import execute_tool
from tests.fakes import ScriptedModel
from tests.test_workflow import alarm

ENGLISH_FIXTURE = Path(__file__).resolve().parents[1] / "evals" / "assetopsbench" / "fixtures" / "english_demo.json"


def test_rrf_score_uses_one_based_ranks_and_stable_ties():
    ordered, scores = reciprocal_rank_fusion([["d1", "d2"], ["d2", "d3"]], k=60)
    assert ordered == ["d2", "d1", "d3"]
    assert scores["d1"] == pytest.approx(1 / 61)
    assert scores["d2"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["d3"] == pytest.approx(1 / 62)


def test_default_retriever_remains_bm25(tmp_path):
    store = Store(tmp_path / "business.db")
    settings = Settings(data_dir=tmp_path)
    assert settings.retriever == "bm25"
    hits, label = ManualRetriever(settings, store).search("泵振动", "P-101", 3)
    assert label == "SQLite FTS5 / BM25"
    assert "PUMP-VIB-01" in [hit["id"] for hit in hits]
    assert "score" not in hits[0]


def test_dense_without_an_index_returns_a_tool_error(tmp_path):
    store = Store(tmp_path / "business.db")
    settings = Settings(data_dir=tmp_path, retriever="dense", embedder="fake")
    state = {"alarm": {"device_id": "P-101"}, "retrieved_ids": []}
    result, patch = execute_tool("search_manual", {"query": "泵振动", "top_k": 3}, state, store,
                                 retriever=ManualRetriever(settings, store))
    assert result["ok"] is False
    assert result["error_code"] == "manual_index_missing"
    assert patch == {}


def test_dev_and_test_are_disjoint_and_the_test_config_is_frozen(tmp_path):
    frozen = load_frozen_config()
    assert frozen["frozen"] is True
    assert frozen["frozen_before_split"] == "test"
    dev = run_eval(tmp_path / "dev", split="dev", embedder="fake",
                   modes=["bm25", "dense", "hybrid", "hybrid_rerank"], seed=7)
    test = run_eval(tmp_path / "test", split="test", embedder="fake",
                    modes=["bm25", "dense", "hybrid", "hybrid_rerank"], seed=7)
    dev_ids = set(dev["dataset"]["query_ids"])
    test_ids = set(test["dataset"]["query_ids"])
    assert dev_ids.isdisjoint(test_ids)
    assert dev_ids | test_ids == {
        "zh-vib-lexical", "zh-belt-paraphrase", "zh-current-lexical", "en-code", "en-load-paraphrase",
        "zh-vib-paraphrase", "zh-temp-lexical", "zh-belt-lexical", "zh-motor-paraphrase", "en-vib-lexical",
    }
    assert "en-code" in dev_ids and "en-vib-lexical" in test_ids
    assert dev["scores_are_model_results"] is False
    assert test["scores_are_model_results"] is False
    assert test["model_id"] == "fake-hash-v1"
    assert test["config_sha256"] == content_hash(knob_document(frozen))
    assert test["frozen_config_sha256"] == content_hash(frozen)
    assert test["config_matches_frozen"] is True
    assert test["config"]["rrf_k"] == 60
    assert test["config"]["fused_top_n"] == 20
    assert test["config"]["rerank_top_k"] == 10
    bm25 = {row["id"]: row for row in test["modes"]["bm25"]["queries"]}
    assert bm25["en-vib-lexical"]["rank"] == 1
    assert all(row["rank"] is None for row in bm25.values() if row["kind"] == "paraphrase_no_overlap")
    dev_bm25 = {row["id"]: row for row in dev["modes"]["bm25"]["queries"]}
    assert dev_bm25["en-code"]["rank"] == 1
    reranked = {row["id"]: row for row in dev["modes"]["hybrid_rerank"]["queries"]}
    assert reranked["en-code"]["retrieved_ids"][0] == "CHILLER-DELTAT-01"
    tuned = run_eval(tmp_path / "tune", split="dev", embedder="fake", rrf_k=10, fused_top_n=5,
                     rerank_top_k=3, modes=["hybrid"], seed=7)
    assert tuned["config_matches_frozen"] is False
    assert tuned["config"]["rrf_k"] == 10
    assert tuned["frozen_config_sha256"] == test["frozen_config_sha256"]
    with pytest.raises(SystemExit):
        resolve_config("test", None, None, 10, None, None)
    metrics = summarise([1, None], [2.0, 4.0])
    assert metrics["recall@1"] == pytest.approx(0.5)
    assert metrics["mrr"] == pytest.approx(0.5)
    dumped = json.dumps(test)
    assert "DEEPSEEK_API_KEY" not in dumped


def test_importing_a_manual_after_the_index_makes_dense_search_stale(tmp_path):
    store = Store(tmp_path / "business.db")
    settings = Settings(data_dir=tmp_path, retriever="dense", embedder="fake")
    retriever = ManualRetriever(settings, store)
    retriever.build_index()
    store.import_fixture(json.loads(ENGLISH_FIXTURE.read_text(encoding="utf-8")))
    with pytest.raises(IndexNotReady, match="manual_index_stale"):
        retriever.search("泵振动升高", "P-101", 3)


def test_mcp_hybrid_search_returns_chunk_ids(tmp_path, monkeypatch):
    store = Store(tmp_path / "business.db")
    settings = Settings(data_dir=tmp_path, retriever="hybrid", embedder="fake", rrf_k=60)
    ManualRetriever(settings, store).build_index()
    monkeypatch.setenv("MAINT_BUSINESS_DB", str(store.path))
    monkeypatch.setenv("MAINT_DEVICE_ID", "P-101")
    monkeypatch.setenv("RETRIEVER", "hybrid")
    monkeypatch.setenv("EMBEDDER", "fake")
    monkeypatch.setenv("RRF_K", "60")
    server._SESSION = None
    try:
        payload = json.loads(server.run_tool("search_manual", {"query": "泵振动升高", "top_k": 3}))
    finally:
        server._SESSION = None
    assert payload["ok"] is True
    assert payload["retrieval"] == "RRF k=60 bm25+dense"
    assert any(hit["id"] == "PUMP-VIB-01" and "score" in hit for hit in payload["hits"])
    forwarded = _retrieval_env(settings)
    assert forwarded["EMBEDDER"] == "fake"
    assert "DEEPSEEK_API_KEY" not in forwarded


def test_inprocess_hybrid_rerank_still_reaches_approval(tmp_path):
    settings = Settings(data_dir=tmp_path, retriever="hybrid_rerank", embedder="fake")
    service = AgentService(settings, ScriptedModel())
    try:
        service.retriever.build_index()
        run = service.diagnose(alarm(event_id="retrieval-001"))
        assert run["status"] == "awaiting_approval"
        assert "PUMP-VIB-01" in run["proposal"]["evidence_ids"]
    finally:
        service.close()
