"""Expose the maintenance tools over MCP stdio or streamable HTTP.

One process is bound to one business database and one alarm device. The draft
tool returns a proposal and does not insert a work order.
"""

import argparse
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from react_agent.models import NotFoundError, ToolInputError
from react_agent.store import Store, canonical_json
from react_agent.tools import DESCRIPTIONS, execute_tool

_SESSION = None


def session():
    global _SESSION
    if _SESSION is None:
        database = os.environ.get("MAINT_BUSINESS_DB", "")
        device_id = os.environ.get("MAINT_DEVICE_ID", "")
        if not database or not device_id:
            raise RuntimeError("MAINT_BUSINESS_DB and MAINT_DEVICE_ID are required")
        _SESSION = {"store": Store(Path(database)), "view": {
            "alarm": {"device_id": device_id}, "device_read": False, "history_read": False,
            "retrieved_ids": [],
        }}
    return _SESSION


def run_tool(name, arguments):
    current = session()
    try:
        result, patch = execute_tool(name, arguments, current["view"], current["store"])
        current["view"].update(patch)
    except ToolInputError as exc:
        result = {"ok": False, "error_code": str(exc)}
    except NotFoundError as exc:
        result = {"ok": False, "error_code": str(exc)}
    return canonical_json(result)


def build_server(host="127.0.0.1", port=8000):
    mcp = FastMCP("maintenance-tools", host=host, port=port, log_level="ERROR", json_response=True)

    @mcp.tool(name="query_device", description=DESCRIPTIONS["query_device"], structured_output=False)
    def query_device(device_id: str) -> str:
        return run_tool("query_device", {"device_id": device_id})

    @mcp.tool(name="query_work_orders", description=DESCRIPTIONS["query_work_orders"], structured_output=False)
    def query_work_orders(device_id: str) -> str:
        return run_tool("query_work_orders", {"device_id": device_id})

    @mcp.tool(name="search_manual", description=DESCRIPTIONS["search_manual"], structured_output=False)
    def search_manual(query: str, top_k: int = 3) -> str:
        return run_tool("search_manual", {"query": query, "top_k": top_k})

    @mcp.tool(name="draft_work_order", description=DESCRIPTIONS["draft_work_order"], structured_output=False)
    def draft_work_order(summary: str, priority: str, evidence_ids: list[str], checks: list[str],
                         rationale: str) -> str:
        return run_tool("draft_work_order", {
            "summary": summary, "priority": priority, "evidence_ids": evidence_ids,
            "checks": checks, "rationale": rationale,
        })

    return mcp


def main(argv=None):
    parser = argparse.ArgumentParser(description="Maintenance tool MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"],
                        default=os.environ.get("MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8000")))
    args = parser.parse_args(argv)
    build_server(args.host, args.port).run(transport=args.transport)


if __name__ == "__main__":
    main()
