from fastapi.testclient import TestClient

from travel_risk.api.main import app


def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_openapi_lists_planned_routes():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for p in ["/v1/advisories/sync", "/v1/orgs/{org_id}/trips/import",
              "/v1/orgs/{org_id}/assessments", "/v1/orgs/{org_id}/alerts"]:
        assert p in paths
