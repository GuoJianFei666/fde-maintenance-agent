"""Adapt the upstream ReAct loop into an approved maintenance workflow.

Upstream: langchain-ai/react-agent, MIT, commit 087d90d0c876668956b733a104f1708cef0128e2.
The model chooses read tools and drafts. Fixed nodes own review and database writes.
"""

import time

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from react_agent.intake import text_nodes
from react_agent.models import Approval, ConflictError, ToolInputError
from react_agent.prompts import SYSTEM_PROMPT
from react_agent.state import State
from react_agent.store import canonical_json, content_hash
from react_agent.tools import TOOL_SCHEMAS, execute_tool


def build_graph(store, model, checkpointer, max_rounds=6, *, cases=None):
    def call_model(state: State):
        rounds = state.get("rounds", 0)
        if rounds >= max_rounds:
            store.trace(state["run_id"], "limit", {"code": "agent_round_limit", "rounds": rounds})
            return {"status": "failed", "error_code": "agent_round_limit"}
        started = time.perf_counter()
        response = model.invoke([SystemMessage(content=SYSTEM_PROMPT), *state["messages"]], TOOL_SCHEMAS)
        if not isinstance(response, AIMessage):
            raise TypeError("Model adapter must return AIMessage")
        store.trace(state["run_id"], "model", {
            "round": rounds + 1, "mode": model.mode,
            "model_name": response.response_metadata.get("model_name"),
            "tool_names": [t["name"] for t in response.tool_calls],
            "usage": response.usage_metadata,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        })
        return {"messages": [response], "rounds": rounds + 1}

    def route_model(state: State):
        if state.get("status") == "failed":
            return END
        return "tools" if state["messages"][-1].tool_calls else "finish_without_draft"

    def run_tools(state: State):
        calls = state["messages"][-1].tool_calls
        if len(calls) > 5:
            return {"status": "failed", "error_code": "too_many_tools_in_one_round"}
        current = dict(state)
        updates = {}
        messages = []
        for call in calls:
            started = time.perf_counter()
            try:
                result, patch = execute_tool(call["name"], call["args"], current, store)
                current.update(patch)
                updates.update(patch)
            except ToolInputError as exc:
                result = {"ok": False, "error_code": str(exc)}
            store.trace(state["run_id"], "tool", {
                "name": call["name"], "arguments": call["args"], "result": result,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            })
            messages.append(ToolMessage(content=canonical_json(result), tool_call_id=call["id"]))
        if current.get("proposal"):
            updates.update({"status": "awaiting_approval", "proposal_sha256": content_hash(current["proposal"])})
        return {**updates, "messages": messages}

    def route_tools(state: State):
        if state.get("status") == "failed":
            return END
        return "human_review" if state.get("proposal") else "call_model"

    def human_review(state: State):
        # No side effects before interrupt: this node starts again when resumed.
        decision = Approval.model_validate(interrupt({
            "run_id": state["run_id"], "proposal": state["proposal"],
            "proposal_sha256": state["proposal_sha256"], "action": "approve_or_reject_work_order",
        }))
        if decision.proposal_sha256 != state["proposal_sha256"]:
            raise ConflictError("stale_proposal_hash")
        return {"approved": decision.approved, "approval_note": decision.note,
                "status": "approved" if decision.approved else "rejected"}

    def commit_order(state: State):
        if state.get("approved") is not True:
            raise ConflictError("human_approval_required")
        kind = "public_corpus_demo_intake" if state.get("workflow") == "maintenance_text" else "synthetic_demo"
        order = store.create_order(state["run_id"], state["alarm"]["device_id"], state["proposal"], data_kind=kind)
        store.trace(state["run_id"], "commit_order", {"order_id": order["id"], "approved": True})
        return {"order": order, "status": "completed"}

    def finish_without_draft(state: State):
        return {"status": "needs_information", "answer": state["messages"][-1].content}

    builder = StateGraph(State)
    builder.add_node("call_model", call_model)
    builder.add_node("tools", run_tools)
    builder.add_node("human_review", human_review)
    builder.add_node("commit_order", commit_order)
    builder.add_node("finish_without_draft", finish_without_draft)
    if cases is not None:
        extract, retrieve, draft = text_nodes(store, model, cases)
        builder.add_node("extract_text", extract)
        builder.add_node("retrieve_cases", retrieve)
        builder.add_node("draft_text_intake", draft)
        builder.add_conditional_edges(START, lambda s: "extract_text" if s.get("workflow") == "maintenance_text" else "call_model")
        builder.add_edge("extract_text", "retrieve_cases")
        builder.add_edge("retrieve_cases", "draft_text_intake")
        builder.add_conditional_edges("draft_text_intake", lambda s: "human_review" if s.get("proposal") else END)
    else:
        builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", route_model)
    builder.add_conditional_edges("tools", route_tools)
    builder.add_conditional_edges("human_review", lambda s: "commit_order" if s["approved"] else END)
    builder.add_edge("commit_order", END)
    builder.add_edge("finish_without_draft", END)
    return builder.compile(checkpointer=checkpointer, name="maintenance_agent")
