from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from react_agent.config import Settings
from react_agent.models import (
    AlarmEvent,
    Approval,
    ConflictError,
    MissingModelConfig,
    ToolInputError,
)
from react_agent.service import AgentService
from react_agent.store import Store, content_hash
from react_agent.tools import execute_tool
from tests.fakes import ScriptedModel, calls, draft


def alarm(**overrides):
    return AlarmEvent(**{"event_id": "test-001", "device_id": "P-101", "message": "循环泵振动升高", **overrides})


@pytest.fixture
def service(tmp_path):
    obj = AgentService(Settings(data_dir=tmp_path), ScriptedModel())
    yield obj
    obj.close()


def decision(run, approved=True, **overrides):
    return Approval(**{"approved": approved, "proposal_sha256": content_hash(run["proposal"]), **overrides})


def new_orders(service):
    return [o for o in service.store.orders() if o.get("source_run")]


@pytest.mark.parametrize("device_id,query,expected", [
    ("P-101", "泵振动轴承", "PUMP-VIB-01"),
    ("P-101", "温升温度", "PUMP-TEMP-02"),
    ("M-201", "电机过热", "MOTOR-HEAT-01"),
    ("C-301", "输送带打滑", "BELT-SLIP-01"),
])
def test_chinese_retrieval_respects_device_scope(tmp_path, device_id, query, expected):
    store = Store(tmp_path / "business.db")
    hits = store.search(query, device_id)
    assert expected in [hit["id"] for hit in hits]
    assert all(hit["device_type"] in (store.device(device_id)["type"], "general") for hit in hits)


def test_query_syntax_cannot_change_sql_or_fts_structure(tmp_path):
    store = Store(tmp_path / "business.db")
    store.search('" OR *; DROP TABLE devices; --', "P-101")
    assert len(store.devices()) == 3
    assert store.search("zznotawordzz", "P-101") == []


@pytest.mark.parametrize("name,args,patch", [
    ("query_device", {"device_id": "M-201"}, {}),
    ("shell_exec", {"command": "anything"}, {}),
    ("draft_work_order", draft(evidence_ids=["MADE-UP-CITATION"]), {"device_read": True, "history_read": True}),
    ("draft_work_order", draft(), {}),
    ("draft_work_order", draft(priority="urgent-invalid"), {}),
])
def test_tool_contract_rejects_invalid_or_unsupported_actions(tmp_path, name, args, patch):
    store = Store(tmp_path / "business.db")
    state = {"alarm": alarm().model_dump(), "retrieved_ids": ["PUMP-VIB-01"], **patch}
    with pytest.raises(ToolInputError):
        execute_tool(name, args, state, store)
    assert not [o for o in store.orders() if o.get("source_run")]


def test_write_occurs_only_after_approval_and_is_idempotent(service):
    run = service.diagnose(alarm())
    assert run["status"] == "awaiting_approval"
    assert new_orders(service) == []
    completed = service.decide(run["id"], decision(run))
    assert completed["status"] == "completed"
    assert completed["report"]["execution_mode"] == "scripted_test"
    assert len(new_orders(service)) == 1
    again = service.decide(run["id"], decision(run))
    assert again["report"]["order"]["id"] == completed["report"]["order"]["id"]
    assert len(new_orders(service)) == 1
    assert service.model.calls == 2


def test_restart_resumes_pending_review_without_another_model_call(tmp_path):
    original = AgentService(Settings(data_dir=tmp_path), ScriptedModel())
    run = original.diagnose(alarm())
    original.close()
    restored = AgentService(Settings(data_dir=tmp_path), ScriptedModel(responses=[]))
    try:
        done = restored.decide(run["id"], decision(run))
        assert done["status"] == "completed"
        assert len(new_orders(restored)) == 1
        assert restored.model.calls == 0
    finally:
        restored.close()


def test_rejection_never_writes_order(service):
    run = service.diagnose(alarm())
    rejected = service.decide(run["id"], decision(run, False))
    assert rejected["status"] == "rejected"
    assert service.decide(run["id"], decision(run, False))["status"] == "rejected"
    with pytest.raises(ConflictError):
        service.decide(run["id"], decision(run, True))
    assert new_orders(service) == []


def test_stale_proposal_does_not_consume_review(service):
    run = service.diagnose(alarm())
    with pytest.raises(ConflictError):
        service.decide(run["id"], decision(run, proposal_sha256="0" * 64))
    assert service.store.run(run["id"])["status"] == "awaiting_approval"
    assert new_orders(service) == []


def test_repeated_alarm_does_not_call_model_again(service):
    first = service.diagnose(alarm())
    assert service.diagnose(alarm())["id"] == first["id"]
    with pytest.raises(ConflictError):
        service.diagnose(alarm(message="内容不同但事件号相同"))
    assert service.model.calls == 2


def test_no_evidence_response_is_information_request_not_success(tmp_path):
    obj = AgentService(Settings(data_dir=tmp_path), ScriptedModel([AIMessage(content="请补充传感器和告警信息。")]))
    try:
        run = obj.diagnose(alarm())
        assert run["status"] == "needs_information"
        assert run["proposal"] is None
        assert new_orders(obj) == []
    finally:
        obj.close()


def test_unexpected_execution_error_remains_failure(tmp_path):
    obj = AgentService(Settings(data_dir=tmp_path), ScriptedModel([RuntimeError("test failure")]))
    try:
        with pytest.raises(RuntimeError):
            obj.diagnose(alarm())
        with obj.store.connection() as conn:
            row = conn.execute("SELECT status,error_code FROM runs").fetchone()
        assert dict(row) == {"status": "failed", "error_code": "RuntimeError"}
        assert new_orders(obj) == []
    finally:
        obj.close()


def test_missing_key_has_no_scripted_fallback(tmp_path):
    obj = AgentService(Settings(data_dir=tmp_path, api_key=""))
    try:
        with pytest.raises(MissingModelConfig):
            obj.diagnose(alarm())
        assert new_orders(obj) == []
    finally:
        obj.close()


def test_round_limit_preserves_failure(tmp_path):
    repeated = [calls(("query_device", {"device_id": "P-101"})) for _ in range(2)]
    obj = AgentService(Settings(data_dir=tmp_path, max_rounds=2), ScriptedModel(repeated))
    try:
        run = obj.diagnose(alarm())
        assert run["status"] == "failed"
        assert run["error_code"] == "agent_round_limit"
        assert run["report"]["usage"] is None
        assert new_orders(obj) == []
    finally:
        obj.close()


def test_database_write_replay_does_not_duplicate_order(tmp_path):
    store = Store(tmp_path / "business.db")
    one = store.create_order("replayed-run", "P-101", draft())
    two = store.create_order("replayed-run", "P-101", draft())
    assert one["id"] == two["id"]
    assert len([o for o in store.orders() if o.get("source_run")]) == 1


def test_config_repr_hides_key():
    assert "not-a-real-secret" not in repr(Settings(data_dir=Path("runtime"), api_key="not-a-real-secret"))
