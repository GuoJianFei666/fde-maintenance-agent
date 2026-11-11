from pathlib import Path

import pytest

from evals.maintnorm.baselines import TABLE_7
from evals.maintnorm.evaluate import assert_prompt_policy, evaluate
from evals.maintnorm.metrics import parse_norm, rates, score_tokens
from react_agent.config import Settings
from react_agent.models import MaintenanceText
from react_agent.normalise import apply_rules, prompt_document, rule_record
from react_agent.service import AgentService
from tests.fakes import ScriptedModel, calls

FIXTURE = Path(__file__).resolve().parents[1] / "evals" / "maintnorm" / "fixtures" / "mini"
BASELINES = Path(__file__).resolve().parents[1] / "evals" / "maintnorm" / "BASELINES.md"


def test_word_level_error_reduction_matches_the_paper_definition():
    counts = score_tokens([
        ("eng", "engine", "engine"),
        ("oil", "oil", "oils"),
        ("repl", "replace", "repaired"),
    ])
    assert counts == {"tp": 1, "fp": 1, "fn": 1}
    assert rates(counts)["err"] == 0
    unchanged = score_tokens([("pump", "pump", "pump")])
    assert unchanged == {"tp": 0, "fp": 0, "fn": 0}
    assert rates(unchanged)["err"] == 0


def test_rule_baseline_and_scripted_oracle_on_the_fixture():
    rules = evaluate(FIXTURE, subset="combined", split="test", method="rules", fixture=True, model=None, seed=7, limit=0)
    oracle = evaluate(FIXTURE, subset="combined", split="test", method="scripted", fixture=True, model=None, seed=7, limit=0)
    lai = evaluate(FIXTURE, subset="combined", split="test", method="lai", fixture=True, model=None, seed=7, limit=0)
    mfr = evaluate(FIXTURE, subset="combined", split="val", method="mfr", fixture=True, model=None, seed=11, limit=0)
    assert rules["metrics"]["err"] == 1
    assert oracle["metrics"]["err"] == 1
    assert lai["metrics"]["err"] == 0
    assert lai["metrics"]["fn"] > 0
    assert mfr["split"] == "val"
    assert rules["scores_are_model_results"] is False
    assert rules["dataset"]["language"] == "en"
    assert rules["git_commit"]
    assert rules["seed"] == 7
    with pytest.raises(SystemExit):
        evaluate(FIXTURE, subset="combined", split="test", method="scripted", fixture=False, model=None, seed=7, limit=0)


def test_prompt_must_be_frozen_before_the_test_split(monkeypatch):
    document, _raw = prompt_document()
    assert document["frozen"] is True
    sentences = parse_norm("pump\tpump\n")
    assert_prompt_policy("test", sentences)

    def unfrozen():
        changed = dict(document)
        changed["frozen"] = False
        return changed, "{}"

    monkeypatch.setattr("evals.maintnorm.evaluate.prompt_document", unfrozen)
    with pytest.raises(SystemExit):
        assert_prompt_policy("test", sentences)


def test_paper_table_is_cited_and_our_column_is_blank():
    combined = next(row for row in TABLE_7["MaintNorm"] if row[0] == "A+B+C")
    assert combined[4] == 95.8
    text = BASELINES.read_text(encoding="utf-8")
    assert "95.8" in text
    assert "待运行" in text
    assert "https://aclanthology.org/2024.wnut-1.7/" in text
    assert "Table 7" in text or "表 7" in text


def test_rules_do_not_change_the_existing_clean_intake_text(tmp_path):
    assert apply_rules("hydraulic") == "hydraulic"
    assert rule_record("hydraulic pump leaking oil")["changed"] is False
    service = AgentService(Settings(data_dir=tmp_path, text_normaliser="rules"), ScriptedModel([calls((
        "submit_extraction", {"entities": [
            {"start": 0, "end": 2, "type": "PhysicalObject"},
            {"start": 1, "end": 2, "type": "PhysicalObject"},
            {"start": 2, "end": 3, "type": "Process"},
            {"start": 3, "end": 4, "type": "PhysicalObject"},
        ]}))]))
    try:
        run = service.submit_text(MaintenanceText(event_id="norm-clean", device_id="P-101",
                                                   message="hydraulic pump leaking oil"))
        assert run["status"] == "awaiting_approval"
        assert run["report"]["normalisation"]["changed"] is False
        assert run["report"]["text_extraction"]["entities"][0]["text"] == "hydraulic pump"
        assert service.model.calls == 1
    finally:
        service.close()


def test_llm_normaliser_runs_before_extraction(tmp_path):
    normal = calls(("submit_normalisation", {"tokens": [
        {"raw": "REPL", "norm": "replace"}, {"raw": "PUMP", "norm": "pump"}]}))
    extracted = calls(("submit_extraction", {"entities": [
        {"start": 0, "end": 1, "type": "Activity"},
        {"start": 1, "end": 2, "type": "PhysicalObject"},
    ]}))
    service = AgentService(Settings(data_dir=tmp_path, text_normaliser="llm"), ScriptedModel([normal, extracted]))
    try:
        run = service.submit_text(MaintenanceText(event_id="norm-llm", device_id="P-101", message="REPL PUMP"))
        assert run["report"]["normalisation"]["text"] == "replace pump"
        assert run["report"]["text_extraction"]["tokens"] == ["replace", "pump"]
        assert service.model.calls == 2
    finally:
        service.close()


def test_fixture_parser_round_trip():
    sentences = parse_norm((FIXTURE / "test.norm").read_text(encoding="utf-8"))
    assert sentences[0][0] == ("u/s", "unserviceable")
    assert sentences[-1][-1] == ("pump", "pump")
