def test_health_endpoint(client):
    """
    Acceptance check: GET /api/health returns ok.
    """
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mock_adapter"] == "MOCK_APAAR_V1"
    assert data["synthetic"] is True


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "OPERATIONAL"
    assert data["mock_adapter"] == "MOCK_APAAR_V1"
