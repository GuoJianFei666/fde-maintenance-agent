import json
from pathlib import Path

from langchain_core.messages import AIMessage

from evals.assetopsbench.convert import convert, load_jsonl
from evals.assetopsbench.metrics import order_correct, score_case, summarise
from evals.assetopsbench.official_sample import (
    import_official_sample,
    load_committed,
    scenario3_inputs,
    verify_committed_files,
    work_order_counts,
)
from evals.assetopsbench.run import run_eval
from react_agent.store import Store

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
    assert record["dataset"]["official_context"] == {"lookup": 6, "partial": 4, "absent": 119}
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


def test_official_sample_answers_lookups_and_leaves_drafts_unchanged(tmp_path):
    verify_committed_files()
    assert MANIFEST["draft_ids"] == [416, 417, 419]
    assert MANIFEST["official_sample_supports_draft"] == []
    assert MANIFEST["official_context"]["lookup"] == [1, 2, 3, 4, 5, 47]
    assert MANIFEST["official_context"]["partial"] == [9, 12, 104, 603]
    by_id = {case["upstream_id"]: case for case in CASES}
    for upstream_id in (1, 2, 3, 4, 5, 47, 9, 12, 104, 603):
        assert by_id[upstream_id]["expected_status"] == "needs_information"
        assert "draft_work_order" in by_id[upstream_id]["forbidden_tools"]
        assert by_id[upstream_id]["official_context"]["official_sample_supports_draft"] is False
    assert by_id[5]["split"] == "dev"
    assert by_id[12]["split"] == "test"
    sample = load_committed()
    counts = work_order_counts(sample["work_orders"])
    official = ROOT / "evals" / "assetopsbench" / "fixtures" / "official"
    assert counts["main_site"] == int((official / "scenario_1_groundtruth.txt").read_text().strip())
    assert counts["main_site_corrective"] == int((official / "scenario_2_groundtruth.txt").read_text().strip())
    facts = scenario3_inputs(sample, {"coverage": "excerpt"})
    assert facts == {
        "work_order": "1000045",
        "asset": "Chiller 6",
        "sensor": "Chiller 6 Condenser Water Flow",
        "sensor_matches": ["Chiller 6 Condenser Water Flow"],
    }
    published = json.loads((official / "scenario_3_groundtruth.txt").read_text(encoding="utf-8"))
    assert published["anomalies_found"] is True
    assert "anomalies_found" not in facts
    store = Store(tmp_path / "sample.sqlite")
    before = store.corpus_sha256
    store.import_fixture(FIXTURE)
    imported = import_official_sample(store)
    assert store.corpus_sha256 == before
    assert imported["telemetry_coverage"] == "excerpt"
    device = store.device("CH-6")["official_sample"]
    assert device["profile"]["siteid"] == "MAIN"
    assert device["telemetry"]["loaded_rows"] == 2
    assert device["telemetry"]["full_file"]["loaded"] is False
    assert {row["siteid"] for row in device["registry"]} == {"MAIN", "NORTH"}
    chillers = [row["assetnum"] for row in device["registry"] if row["assettype"] == "CHILLER"]
    assert chillers == ["Chiller 6"]
    assert store.orders("CH-6")[0]["id"] == "WO-1000045"
    official_orders = [order for order in store.orders() if order.get("data_kind") == "official_sample"]
    assert {order["device_id"] for order in official_orders} == {"AHU2", "CH-6", "PUMP3"}
    for query, evidence in (
        ("unnamed anomaly inspection", "CHILLER-ANOM-01"),
        ("cooling load upper bound", "CHILLER-LOAD-01"),
        ("RUL0014 delta temperature", "CHILLER-DELTAT-01"),
    ):
        assert evidence in [hit["id"] for hit in store.search(query, "CH-6", 3)]
    assert store.search("泵振动升高", "P-101", 3)[0]["id"] == "PUMP-VIB-01"


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
