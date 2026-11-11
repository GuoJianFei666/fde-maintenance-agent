import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from react_agent.config import Settings
from react_agent.models import AlarmEvent
from react_agent.service import AgentService
from react_agent.store import Store
from react_agent.tools import execute_tool, patch_from_result
from tests.fakes import ScriptedModel, draft
from tests.test_workflow import alarm, decision, new_orders


def test_public_patch_matches_execute_tool(tmp_path):
    store = Store(tmp_path / "business.db")
    state = {"alarm": alarm().model_dump(), "retrieved_ids": [], "device_read": False, "history_read": False}
    for name, args in (
        ("query_device", {"device_id": "P-101"}),
        ("query_work_orders", {"device_id": "P-101"}),
        ("search_manual", {"query": "泵振动", "top_k": 3}),
    ):
        result, patch = execute_tool(name, args, state, store)
        assert patch_from_result(name, result, state) == patch
        state.update(patch)
    result, patch = execute_tool("draft_work_order", draft(), state, store)
    assert patch == {"proposal": result["proposal"]}
    assert patch_from_result("draft_work_order", result, state) == patch
    assert not [order for order in store.orders() if order.get("source_run")]


def test_mcp_server_draft_cannot_write(tmp_path, monkeypatch):
    from mcp_server import server

    database = tmp_path / "business.db"
    Store(database)
    monkeypatch.setenv("MAINT_BUSINESS_DB", str(database))
    monkeypatch.setenv("MAINT_DEVICE_ID", "P-101")
    server._SESSION = None
    try:
        assert json.loads(server.run_tool("query_device", {"device_id": "M-201"}))["error_code"] == "device_scope_mismatch"
        assert json.loads(server.run_tool("query_device", {"device_id": "P-101"}))["ok"] is True
        blocked = json.loads(server.run_tool("draft_work_order", draft()))
        assert blocked["ok"] is False
        assert blocked["error_code"] == "read_device_and_history_before_drafting"
        assert not [order for order in Store(database).orders() if order.get("source_run")]
    finally:
        server._SESSION = None


def test_stdio_mcp_transport_keeps_approval_and_idempotent_write(tmp_path):
    service = AgentService(Settings(data_dir=tmp_path, tool_transport="mcp"), ScriptedModel())
    try:
        run = service.diagnose(alarm())
        assert run["status"] == "awaiting_approval"
        assert run["report"]["tool_transport"] == "mcp"
        assert new_orders(service) == []
        done = service.decide(run["id"], decision(run))
        again = service.decide(run["id"], decision(run))
        assert done["report"]["order"]["id"] == again["report"]["order"]["id"]
        assert len(new_orders(service)) == 1
    finally:
        service.close()


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_streamable_http_lists_four_tools_and_reads_device(tmp_path):
    from react_agent.mcp_client import McpSession, _http

    database = tmp_path / "business.db"
    Store(database)
    port = _free_port()
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update({"MAINT_BUSINESS_DB": str(database), "MAINT_DEVICE_ID": "P-101",
                "PYTHONPATH": os.pathsep.join([str(root), str(root / "src"), env.get("PYTHONPATH", "")])})
    process = subprocess.Popen(
        [sys.executable, "-m", "mcp_server", "--transport", "streamable-http", "--port", str(port)],
        cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    session = None
    try:
        last_error = None
        for _ in range(40):
            if process.poll() is not None:
                break
            try:
                session = McpSession(lambda port=port: _http(f"http://127.0.0.1:{port}/mcp"))
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
        assert session is not None, last_error
        assert set(session.list_tools()) >= {"query_device", "query_work_orders", "search_manual", "draft_work_order"}
        payload = session.call("query_device", {"device_id": "P-101"})
        assert payload["ok"] is True
        assert payload["device"]["id"] == "P-101"
    finally:
        if session is not None:
            session.close()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_inprocess_transport_remains_the_default(tmp_path):
    service = AgentService(Settings(data_dir=tmp_path), ScriptedModel())
    try:
        run = service.diagnose(AlarmEvent(event_id="local-1", device_id="P-101", message="循环泵振动升高"))
        assert run["report"]["tool_transport"] == "inprocess"
        assert service._tools is None
    finally:
        service.close()
