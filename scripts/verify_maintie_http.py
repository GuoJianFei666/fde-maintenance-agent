"""Verify the running loopback HTTP service with a real, sourced MaintIE input."""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("Choose a new output path")
    with httpx.Client(base_url=args.url, timeout=90, trust_env=False) as client:
        def get(path, **kwargs):
            response = client.get(path, **kwargs)
            response.raise_for_status()
            return response.json()

        health = get("/health")
        metadata = get("/api/datasets/maintie")
        source = get("/api/cases/MAINTIE-GOLD-0256")
        schema = get("/openapi.json")
        chinese_hits = get("/api/cases/search", params={"q": "泵漏油"})
        request = {"event_id": "http-maintie-" + uuid.uuid4().hex[:12], "device_id": "P-101",
                   "message": source["body"], "source_record_id": source["id"], "severity": "warning"}
        response = client.post("/api/maintenance-texts", json=request)
        response.raise_for_status()
        run = response.json()
        duplicate = client.post("/api/maintenance-texts", json=request)
        duplicate.raise_for_status()
        traces = get(f"/api/runs/{run['id']}/trace")
        orders = get("/api/work-orders")
        report = client.get(f"/api/runs/{run['id']}/report")
        report.raise_for_status()
        checks = {
            "live_provider": health["execution_mode"] == "live_deepseek",
            "dataset_count": metadata["record_count"] == 1076,
            "openapi": "/api/maintenance-texts" in schema["paths"],
            "chinese_query": bool(chinese_hits),
            "source_is_evaluation": source["split"] == "evaluation",
            "pending_review": run["status"] == "awaiting_approval",
            "duplicate_reuses_run": duplicate.json()["id"] == run["id"],
            "one_model_call": len([item for item in traces if item["node"] == "model"]) == 1,
            "no_unapproved_order": not any(order.get("source_run") == run["id"] for order in orders),
            "reference_only": all(row["split"] == "reference" for row in run["report"]["evidence"]),
            "no_exact_self_reference": all(row["text_sha256"] != source["text_sha256"] for row in run["report"]["evidence"]),
            "source_preserved": run["report"]["input_source"]["id"] == source["id"],
            "report": "原文实体抽取" in report.text and "MAINTIE-GOLD-" in report.text,
        }
        summary = {"kind": "live_loopback_http_maintie", "performed_at": datetime.now(timezone.utc).isoformat(),
                   "url": args.url, "request": request, "run": run, "trace": traces,
                   "checks": checks, "passed": all(checks.values())}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.out.parent / "http-pending-review.md").write_text(report.text, encoding="utf-8")
        print(json.dumps({"passed": summary["passed"], "checks": checks, "run_id": run["id"]}, ensure_ascii=False))
        assert summary["passed"], "Inspect the saved actual response"


if __name__ == "__main__":
    main()
