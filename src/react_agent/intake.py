"""Fixed intake nodes after model extraction; cases are references, not SOPs."""

from react_agent.extraction import extract_text
from react_agent.store import content_hash


def text_nodes(store, model, cases):
    def extract(state):
        source = state.get("input_source")

        def observed(response, elapsed_ms):
            store.trace(state["run_id"], "model", {
                "round": 1, "mode": model.mode, "workflow": "maintenance_text",
                "model_name": response.response_metadata.get("model_name"), "usage": response.usage_metadata,
                "tool_names": [call["name"] for call in response.tool_calls],
                "tool_calls": response.tool_calls, "elapsed_ms": elapsed_ms,
            })

        result = extract_text(model, state["alarm"]["message"], tokens=source["tokens"] if source else None,
                              on_response=observed)
        store.trace(state["run_id"], "extract_text", result)
        return {"text_extraction": result, "rounds": 1}

    def retrieve(state):
        hits = cases.search(state["alarm"]["message"])
        store.trace(state["run_id"], "retrieve_cases", {
            "hits": hits, "dataset_revision": cases.manifest["revision"],
            "query": state["alarm"]["message"], "evaluation_rows_indexed": False,
        })
        return {"case_evidence": hits, "dataset": cases.metadata()}

    def draft(state):
        entities = state["text_extraction"]["entities"]
        categories = {entity["type"] for entity in entities}
        missing = []
        if "PhysicalObject" not in categories:
            missing.append("设备或部件名称")
        if not categories.intersection({"State", "Process", "Activity"}):
            missing.append("异常状态、现象或待处理事项")
        if not state["case_evidence"]:
            missing.append("可供受理参考的维修案例")
        if missing:
            answer = "请补充或核实：" + "、".join(missing) + "。当前未生成工单草稿。"
            store.trace(state["run_id"], "draft_text_intake", {"missing": missing})
            return {"status": "needs_information", "answer": answer}
        proposal = {
            "summary": "维修受理复核：" + state["alarm"]["message"][:120],
            "priority": {"info": "low", "warning": "medium", "critical": "high"}[state["alarm"]["severity"]],
            "evidence_ids": [case["id"] for case in state["case_evidence"]],
            "checks": ["核对所选设备编号、现场部件与用户原始描述是否一致。",
                       "补充发生时间、当前状态、相关测量值及适用作业规程，再由维护人员判断处理方法。",
                       "相似案例仅作受理参考；原文中的历史活动不能直接转成当前设备的维修指令。"],
            "rationale": "依据用户原始描述抽取受理字段，并附公开维修短文本供人工比较；未推断故障原因或维修效果。",
            "kind": "maintenance_text_intake", "source_text": state["alarm"]["message"],
            "extracted_entities": entities, "dataset_revision": cases.manifest["revision"],
            "evidence_sha256": content_hash(state["case_evidence"]),
        }
        store.trace(state["run_id"], "draft_text_intake", {"proposal": proposal, "draft_only": True})
        return {"proposal": proposal, "proposal_sha256": content_hash(proposal), "status": "awaiting_approval"}

    return extract, retrieve, draft
