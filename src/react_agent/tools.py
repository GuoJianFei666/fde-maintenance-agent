"""Expose bounded business tools; drafts cannot write a work order."""

from pydantic import ValidationError

from react_agent.models import DeviceQuery, ManualQuery, ToolInputError, WorkOrderDraft

TOOL_MODELS = {
    "query_device": DeviceQuery,
    "query_work_orders": DeviceQuery,
    "search_manual": ManualQuery,
    "draft_work_order": WorkOrderDraft,
}
DESCRIPTIONS = {
    "query_device": "查询当前告警设备的型号类别、维护组和运行状态。",
    "query_work_orders": "查询当前设备已有维护工单，供重复问题检查和工单上下文参考。",
    "search_manual": "按告警关键词检索当前设备适用手册，返回证据ID、原文、来源和版本。",
    "draft_work_order": "只生成待人工确认的维护工单草案，不写入工单数据库。此前必须查设备、历史工单和手册。",
}
TOOL_SCHEMAS = [{"type": "function", "function": {
    "name": name, "description": DESCRIPTIONS[name], "parameters": model.model_json_schema()
}} for name, model in TOOL_MODELS.items()]


def execute_tool(name, arguments, state, store):
    if name not in TOOL_MODELS:
        raise ToolInputError("tool_not_allowed")
    try:
        params = TOOL_MODELS[name].model_validate(arguments)
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
        raise ToolInputError("invalid_arguments:" + ",".join(fields)) from None
    device_id = state["alarm"]["device_id"]
    if name in ("query_device", "query_work_orders") and params.device_id != device_id:
        raise ToolInputError("device_scope_mismatch")
    if name == "query_device":
        return {"ok": True, "device": store.device(device_id)}, {"device_read": True}
    if name == "query_work_orders":
        return {"ok": True, "orders": store.orders(device_id)}, {"history_read": True}
    if name == "search_manual":
        hits = store.search(params.query, device_id, params.top_k)
        seen = list(dict.fromkeys([*state.get("retrieved_ids", []), *[hit["id"] for hit in hits]]))
        return {"ok": True, "retrieval": "SQLite FTS5 / BM25", "hits": hits}, {"retrieved_ids": seen}
    if not state.get("device_read") or not state.get("history_read"):
        raise ToolInputError("read_device_and_history_before_drafting")
    evidence_ids = list(dict.fromkeys(params.evidence_ids))
    if not set(evidence_ids).issubset(state.get("retrieved_ids", [])):
        raise ToolInputError("citation_not_retrieved_in_this_run")
    device_type = store.device(device_id)["type"]
    for chunk_id in evidence_ids:
        if store.manual(chunk_id)["device_type"] not in (device_type, "general"):
            raise ToolInputError("citation_device_type_mismatch")
    proposal = params.model_dump()
    proposal["evidence_ids"] = evidence_ids
    return {"ok": True, "status": "draft_only", "proposal": proposal}, {"proposal": proposal}


def patch_from_result(name, result, state):
    """Rebuild the graph patch from the public tool payload.

    The MCP server applies the same patch inside its own session. This function
    keeps the in-process graph state aligned with that payload.
    """
    if not result.get("ok"):
        return {}
    if name == "query_device":
        return {"device_read": True}
    if name == "query_work_orders":
        return {"history_read": True}
    if name == "search_manual":
        seen = list(dict.fromkeys([*state.get("retrieved_ids", []), *[hit["id"] for hit in result.get("hits", [])]]))
        return {"retrieved_ids": seen}
    if name == "draft_work_order":
        return {"proposal": result["proposal"]}
    return {}
