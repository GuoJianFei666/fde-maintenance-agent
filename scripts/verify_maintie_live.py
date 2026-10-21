"""Exercise the text-intake workflow with the configured model and local approvals."""

import argparse
import json
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from react_agent.config import Settings
from react_agent.models import Approval, MaintenanceText
from react_agent.service import AgentService
from react_agent.store import content_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("Choose a new output path to preserve previous observations")
    settings = Settings.from_env()
    settings = replace(settings, data_dir=settings.data_dir / ("maintie-live-" + uuid.uuid4().hex[:8]))
    scenarios = [
        ("approve_after_restart", "P-101", "hydraulic pump leaking oil", True, "completed"),
        ("reject", "M-201", "electric motor bearings damaged", False, "rejected"),
        ("missing_information", "P-101", "please help", None, "needs_information"),
    ]
    results = []
    summary = {"kind": "live_maintie_workflow_acceptance", "performed_at": datetime.now(timezone.utc).isoformat(),
               "model": settings.model, "planned_count": len(scenarios), "approval_operator": "acceptance_script",
               "scope": "Three authored intake examples, public case references and demo assets; not industrial maintenance outcomes",
               "cases": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for name, device_id, text, approved, expected in scenarios:
        service = AgentService(settings)
        try:
            event = MaintenanceText(event_id=uuid.uuid4().hex, device_id=device_id, message=text)
            run = service.submit_text(event)
            first_status = run["status"]
            assert not [o for o in service.store.orders() if o.get("source_run") == run["id"]]
            assert service.submit_text(event)["id"] == run["id"]
            if approved is not None:
                assert first_status == "awaiting_approval", first_status
                service.close()
                service = AgentService(settings)
                before = len([t for t in service.store.traces(run["id"]) if t["node"] == "model"])
                choice = Approval(approved=approved, proposal_sha256=content_hash(run["proposal"]),
                                  note="本地验收脚本演示审批，未执行真实设备维护。")
                run = service.decide(run["id"], choice)
                repeated = service.decide(run["id"], choice)
                assert repeated["id"] == run["id"]
                assert before == len([t for t in service.store.traces(run["id"]) if t["node"] == "model"])
            written = len([o for o in service.store.orders() if o.get("source_run") == run["id"]])
            actual = {"scenario": name, "request": event.model_dump(), "initial_status": first_status,
                      "actual_status": run["status"], "expected_status": expected, "written_orders": written,
                      "passed": run["status"] == expected and written == int(approved is True),
                      "run": run, "trace": service.store.traces(run["id"])}
            results.append(actual)
            (args.out.parent / (name + ".md")).write_text(service.report_markdown(run["id"]), encoding="utf-8")
            summary.update({"completed_count": len(results), "passed": all(r["passed"] for r in results)})
            args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({k: actual[k] for k in ("scenario", "actual_status", "written_orders", "passed")}), flush=True)
        finally:
            service.close()
    assert summary["completed_count"] == len(scenarios) and summary["passed"]


if __name__ == "__main__":
    main()
