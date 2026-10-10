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
        "address": "1 Main Street",
        "latitude": 18.5204,
        "longitude": 73.8567,
        "total_beds": 100,
        "available_beds": 40,
        "is_active": True,
    }
    payload.update(overrides)
    return payload


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_list_and_get_hospital():
    with TestClient(app) as client:
        created = client.post("/hospitals/", json=hospital_payload())
        assert created.status_code == 201
        hospital_id = created.json()["id"]

        listed = client.get("/hospitals/")
        assert listed.status_code == 200
        assert listed.json()[0]["registration_number"] == "CGH-001"

        retrieved = client.get(f"/hospitals/{hospital_id}")
        assert retrieved.status_code == 200
        assert retrieved.json()["name"] == "City General Hospital"


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
        assert client.post(
            "/hospitals/register", json=hospital_payload(available_beds=101)
        ).status_code == 422


def test_update_hospital_details():
    with TestClient(app) as client:
        created = client.post("/hospitals/register", json=hospital_payload())
        hospital_id = created.json()["id"]

        updated = client.put(
            f"/hospitals/{hospital_id}",
            json={
                "name": "City Advanced Trauma Center",
                "contact_number": "+1-800-555-0199",
                "address": "99 Emergency Blvd",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "City Advanced Trauma Center"
        assert updated.json()["contact_number"] == "+1-800-555-0199"
        assert updated.json()["address"] == "99 Emergency Blvd"


def test_update_availability_updates_value_and_timestamp():
    with TestClient(app) as client:
        created = client.post("/hospitals/register", json=hospital_payload())
        hospital_id = created.json()["id"]
        original_timestamp = datetime.fromisoformat(
            created.json()["availability_updated_at"]
        )

        updated = client.patch(
            f"/hospitals/{hospital_id}/availability",
            json={"total_beds": 120, "available_beds": 75},
        )
        assert updated.status_code == 200
        assert updated.json()["available_beds"] == 75
        assert updated.json()["total_beds"] == 120
        assert (
            datetime.fromisoformat(updated.json()["availability_updated_at"])
            >= original_timestamp
        )


def test_register_and_login_hospital():
    with TestClient(app) as client:
        reg_payload = hospital_payload(
            registration_number="HOSP-AUTH-1",
            password="securepassword123",
        )
        response = client.post("/hospitals/register", json=reg_payload)
        assert response.status_code == 201
        data = response.json()
        assert data["registration_number"] == "HOSP-AUTH-1"
        assert "password" not in data
        assert "password_hash" not in data

        # Login with valid credentials
        login_response = client.post(
            "/hospitals/login",
            json={
                "registration_number": "HOSP-AUTH-1",
                "password": "securepassword123",
            },
        )
        assert login_response.status_code == 200
        login_data = login_response.json()
        assert login_data["message"] == "Login successful"
        assert login_data["hospital"]["registration_number"] == "HOSP-AUTH-1"

        # Login with invalid password
        bad_pw_response = client.post(
            "/hospitals/login",
            json={
                "registration_number": "HOSP-AUTH-1",
                "password": "wrongpassword",
            },
        )
        assert bad_pw_response.status_code == 401
        assert "Invalid registration number or password" in bad_pw_response.json()["detail"]

        # Login with unknown registration number
        not_found_response = client.post(
            "/hospitals/login",
            json={
                "registration_number": "NON-EXISTENT",
                "password": "anypassword",
            },
        )
        assert not_found_response.status_code == 401


def test_missing_hospital_returns_not_found():
    dummy_id = "507f1f77bcf86cd799439011"
    with TestClient(app) as client:
        assert client.get(f"/hospitals/{dummy_id}").status_code == 404
        assert (
            client.patch(
                f"/hospitals/{dummy_id}/availability",
                json={"total_beds": 10, "available_beds": 5},
            ).status_code
            == 404
        )
