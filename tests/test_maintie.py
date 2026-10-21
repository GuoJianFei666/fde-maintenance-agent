import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from react_agent.api import create_app
from react_agent.config import Settings
from react_agent.extraction import extract_text
from react_agent.maintie import GoldRecord, MaintIEIndex, load_corpus, split_for, text_fingerprint
from react_agent.models import Approval, ConflictError, MaintenanceText, ModelCallError
from react_agent.service import AgentService
from react_agent.store import content_hash
from tests.fakes import ScriptedModel, calls


def extraction_response():
    # Authored test fixture, not a claimed model observation.
    return calls(("submit_extraction", {"entities": [
        {"start": 0, "end": 2, "type": "PhysicalObject"},
        {"start": 1, "end": 2, "type": "PhysicalObject"},
        {"start": 2, "end": 3, "type": "Process"},
        {"start": 3, "end": 4, "type": "PhysicalObject"},
    ]}))


def request(**overrides):
    return MaintenanceText(**{"event_id": "maintie-test-001", "device_id": "P-101",
                              "message": "hydraulic pump leaking oil", **overrides})


def test_pinned_raw_corpus_validates_and_holdout_is_not_indexed(tmp_path):
    manifest, rows = load_corpus()
    assert len(rows) == manifest["record_count"] == 1076
    index = MaintIEIndex(tmp_path / "cases.db")
    with index.connection() as conn:
        assert conn.execute("SELECT count(*) FROM cases").fetchone()[0] == 1076
        assert conn.execute("""SELECT count(*) FROM case_fts f JOIN cases c ON f.case_id=c.id
                            WHERE c.split != 'reference'""").fetchone()[0] == 0
    for row in index.evaluation_records()[:20]:
        hits = index.search(row["body"], 5)
        assert all(hit["split"] == "reference" for hit in hits)
        assert all(hit["text_sha256"] != row["text_sha256"] for hit in hits)
        assert all("entities" not in hit and "relations" not in hit for hit in hits)


def test_same_normalized_description_stays_in_one_split():
    variants = ["<id> Pump LEAKING", "<num> pump leaking", "pump leaking"]
    assert len({text_fingerprint(text) for text in variants}) == 1
    assert len({split_for(text) for text in variants}) == 1


def test_references_are_lexical_bilingual_and_not_device_histories(tmp_path):
    index = MaintIEIndex(tmp_path / "cases.db")
    hits = index.search("泵漏油")
    assert hits and any("pump" in row["body"] for row in hits)
    assert all(row["raw_sha256"] == index.manifest["files"]["gold_release.json"]["sha256"] for row in hits)
    assert index.search("zznorecord999") == []
    index.search('" OR *; DROP TABLE cases; --')
    assert index.metadata()["record_count"] == 1076
    reference = next(index.record(case_id) for case_id in index.rows
                     if index.record(case_id)["split"] == "reference")
    assert reference["id"] not in [row["id"] for row in index.search(reference["body"], 5)]


def test_corrupt_packaged_data_is_rejected_before_import(tmp_path, monkeypatch):
    from react_agent import maintie

    source = maintie.files("react_agent").joinpath("data/maintie")
    target = tmp_path / "data" / "maintie"
    target.mkdir(parents=True)
    for filename in ("manifest.json", "gold_release.json", "LICENSE.md", "README.upstream.md"):
        (target / filename).write_bytes(source.joinpath(filename).read_bytes())
    (target / "gold_release.json").write_bytes(b"[]")
    monkeypatch.setattr(maintie, "files", lambda _: tmp_path)
    with pytest.raises(ValueError, match="maintie_file_hash_mismatch"):
        load_corpus()


@pytest.mark.parametrize("entity,relations", [
    ({"start": 0, "end": 5, "type": "PhysicalObject"}, []),
    ({"start": 0, "end": 1, "type": "Unknown"}, []),
    ({"start": 0, "end": 1, "type": "PhysicalObject"}, [{"head": 0, "tail": 2, "type": "hasPart"}]),
])
def test_invalid_source_annotations_do_not_become_accepted_records(entity, relations):
    with pytest.raises(ValidationError):
        GoldRecord.model_validate({"text": "pump leaking", "tokens": ["pump", "leaking"],
                                   "entities": [entity], "relations": relations})


@pytest.mark.parametrize("entities,error", [
    ([{"start": 0, "end": 10, "type": "PhysicalObject"}], "extraction_span_out_of_bounds"),
    ([{"start": 0, "end": 1, "type": "Cause"}], "invalid_extraction_schema"),
    ([{"start": "0", "end": 1, "type": "PhysicalObject"}], "invalid_extraction_schema"),
    ([{"start": 0, "end": 1, "type": "PhysicalObject"}] * 2, "duplicate_extraction_span"),
])
def test_invalid_model_spans_fail_explicitly(entities, error):
    model = ScriptedModel([calls(("submit_extraction", {"entities": entities}))])
    with pytest.raises(ModelCallError, match=error):
        extract_text(model, "pump leaking")


def test_placeholder_is_not_treated_as_known_asset():
    model = ScriptedModel([calls(("submit_extraction", {"entities": [
        {"start": 0, "end": 1, "type": "PhysicalObject"}]}))])
    with pytest.raises(ModelCallError, match="extraction_placeholder_not_entity"):
        extract_text(model, "<id> leaking")


