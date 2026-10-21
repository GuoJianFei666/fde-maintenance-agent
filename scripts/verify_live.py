"""Run a bounded, real DeepSeek diagnosis and review acceptance suite.

All business inputs are synthetic demo cases. This script calls the configured
provider and reports actual outcomes; it does not select scripted model fixtures.
"""

import argparse
import json
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from react_agent.config import Settings
from react_agent.models import AlarmEvent, Approval
from react_agent.service import AgentService
from react_agent.store import content_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("reports/live-verification.json"))
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    settings = Settings.from_env()
    settings = replace(settings, data_dir=settings.data_dir / ("acceptance-" + stamp + "-" + uuid.uuid4().hex[:6]))
    cases = [
        {"name": "pump_approve_after_restart", "device": "P-101", "message": "循环泵振动升高并伴随轴承异响，请按手册和历史工单生成待确认检查工单。", "decision": True, "expected": "completed"},
        {"name": "motor_reject", "device": "M-201", "message": "驱动电机出现过热温升告警，现场电流和负载数据尚未补齐，请查手册后生成待核实的检查工单。", "decision": False, "expected": "rejected"},
        {"name": "unknown_manual_evidence", "device": "C-301", "message": "设备出现固件签名校验失败，错误码SIG900。现有维护手册未提供该错误码，请明确缺少的依据，不要编造维修步骤。", "decision": None, "expected": "needs_information"},
    ]
    results = []
    for case in cases:
        started = time.perf_counter()
        service = AgentService(settings)
        try:
            event = AlarmEvent(event_id=f"{stamp}-{case['name']}", device_id=case["device"], message=case["message"])
            run = service.diagnose(event)
            before_orders = [o for o in service.store.orders() if o.get("source_run") == run["id"]]
            assert not before_orders, "An unapproved run wrote an order"
            initial_status = run["status"]
            if case["decision"] is not None:
                assert initial_status == "awaiting_approval", initial_status
                # A new service instance proves persisted human-review state resumes after restart.
                service.close()
                service = AgentService(settings)
                choice = Approval(approved=case["decision"], proposal_sha256=content_hash(run["proposal"]),
                                  note="本地验收脚本执行的审批接口演示，非真实维护指令。")
                run = service.decide(run["id"], choice)
                if case["decision"]:
                    duplicate = service.decide(run["id"], choice)
                    assert duplicate["report"]["order"]["id"] == run["report"]["order"]["id"]
            orders = [o for o in service.store.orders() if o.get("source_run") == run["id"]]
            traces = service.store.traces(run["id"])
            actual = {"case": case["name"], "run_id": run["id"], "event": event.model_dump(),
                      "expected_status": case["expected"], "initial_status": initial_status,
                      "actual_status": run["status"], "passed": run["status"] == case["expected"],
                      "unapproved_writes": len(before_orders), "written_orders": len(orders),
                      "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                      "proposal": run["proposal"], "report": run["report"], "trace": traces}
            results.append(actual)
            report_file = args.out.parent / (case["name"] + ".md")
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(service.report_markdown(run["id"]), encoding="utf-8")
            print(json.dumps({k: v for k, v in actual.items() if k not in ("event", "proposal", "report", "trace")}, ensure_ascii=False), flush=True)
        finally:
            service.close()
        # Preserve each observed result even if a later case or acceptance assertion fails.
        summary = {"kind": "live_provider_acceptance", "provider": "DeepSeek", "model": settings.model,
                   "performed_at": stamp, "data_kind": "synthetic_demo", "cases": results,
                   "passed": all(c["passed"] for c in results), "planned_case_count": len(cases),
                   "completed_case_count": len(results), "approval_operator": "acceptance_script",
                   "scope": "Three selected local POC cases, not production accuracy or reliability statistics"}
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not all(c["passed"] for c in results):
        raise SystemExit("Acceptance expectations were not met; inspect the recorded provider outputs")


if __name__ == "__main__":
    main()
