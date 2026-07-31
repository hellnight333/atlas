from fastapi.testclient import TestClient

from atlas_kernel.api import app


def test_runs_endpoint_returns_list():
    client = TestClient(app)
    response = client.get('/runs')
    assert response.status_code == 200
    assert isinstance(response.json(), list)
