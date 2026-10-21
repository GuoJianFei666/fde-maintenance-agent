"""Check the running local API over real HTTP with one live provider diagnosis."""

import json
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


def request(path, payload=None):
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request("http://127.0.0.1:8765" + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read()
        return response.status, raw, response.headers.get_content_type()


def main():
    checks = {}
    for path in ["/health", "/docs", "/openapi.json", "/api/devices"]:
        status, raw, content_type = request(path)
        assert status == 200
        checks[path] = {"status": status, "content_type": content_type, "bytes": len(raw)}
    event = {"event_id": "http-demo-" + uuid.uuid4().hex[:12], "device_id": "P-101",
             "message": "循环泵振动升高并伴随温升，请查设备、历史工单和手册，生成待人工确认的检查工单。"}
    status, raw, _ = request("/api/alarms", event)
    run = json.loads(raw)
    assert status == 200 and run["status"] == "awaiting_approval"
    _, repeated_raw, _ = request("/api/alarms", event)
    assert json.loads(repeated_raw)["id"] == run["id"]
    trace_status, trace_raw, _ = request(f"/api/runs/{run['id']}/trace")
    report_status, report_raw, _ = request(f"/api/runs/{run['id']}/report")
    _, orders_raw, _ = request("/api/work-orders")
    assert not [o for o in json.loads(orders_raw) if o.get("source_run") == run["id"]]
    assert trace_status == report_status == 200
    result = {"status": "pass", "kind": "live_local_http", "performed_at": datetime.now(timezone.utc).isoformat(),
              "checks": checks, "repeated_event_same_run": True, "unapproved_work_orders": 0,
              "run": run, "trace": json.loads(trace_raw), "retained_for_manual_demo": True}
    out = Path("reports/http-smoke.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out.parent / "http-demo.md").write_bytes(report_raw)
    print(json.dumps({"status": "pass", "run_id": run["id"], "run_status": run["status"],
                      "http_endpoints": list(checks), "repeated_event_same_run": True,
                      "unapproved_work_orders": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
