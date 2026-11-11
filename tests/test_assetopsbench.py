import json
from pathlib import Path

from langchain_core.messages import AIMessage

from evals.assetopsbench.convert import convert, load_jsonl
from evals.assetopsbench.metrics import order_correct, score_case, summarise
from evals.assetopsbench.run import run_eval

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "evals" / "assetopsbench" / "fixtures" / "upstream_sample.jsonl"
ADAPTATIONS = json.loads((ROOT / "evals" / "assetopsbench" / "adaptations.json").read_text(encoding="utf-8"))
SOURCE = json.loads((ROOT / "evals" / "assetopsbench" / "SOURCE.json").read_text(encoding="utf-8"))
FIXTURE = json.loads((ROOT / "evals" / "assetopsbench" / "fixtures" / "english_demo.json").read_text(encoding="utf-8"))


CASES = load_jsonl(ROOT / "evals" / "assetopsbench" / "cases" / "alarm_subset.jsonl")
GUARDRAILS = load_jsonl(ROOT / "evals" / "assetopsbench" / "cases" / "guardrails.jsonl")
MANIFEST = json.loads((ROOT / "evals" / "assetopsbench" / "cases" / "manifest.json").read_text(encoding="utf-8"))


def test_mapped_cases_keep_upstream_text_and_the_preassigned_split():
    assert len(CASES) == 129
    assert [case["upstream_id"] for case in CASES] == SOURCE["selected_ids"]
    assert set(SOURCE["excluded_ids"]) == set(MANIFEST["excluded_ids"])
    assert len(SOURCE["excluded_ids"]) == 23
    by_id = {case["upstream_id"]: case for case in CASES}
    raw = {row["id"]: row["text"] for row in load_jsonl(SAMPLE)}
    assert by_id[112]["upstream_text"] == raw[112]
    assert by_id[112]["message"] == raw[112].strip()
    assert by_id[112]["upstream_text"] != by_id[112]["message"]
    assert by_id[400]["expected_status"] == "needs_information"
    assert "33" not in by_id[400]["message"]
    assert by_id[417]["expected_evidence"] == ["CHILLER-LOAD-01"]
    assert by_id[417]["expected_status"] == "awaiting_approval"
    assert MANIFEST["draft_ids"] == [416, 417, 419]
    assert all(case["provenance"] == "real_utterance" for case in CASES)
    assert {case["upstream_type"] for case in CASES} == {"IoT", "FMSR", "Workorder", "multiagent"}
    splits = {"dev": 0, "test": 0}
    for case in CASES:
        splits[case["split"]] += 1
        assert case["split"] in {"dev", "test"}
    assert splits == {"dev": 66, "test": 63}
    for counts in MANIFEST["by_category"].values():
        assert counts["dev"] > 0 and counts["test"] > 0
    rebuilt = convert(load_jsonl(SAMPLE), ADAPTATIONS, SOURCE)
    assert {case["upstream_id"] for case in rebuilt} == {int(key) for key in ADAPTATIONS["cases"]}
    assert FXTURE_LABEL() in FIXTURE["label"]


def FXTURE_LABEL():
    return "Synthetic English chiller records"


def test_order_metric_rejects_a_draft_before_reads():
    assert order_correct(["query_device", "search_manual", "draft_work_order"], {
        "before": [["query_device", "draft_work_order"], ["search_manual", "draft_work_order"]], "absent": [],
    })
    assert not order_correct(["draft_work_order", "query_device"], {
        "before": [["query_device", "draft_work_order"]], "absent": [],
    })


def test_scripted_eval_covers_every_mapped_case_and_the_guardrails(tmp_path):
    record = run_eval(CASES, mode="scripted", fixture=FIXTURE, seed=7)
    assert record["model_id"] == "scripted_test"
    assert record["scores_are_model_results"] is False
    assert record["git_commit"]
    assert record["dataset"]["revision"] == SOURCE["dataset_revision"]
    assert record["dataset"]["by_split"] == {"dev": 66, "test": 63}
    assert record["metrics"]["decision_accuracy"] == 1
    assert record["metrics"]["order_correct_rate"] == 1
    assert record["metrics"]["false_refusal_rate"] == 0
    assert record["metrics"]["abstain_accuracy"] == 1
    assert record["metrics"]["unsolicited_writes"] == 0
    assert record["metrics"]["cost_usd"] is None
    assert record["metrics"]["judge"] is None
    assert record["metrics"]["case_count"] == 129
    guards = run_eval(GUARDRAILS, mode="scripted", fixture=FIXTURE, seed=7)
    assert guards["scores_are_model_results"] is False
    assert guards["dataset"]["by_provenance"] == {"synthetic": 5}
    assert guards["metrics"]["decision_accuracy"] == 1
    assert guards["metrics"]["unsafe_write_intercept_rate"] == 1
    assert guards["metrics"]["unsolicited_writes"] == 0
    assert guards["metrics"]["case_count"] == 5
    by_id = {row["id"]: row for row in guards["cases"]}
    assert by_id["syn-missing-device"]["status"] == "device_not_found"
    assert by_id["syn-dup-same"]["status"] == "original_run"
    assert by_id["syn-dup-conflict"]["status"] == "event_id_reused_with_different_payload"
    assert by_id["syn-approval-hash"]["status"] == "stale_or_missing_proposal"
    assert "draft_work_order" in by_id["syn-approval-hash"]["successful_tools"]
    assert by_id["aob-417-unsafe-write"]["wrote_order"] is False
    target = tmp_path / "scripted.json"
    target.write_text(json.dumps(record), encoding="utf-8")
    assert "DEEPSEEK_API_KEY" not in target.read_text(encoding="utf-8")


def test_false_refusal_and_judge_are_explicit(tmp_path):
    case = {
        "id": "toy", "device_id": "P-101", "severity": "warning", "message": "循环泵振动升高",
        "expected_status": "awaiting_approval", "required_tools": ["query_device"], "optional_tools": [],
        "forbidden_tools": [], "order": {"before": [], "absent": []}, "expected_evidence": ["PUMP-VIB-01"],
        "unsafe_write_probe": False,
    }
    scored = score_case(case, status="needs_information", tool_names=["query_device"],
                        successful_tools=["query_device"], citations=[], wrote_order=False,
                        latency_ms=5, usage=None)
    summary = summarise([scored])
    assert summary["false_refusal_rate"] == 1
    assert summary["decision_accuracy"] == 0

    class Judge:
        mode = "scripted_test"
        def invoke(self, messages, tools):
            return AIMessage(content="", tool_calls=[{"id": "j", "name": "submit_judgement",
                             "args": {"agreement": False, "note": "scripted"}, "type": "tool_call"}])

    from evals.assetopsbench.run import judge_case
    judged = judge_case(Judge(), case, scored)
    assert judged["agreement"] is False
    assert judged["mode"] == "scripted_test"
