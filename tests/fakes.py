"""Scripted test fixtures, never selected by the production API or CLI."""

from langchain_core.messages import AIMessage


def calls(*items):
    return AIMessage(content="", tool_calls=[{"id": f"test-{i}-{name}", "name": name,
                     "args": args, "type": "tool_call"} for i, (name, args) in enumerate(items)])


def draft(**overrides):
    return {"summary": "复核循环泵振动升高告警", "priority": "medium", "evidence_ids": ["PUMP-VIB-01"],
            "checks": ["记录振动变化和告警时序", "现场复核轴承与紧固件状态"],
            "rationale": "演示手册要求先复核告警与现场信息，当前不能直接确定故障。", **overrides}


def normal_responses():
    return [calls(("query_device", {"device_id": "P-101"}),
                  ("query_work_orders", {"device_id": "P-101"}),
                  ("search_manual", {"query": "泵振动告警", "top_k": 3})),
            calls(("draft_work_order", draft()))]


class ScriptedModel:
    mode = "scripted_test"

    def __init__(self, responses=None):
        self.responses = list(normal_responses() if responses is None else responses)
        self.calls = 0

    def invoke(self, messages, tools):
        self.calls += 1
        if not self.responses:
            raise AssertionError("Unexpected extra model call in scripted test")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
