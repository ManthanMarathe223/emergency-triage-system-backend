import os
from datetime import datetime

os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient

from app.main import app
from app.utils.database import get_database, init_db


def setup_function():
    db = get_database()
    db.hospitals.drop()
    db.hospitals_data.drop()
    init_db()


def hospital_payload(**overrides):
    payload = {
        "name": "City General Hospital",
        "registration_number": "CGH-001",
        "password": "securepassword123",
        "address": "1 Main Street",
        "latitude": 18.5204,
        "longitude": 73.8567,
        "total_beds": 100,
        "available_beds": 40,
        "is_active": True,
    }
    payload.update(overrides)
    return payload


def authenticate(client: TestClient, registration_number="CGH-001"):
    response = client.post(
        "/hospitals/login",
        json={
            "registration_number": registration_number,
            "password": "securepassword123",
        },
    )
    assert response.status_code == 200
    client.headers.update(
        {"Authorization": f"Bearer {response.json()['access_token']}"}
    )


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_private_hospital_routes_require_access_token():
    with TestClient(app) as client:
        assert client.get("/hospitals/").status_code == 401
        assert client.get("/hospitals/not-an-object-id").status_code == 401


def test_create_list_and_get_hospital():
    with TestClient(app) as client:
        created = client.post("/hospitals/", json=hospital_payload())
        assert created.status_code == 201
        hospital_id = created.json()["id"]
        authenticate(client)

        listed = client.get("/hospitals/")
        assert listed.status_code == 200
        assert listed.json()[0]["registration_number"] == "CGH-001"

        retrieved = client.get(f"/hospitals/{hospital_id}")
        assert retrieved.status_code == 200
        assert retrieved.json()["name"] == "City General Hospital"


def test_public_hospital_summary_requires_no_login():
    with TestClient(app) as client:
        client.post("/hospitals/", json=hospital_payload())
        response = client.get("/hospitals/public")
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": response.json()[0]["id"],
            "name": "City General Hospital",
            "address": "1 Main Street",
            "latitude": 18.5204,
            "longitude": 73.8567,
        }
    ]


def test_duplicate_registration_is_rejected():
    with TestClient(app) as client:
        assert client.post("/hospitals/register", json=hospital_payload()).status_code == 201
        duplicate = client.post(
            "/hospitals/register", json=hospital_payload(name="Another Hospital")
        )
    assert duplicate.status_code == 409


def test_invalid_coordinates_and_bed_values_are_rejected():
    with TestClient(app) as client:
        assert client.post("/hospitals/register", json=hospital_payload(latitude=91)).status_code == 422
        assert client.post("/hospitals/register", json=hospital_payload(longitude=-181)).status_code == 422
        assert client.post("/hospitals/register", json=hospital_payload(total_beds=-1)).status_code == 422
        assert client.post("/hospitals/register", json=hospital_payload(available_beds=101)).status_code == 422


def test_update_hospital_details():
    with TestClient(app) as client:
        created = client.post("/hospitals/register", json=hospital_payload())
        hospital_id = created.json()["id"]
        authenticate(client)
        updated = client.put(
            f"/hospitals/{hospital_id}",
            json={"name": "City Advanced Trauma Center", "address": "99 Emergency Blvd"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "City Advanced Trauma Center"
        assert "created_at" not in updated.json()


def test_update_availability_updates_value_and_timestamp():
    with TestClient(app) as client:
        created = client.post("/hospitals/register", json=hospital_payload())
        hospital_id = created.json()["id"]
        authenticate(client)
        original_timestamp = datetime.fromisoformat(created.json()["availability_updated_at"])
        updated = client.patch(
            f"/hospitals/{hospital_id}/availability",
            json={"total_beds": 120, "available_beds": 75},
        )
        assert updated.status_code == 200
        assert updated.json()["available_beds"] == 75
        assert datetime.fromisoformat(updated.json()["availability_updated_at"]) >= original_timestamp


def test_login_refresh_and_invalid_tokens():
    with TestClient(app) as client:
        client.post("/hospitals/register", json=hospital_payload())
        login = client.post(
            "/hospitals/login",
            json={"registration_number": "CGH-001", "password": "securepassword123"},
        )
        assert login.status_code == 200
        tokens = login.json()
        assert tokens["token_type"] == "bearer"

        refreshed = client.post("/hospitals/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"]
        assert client.post("/hospitals/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
        assert client.post(
            "/hospitals/login",
            json={"registration_number": "CGH-001", "password": "wrongpassword"},
        ).status_code == 401


def test_missing_hospital_returns_not_found():
    with TestClient(app) as client:
        client.post("/hospitals/register", json=hospital_payload())
        authenticate(client)
        dummy_id = "507f1f77bcf86cd799439011"
        assert client.get(f"/hospitals/{dummy_id}").status_code == 404
        assert client.get("/hospitals/not-an-object-id").status_code == 400


def test_empty_update_is_rejected():
    with TestClient(app) as client:
        created = client.post("/hospitals/register", json=hospital_payload())
        authenticate(client)
        assert client.patch(f"/hospitals/{created.json()['id']}", json={}).status_code == 422