def test_text_intake_preserves_case_provenance_and_approval_after_restart(tmp_path):
    service = AgentService(Settings(data_dir=tmp_path), ScriptedModel([extraction_response()]))
    run = service.submit_text(request())
    assert run["status"] == "awaiting_approval"
    assert service.submit_text(request())["id"] == run["id"]
    assert service.model.calls == 1
    assert run["report"]["text_extraction"]["entities"][0]["text"] == "hydraulic pump"
    assert run["report"]["evidence_kind"] == "case_reference_not_sop"
    assert run["report"]["evidence"] and all(row["split"] == "reference" for row in run["report"]["evidence"])
    assert service.store.orders("P-101") and not any(order.get("source_run") for order in service.store.orders())
    service.close()
    restored = AgentService(Settings(data_dir=tmp_path), ScriptedModel([]))
    try:
        with pytest.raises(ConflictError, match="stale_or_missing_proposal"):
            restored.decide(run["id"], Approval(approved=True, proposal_sha256="0" * 64))
        decision = Approval(approved=True, proposal_sha256=content_hash(run["proposal"]))
        done = restored.decide(run["id"], decision)
        again = restored.decide(run["id"], decision)
        assert done["status"] == "completed"
        assert done["report"]["order"]["id"] == again["report"]["order"]["id"]
        assert len([order for order in restored.store.orders() if order.get("source_run")]) == 1
        assert done["report"]["order"]["data_kind"] == "public_corpus_demo_intake"
        assert restored.model.calls == 0
        markdown = restored.report_markdown(run["id"])
        assert "MAINTIE-GOLD-" in markdown and "原文实体抽取" in markdown
        assert "适用操作规程" in markdown
    finally:
        restored.close()


def test_rejected_text_and_incomplete_text_do_not_create_orders(tmp_path):
    model = ScriptedModel([extraction_response(), calls(("submit_extraction", {"entities": []}))])
    service = AgentService(Settings(data_dir=tmp_path), model)
    try:
        run = service.submit_text(request())
        rejected = service.decide(run["id"], Approval(approved=False, proposal_sha256=content_hash(run["proposal"])))
        assert rejected["status"] == "rejected"
        missing = service.submit_text(request(event_id="empty", message="please help"))
        assert missing["status"] == "needs_information" and missing["proposal"] is None
        assert not [order for order in service.store.orders() if order.get("source_run")]
    finally:
        service.close()


def test_maintie_endpoints_and_invalid_source_mapping(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), ScriptedModel([extraction_response()]))
    with TestClient(app) as client:
        assert client.get("/api/datasets/maintie").json()["record_count"] == 1076
        assert client.get("/api/cases/MAINTIE-GOLD-0000").status_code == 200
        assert client.get("/api/cases/not-a-record").status_code == 404
        assert client.get("/api/cases/search", params={"q": "pump leaking"}).json()
        mismatch = request(source_record_id="MAINTIE-GOLD-0000").model_dump()
        assert client.post("/api/maintenance-texts", json=mismatch).status_code == 409
        run = client.post("/api/maintenance-texts", json=request().model_dump()).json()
        assert run["status"] == "awaiting_approval"
        assert client.post("/api/maintenance-texts", json=request(message="different text").model_dump()).status_code == 409
        result = client.get(f"/api/runs/{run['id']}/trace").json()
        assert {"extract_text", "retrieve_cases", "draft_text_intake"} <= {item["node"] for item in result}


def test_extractor_never_receives_gold_annotations():
    class InspectModel(ScriptedModel):
        def invoke(self, messages, tools):
            payload = json.loads(messages[-1].content)
            assert set(payload) == {"text", "tokens"}
            assert "entities" not in payload and "relations" not in payload
            return super().invoke(messages, tools)

    result = extract_text(InspectModel([extraction_response()]), "hydraulic pump leaking oil")
    assert len(result["entities"]) == 4


def test_too_many_tokens_is_a_request_error_before_model_call(tmp_path):
    model = ScriptedModel([])
    with TestClient(create_app(Settings(data_dir=tmp_path), model)) as client:
        payload = {"event_id": "overlong", "device_id": "P-101", "message": "泵" * 161}
        response = client.post("/api/maintenance-texts", json=payload)
        assert response.status_code == 422
        assert model.calls == 0


def test_invalid_extraction_is_recorded_as_failed_without_a_draft(tmp_path):
    model = ScriptedModel([calls(("submit_extraction", {"entities": [
        {"start": 0, "end": 999, "type": "PhysicalObject"}]}))])
    service = AgentService(Settings(data_dir=tmp_path), model)
    try:
        with pytest.raises(ModelCallError, match="extraction_span_out_of_bounds"):
            service.submit_text(request())
        with service.store.connection() as conn:
            row = conn.execute("SELECT status,proposal,error_code FROM runs").fetchone()
        assert dict(row) == {"status": "failed", "proposal": None, "error_code": "ModelCallError"}
        with service.store.connection() as conn:
            run_id = conn.execute("SELECT id FROM runs").fetchone()["id"]
        trace = service.store.traces(run_id)
        assert len([item for item in trace if item["node"] == "model"]) == 1
        assert trace[-1]["data"]["category"] == "extraction_span_out_of_bounds"
        assert not any(order.get("source_run") for order in service.store.orders())
    finally:
        service.close()
