"""Run diagnosis and review without a separate web frontend."""

import argparse
import json
from pathlib import Path

from react_agent.config import Settings
from react_agent.models import AlarmEvent, Approval
from react_agent.service import AgentService
from react_agent.store import content_hash


def main():
    parser = argparse.ArgumentParser(description="设备告警处置Agent与工单工作流")
    sub = parser.add_subparsers(dest="command", required=True)
    diagnose = sub.add_parser("diagnose")
    diagnose.add_argument("--event", required=True)
    diagnose.add_argument("--device", required=True)
    diagnose.add_argument("--message", required=True)
    diagnose.add_argument("--severity", choices=["info", "warning", "critical"], default="warning")
    decide = sub.add_parser("decide")
    decide.add_argument("run_id")
    decide.add_argument("--decision", choices=["approve", "reject"], required=True)
    decide.add_argument("--proposal-hash", required=True, help="Hash from the inspected diagnosis result")
    decide.add_argument("--note", default="")
    report = sub.add_parser("report")
    report.add_argument("run_id")
    report.add_argument("--out", type=Path)
    args = parser.parse_args()
    service = AgentService(Settings.from_env())
    try:
        if args.command == "diagnose":
            result = service.diagnose(AlarmEvent(event_id=args.event, device_id=args.device,
                                                 message=args.message, severity=args.severity))
        elif args.command == "decide":
            result = service.decide(args.run_id, Approval(approved=args.decision == "approve",
                                     proposal_sha256=args.proposal_hash, note=args.note))
        else:
            text = service.report_markdown(args.run_id)
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(text, encoding="utf-8")
                print(str(args.out.resolve()))
            else:
                print(text)
            return
        if result["proposal"]:
            result["proposal_sha256"] = content_hash(result["proposal"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        service.close()


if __name__ == "__main__":
    main()
