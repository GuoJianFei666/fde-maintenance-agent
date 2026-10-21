"""Coordinate a persistent Agent run and human decision."""

import sqlite3
import threading

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from react_agent.config import Settings
from react_agent.graph import build_graph
from react_agent.llm import DeepSeekModel
from react_agent.models import AlarmEvent, Approval, ConflictError
from react_agent.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from react_agent.store import Store, canonical_json, content_hash


class AgentService:
    """Use one local worker; SQLite uniqueness protects repeated business writes."""

    def __init__(self, settings: Settings, model=None):
        self.settings = settings
        self.store = Store(settings.data_dir / "business.db")
        self.model = model if model is not None else DeepSeekModel(settings)
        self._lock = threading.RLock()
        self._checkpoint_connection = sqlite3.connect(settings.data_dir / "checkpoints.db", check_same_thread=False)
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer.setup()
        self.graph = build_graph(self.store, self.model, self.checkpointer, settings.max_rounds)

    def close(self):
        self._checkpoint_connection.close()

    @staticmethod
    def config(run_id):
        return {"configurable": {"thread_id": run_id}, "recursion_limit": 40}

    def diagnose(self, alarm: AlarmEvent):
        with self._lock:
            self.store.device(alarm.device_id)
            run_id, created = self.store.create_run(alarm)
            if not created:
                return self.store.run(run_id)
            self.store.trace(run_id, "intake", {"data_kind": "synthetic_demo", "event_id": alarm.event_id})
            try:
                self.graph.invoke({"messages": [HumanMessage(content=canonical_json(alarm.model_dump()))],
                                   "run_id": run_id, "alarm": alarm.model_dump(), "rounds": 0,
                                   "status": "running", "retrieved_ids": [],
                                   "device_read": False, "history_read": False}, self.config(run_id))
            except Exception as exc:
                self._record_failure(run_id, exc)
                raise
            return self._sync(run_id)

    def decide(self, run_id: str, approval: Approval):
        with self._lock:
            run = self.store.run(run_id)
            proposal = run["proposal"]
            if not proposal or content_hash(proposal) != approval.proposal_sha256:
                raise ConflictError("stale_or_missing_proposal")
            if run["status"] == "completed" and approval.approved:
                return run
            if run["status"] == "rejected" and not approval.approved:
                return run
            if run["status"] != "awaiting_approval":
                raise ConflictError("decision_already_terminal")
            self.store.trace(run_id, "human_decision", approval.model_dump())
            try:
                self.graph.invoke(Command(resume=approval.model_dump()), self.config(run_id))
            except Exception as exc:
                self._record_failure(run_id, exc)
                raise
            return self._sync(run_id)

    def _record_failure(self, run_id, exc):
        # Unexpected exceptions remain exceptions. The record describes failure, never a substitute answer.
        code = type(exc).__name__
        self.store.trace(run_id, "execution_failed", {"error_type": code})
        old = self.store.run(run_id)
        self.store.update_run(run_id, "failed", proposal=old["proposal"], report=old["report"], error_code=code)

    def _sync(self, run_id):
        state = self.graph.get_state(self.config(run_id)).values
        evidence = [self.store.manual(i) for i in state.get("proposal", {}).get("evidence_ids", [])]
        traces = self.store.traces(run_id)
        model_calls = [t["data"] for t in traces if t["node"] == "model"]
        usages = [c["usage"] for c in model_calls if c.get("usage") is not None]
        usage = None
        if usages and len(usages) == len(model_calls):
            usage = {k: sum(u[k] for u in usages) for k in ("input_tokens", "output_tokens", "total_tokens")}
        report = {
            "data_kind": "synthetic_demo", "execution_mode": self.model.mode,
            "prompt_version": PROMPT_VERSION, "prompt_sha256": content_hash(SYSTEM_PROMPT),
            "corpus_version": self.store.corpus_version, "corpus_sha256": self.store.corpus_sha256,
            "configured_model": self.settings.model,
            "observed_models": sorted({c["model_name"] for c in model_calls if c.get("model_name")}),
            "model_call_count": len(model_calls), "usage": usage,
            "proposal_sha256": state.get("proposal_sha256"), "evidence": evidence,
            "order": state.get("order"), "answer": state.get("answer"),
            "approval_note": state.get("approval_note"),
        }
        self.store.update_run(run_id, state["status"], proposal=state.get("proposal"),
                              report=report, error_code=state.get("error_code"))
        return self.store.run(run_id)

    def report_markdown(self, run_id):
        run = self.store.run(run_id)
        report = run["report"] or {}
        proposal = run["proposal"] or {}
        lines = ["# 设备告警处置记录", "", f"运行编号：{run_id}", f"状态：{run['status']}",
                 f"设备：{run['alarm']['device_id']}", f"告警：{run['alarm']['message']}",
                 f"执行方式：{report.get('execution_mode', 'not_completed')}",
                 "数据类型：本项目构造的演示数据", "", "## 工单草案", "",
                 proposal.get("summary", "尚未形成草案。")]
        if proposal:
            lines.extend([f"优先级：{proposal['priority']}", "", proposal["rationale"], ""])
            lines.extend("- " + step for step in proposal["checks"])
        lines.extend(["", "## 引用原文", ""])
        for chunk in report.get("evidence", []):
            lines.extend([f"[{chunk['id']}] {chunk['source']} / {chunk['version']}", "", chunk["body"], ""])
        if report.get("order"):
            lines.extend(["## 写入结果", "", f"工单编号：{report['order']['id']}", "人工确认后已写入本地演示工单库。", ""])
        if report.get("answer"):
            lines.extend(["## 待补信息", "", report["answer"], ""])
        lines.extend(["## 运行版本", "", f"Prompt：{report.get('prompt_version', 'unavailable')}",
                      f"语料：{report.get('corpus_version', 'unavailable')}",
                      f"模型调用次数：{report.get('model_call_count', 0)}", f"用量：{report.get('usage')}"])
        return "\n".join(lines) + "\n"
