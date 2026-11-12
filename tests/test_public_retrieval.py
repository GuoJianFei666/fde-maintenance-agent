import json
from pathlib import Path

import pytest

from evals.retrieval.public_corpus import (
    assign_techmanualqa_split,
    convert_techmanualqa,
    convert_techqa,
    load_fixture,
    techqa_split,
)
from evals.retrieval.run import content_hash, knob_document, load_frozen_config
from evals.retrieval.run_public import run_dataset

FIXTURES = Path(__file__).resolve().parents[1] / "evals" / "retrieval" / "fixtures"
LABELS = Path(__file__).resolve().parents[1] / "evals" / "retrieval" / "labels.json"


def test_in_domain_query_set_stays_at_the_original_ten():
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    assert labels["version"] == "manual-retrieval-v2"
    assert len(labels["queries"]) == 10
    assert {item["split"] for item in labels["queries"]} == {"dev", "test"}


def test_public_splits_use_labels_not_scores():
    passages, queries = load_fixture("techmanualqa")
    by_id = {item["id"]: item for item in queries}
    assert by_id["mini_A_Q001"]["split"] == "dev"
    assert by_id["mini_A_Q002"]["split"] == "test"
    assert by_id["mini_U_Q002"]["split"] == "test"
    assert by_id["mini_U_Q002"]["answerable"] is False
    assert all(item["answerable"] or not item["relevant_ids"] for item in queries)
    assert len(passages) == 4
    rows = [json.loads(line) for line in (FIXTURES / "techmanualqa_mini.jsonl").read_text(encoding="utf-8").splitlines()]
    again = assign_techmanualqa_split(rows)
    assert again == {item["id"]: item["split"] for item in queries}
    tech_passages, tech_queries = load_fixture("techqa")
    assert {item["id"] for item in tech_passages} == {"alpha.txt", "beta.txt", "gamma.txt"}
    assert techqa_split("DEV_Q001") == "dev"
    assert techqa_split("TRAIN_Q001") == "test"
    with pytest.raises(ValueError):
        techqa_split("HOLDOUT_Q1")
    broken = [{"id": "TRAIN_Q009", "question": "q", "is_impossible": False,
               "contexts": [{"filename": "missing.txt", "text": "x"}]}]
    with pytest.raises(ValueError):
        convert_techqa(broken, {"other.txt": "text"})
    empty = [{"question_id": "mini_A_Q001", "doc_id": "a.pdf", "question_text": "q",
              "gt_answer_snippet": "", "gt_page_number": "1", "category": "Location/Definition"}]
    with pytest.raises(ValueError):
        convert_techmanualqa(empty)


def test_fixture_retrieval_uses_the_frozen_config(tmp_path):
    frozen = load_frozen_config()
    passages, queries = load_fixture("techqa")
    record = run_dataset(tmp_path, "techqa", passages, queries, split="test", embedder_name="fake", seed=7)
    assert record["scores_are_model_results"] is False
    assert record["config_matches_frozen"] is True
    assert record["config_sha256"] == content_hash(knob_document(frozen))
    assert record["dataset"]["answerable_count"] == 1
    assert record["dataset"]["unanswerable_count"] == 1
    bm25 = {row["id"]: row for row in record["modes"]["bm25"]["queries"]}
    assert bm25["TRAIN_Q001"]["rank"] == 1
    assert bm25["TRAIN_Q002"]["rank"] is None
    assert record["modes"]["bm25"]["metrics"]["query_count"] == 1
    with pytest.raises(SystemExit):
        run_dataset(tmp_path / "blocked", "techqa", passages, queries, split="test",
                    embedder_name="fake", rrf_k=10)
