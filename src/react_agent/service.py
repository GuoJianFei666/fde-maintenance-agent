"""Coordinate a persistent Agent run and human decision."""

import sqlite3
import threading

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from react_agent.config import Settings
from react_agent.extraction import EXTRACTION_VERSION
from react_agent.graph import build_graph
from react_agent.llm import DeepSeekModel
from react_agent.maintie import MaintIEIndex
from react_agent.models import AlarmEvent, Approval, ConflictError, MaintenanceText, ModelCallError
from react_agent.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from react_agent.store import Store, canonical_json, content_hash


class AgentService:
    """Use one local worker; SQLite uniqueness protects repeated business writes."""

    def __init__(self, settings: Settings, model=None):
        self.settings = settings
        self.store = Store(settings.data_dir / "business.db")
        self.cases = MaintIEIndex(settings.data_dir / "maintie.db")
        self.model = model if model is not None else DeepSeekModel(settings)
        self._lock = threading.RLock()
        self._checkpoint_connection = sqlite3.connect(settings.data_dir / "checkpoints.db", check_same_thread=False)
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer.setup()
        self.graph = build_graph(self.store, self.model, self.checkpointer, settings.max_rounds, cases=self.cases)

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

    def submit_text(self, request: MaintenanceText):
        with self._lock:
            self.store.device(request.device_id)
            source = self.cases.record(request.source_record_id) if request.source_record_id else None
            if source and source["body"] != request.message:
                raise ConflictError("source_record_text_mismatch")
            run_id, created = self.store.create_run(request, workflow="maintenance_text")
            if not created:
                return self.store.run(run_id)
            self.store.trace(run_id, "intake", {
                "workflow": "maintenance_text", "event_id": request.event_id,
                "input_kind": "public_maintie_short_text" if source else "user_supplied_text",
                "source_record_id": request.source_record_id, "device_mapping": "user_selected_demo_device",
            })
            try:
                self.graph.invoke({"messages": [], "run_id": run_id, "alarm": request.model_dump(),
                                   "workflow": "maintenance_text", "status": "running", "rounds": 0,
                                   "input_source": source, "dataset": self.cases.metadata()}, self.config(run_id))
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
        detail = {"error_type": code}
        if isinstance(exc, ModelCallError):
            detail["category"] = str(exc)
        self.store.trace(run_id, "execution_failed", detail)
        old = self.store.run(run_id)
        self.store.update_run(run_id, "failed", proposal=old["proposal"], report=old["report"], error_code=code)

    def _sync(self, run_id):
        state = self.graph.get_state(self.config(run_id)).values
        is_text = state.get("workflow") == "maintenance_text"
        evidence = state.get("case_evidence", []) if is_text else [
            self.store.manual(i) for i in state.get("proposal", {}).get("evidence_ids", [])]
        traces = self.store.traces(run_id)
        model_calls = [t["data"] for t in traces if t["node"] == "model"]
        usages = [c["usage"] for c in model_calls if c.get("usage") is not None]
        usage = None
        if usages and len(usages) == len(model_calls):
            usage = {k: sum(u[k] for u in usages) for k in ("input_tokens", "output_tokens", "total_tokens")}
        report = {
            "data_kind": "public_corpus_demo_intake" if is_text else "synthetic_demo",
            "execution_mode": self.model.mode,
            "prompt_version": EXTRACTION_VERSION if is_text else PROMPT_VERSION,
            "prompt_sha256": state["text_extraction"]["prompt_sha256"] if is_text else content_hash(SYSTEM_PROMPT),
            "corpus_version": self.store.corpus_version, "corpus_sha256": self.store.corpus_sha256,
            "configured_model": self.settings.model,
            "observed_models": sorted({c["model_name"] for c in model_calls if c.get("model_name")}),
            "model_call_count": len(model_calls), "usage": usage,
            "proposal_sha256": state.get("proposal_sha256"), "evidence": evidence,
            "order": state.get("order"), "answer": state.get("answer"),
            "approval_note": state.get("approval_note"),
        }
        if is_text:
            report.update({"workflow": "maintenance_text", "text_extraction": state["text_extraction"],
                           "dataset": state["dataset"], "input_source": state.get("input_source"),
                           "device_mapping": "user_selected_demo_device", "evidence_kind": "case_reference_not_sop"})
        self.store.update_run(run_id, state["status"], proposal=state.get("proposal"),
                              report=report, error_code=state.get("error_code"))
        return self.store.run(run_id)

    def report_markdown(self, run_id):
        run = self.store.run(run_id)
        report = run["report"] or {}
        proposal = run["proposal"] or {}
        is_text = run["workflow"] == "maintenance_text"
        data_label = "公开MaintIE案例与本地演示受理流程；所选设备为演示资产" if is_text else "本项目构造的演示数据"
        lines = ["# 维修文本受理记录" if is_text else "# 设备告警处置记录", "", f"运行编号：{run_id}", f"状态：{run['status']}",
                 f"设备：{run['alarm']['device_id']}", f"告警：{run['alarm']['message']}",
                 f"执行方式：{report.get('execution_mode', 'not_completed')}",
                 f"数据类型：{data_label}", "", "## 工单草案", "",
                 proposal.get("summary", "尚未形成草案。")]
        if proposal:
            lines.extend([f"优先级：{proposal['priority']}", "", proposal["rationale"], ""])
            lines.extend("- " + step for step in proposal["checks"])
        if is_text:
            lines.extend(["", "## 原文实体抽取", "", "跨度使用从0开始、左闭右开的token编号；仅评估五个顶层类别。", ""])
            for entity in report.get("text_extraction", {}).get("entities", []):
                lines.append(f"- {entity['type']} [{entity['start']}, {entity['end']}): {entity['text']}")
            dataset = report.get("dataset", {})
            lines.extend(["", "保留英文原文；中文段落为本项目生成的受理说明。公开案例不代表当前设备的维修履历或适用操作规程。",
                          f"MaintIE版本：{dataset.get('revision')}",
                          f"原始数据SHA256：{dataset.get('files', {}).get('gold_release.json', {}).get('sha256')}"])
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
