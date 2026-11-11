"""Synchronous MCP client used by the LangGraph tool node.

The official MCP Python client keeps one stdio process, or one streamable HTTP
session, open across the tool rounds of a run. langchain-mcp-adapters wraps
this same ClientSession; this module calls it directly so the graph can split
the public payload from its state patch.
"""

import asyncio
import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

_ROOT = Path(__file__).resolve().parents[2]


def _pythonpath():
    parts = [str(_ROOT), str(_ROOT / "src")]
    if os.environ.get("PYTHONPATH"):
        parts.append(os.environ["PYTHONPATH"])
    return os.pathsep.join(parts)


def tool_payload(result):
    if getattr(result, "isError", False):
        return {"ok": False, "error_code": "mcp_tool_error"}
    texts = [getattr(block, "text", "") for block in (result.content or [])]
    texts = [text for text in texts if text]
    if not texts:
        return {"ok": False, "error_code": "mcp_empty_tool_result"}
    try:
        payload = json.loads(texts[0])
    except json.JSONDecodeError:
        return {"ok": False, "error_code": "mcp_tool_result_not_json"}
    if not isinstance(payload, dict):
        return {"ok": False, "error_code": "mcp_tool_result_not_object"}
    return payload


class McpSession:
    def __init__(self, opener):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="mcp-tool-session", daemon=True)
        self._ready = threading.Event()
        self._start_error = None
        self._session = None
        self._stop = None
        self._thread.start()
        self._task = asyncio.run_coroutine_threadsafe(self._serve(opener), self._loop)
        if not self._ready.wait(30):
            self.close()
            raise TimeoutError("mcp_session_start_timeout")
        if self._start_error is not None:
            self.close()
            raise self._start_error

    async def _serve(self, opener):
        self._stop = asyncio.Event()
        try:
            async with opener() as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._ready.set()
                    await self._stop.wait()
        except Exception as exc:
            self._start_error = exc
            self._ready.set()
            raise

    def call(self, name, arguments):
        future = asyncio.run_coroutine_threadsafe(self._session.call_tool(name, arguments), self._loop)
        return tool_payload(future.result(timeout=60))

    def list_tools(self):
        future = asyncio.run_coroutine_threadsafe(self._session.list_tools(), self._loop)
        listed = future.result(timeout=30)
        return [tool.name for tool in listed.tools]

    def close(self):
        if self._stop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop.set)
        try:
            self._task.result(timeout=10)
        except Exception:
            pass
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


@asynccontextmanager
async def _stdio(database, device_id):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_server"], cwd=str(_ROOT),
        env={"PYTHONPATH": _pythonpath(), "MAINT_BUSINESS_DB": str(database), "MAINT_DEVICE_ID": device_id},
    )
    async with stdio_client(params) as (read, write):
        yield read, write


@asynccontextmanager
async def _http(url):
    async with streamable_http_client(url) as (read, write, _session_id):
        yield read, write


class McpToolHub:
    def __init__(self, settings, database):
        self.settings = settings
        self.database = database
        self._sessions = {}
        self._lock = threading.Lock()

    def call(self, name, arguments, state):
        return self._session(state).call(name, arguments)

    def _session(self, state):
        if self.settings.mcp_url:
            url = self.settings.mcp_url
            key, opener = "http", (lambda url=url: _http(url))
        else:
            device_id = state["alarm"]["device_id"]
            key, opener = state["run_id"], (lambda device_id=device_id: _stdio(self.database, device_id))
        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = McpSession(opener)
            return self._sessions[key]

    def close_run(self, run_id):
        if self.settings.mcp_url:
            return
        with self._lock:
            session = self._sessions.pop(run_id, None)
        if session is not None:
            session.close()

    def close(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()
