from fastapi.testclient import TestClient

from react_agent.api import create_app
from react_agent.config import Settings
from react_agent.models import ModelCallError
from react_agent.store import content_hash
from tests.fakes import ScriptedModel

EVENT = {"event_id": "api-001", "device_id": "P-101", "message": "循环泵振动升高"}


def test_rest_flow_validation_review_and_report(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), ScriptedModel())
    with TestClient(app) as client:
        assert client.get("/health").json()["execution_mode"] == "scripted_test"
        assert len(client.get("/api/devices").json()) == 3
        assert client.get("/api/devices/NOT-FOUND").status_code == 404
        assert client.get("/api/runs/missing").status_code == 404
        assert client.post("/api/alarms", json={"device_id": "P-101"}).status_code == 422
        hits = client.get("/api/manuals/search", params={"device_id": "P-101", "q": "振动"}).json()
        assert "PUMP-VIB-01" in [x["id"] for x in hits]
        result = client.post("/api/alarms", json=EVENT)
        assert result.status_code == 200
        run = result.json()
        assert run["status"] == "awaiting_approval"
        url = f"/api/runs/{run['id']}/approval"
        invalid = {"approved": "false", "proposal_sha256": content_hash(run["proposal"])}
        assert client.post(url, json=invalid).status_code == 422
        assert client.post(url, json={"approved": True, "proposal_sha256": "0" * 64}).status_code == 409
        approved = client.post(url, json={"approved": True, "proposal_sha256": content_hash(run["proposal"])})
        assert approved.json()["status"] == "completed"
        assert len([x for x in client.get("/api/work-orders").json() if x.get("source_run")]) == 1
        assert any(x["node"] == "commit_order" for x in client.get(f"/api/runs/{run['id']}/trace").json())
        report = client.get(f"/api/runs/{run['id']}/report")
        assert "PUMP-VIB-01" in report.text
        assert "scripted_test" in report.text


def test_api_exposes_missing_model_configuration(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, api_key=""))) as client:
        response = client.post("/api/alarms", json=EVENT)
        assert response.status_code == 503
        assert response.json() == {"error": "model_not_configured"}


def test_provider_error_is_not_replaced_by_a_success_response(tmp_path):
    model = ScriptedModel([ModelCallError("RateLimitError")])
    with TestClient(create_app(Settings(data_dir=tmp_path), model)) as client:
        response = client.post("/api/alarms", json=EVENT)
        assert response.status_code == 502
        assert response.json() == {"error": "model_call_failed", "category": "RateLimitError"}
