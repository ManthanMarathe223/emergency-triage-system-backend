import os

os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient

from app.main import app
from app.utils.database import get_database, init_db


def setup_function():
    db = get_database()
    db.hospitals.drop()
    db.hospitals_data.drop()
    init_db()


def create_sample_hospital(client: TestClient) -> str:
    res = client.post(
        "/hospitals/register",
        json={
            "name": "Metro Trauma Center",
            "registration_number": "MTC-999",
            "password": "securepassword123",
            "address": "45 Emergency Blvd",
            "latitude": 19.076,
            "longitude": 72.877,
            "total_beds": 100,
            "available_beds": 50,
            "is_active": True,
        },
    )
    assert res.status_code == 201
    token = client.post(
        "/hospitals/login",
        json={
            "registration_number": "MTC-999",
            "password": "securepassword123",
        },
    )
    assert token.status_code == 200
    client.headers.update(
        {"Authorization": f"Bearer {token.json()['access_token']}"}
    )
    return res.json()["id"]


def test_create_and_fetch_hospital_data():
    with TestClient(app) as client:
        hosp_id = create_sample_hospital(client)

        payload = {
            "hospital_id": hosp_id,
            "doctors": [
                {
                    "doctor_id": "DOC-001",
                    "name": "Dr. Asha Rao",
                    "specialization": "Emergency Medicine",
                    "is_available": True,
                },
                {
                    "doctor_id": "DOC-002",
                    "name": "Dr. Vikram Shah",
                    "specialization": "Critical Care",
                    "is_available": False,
                },
            ],
            "general_beds_total": 80,
            "general_beds_available": 30,
            "icu_beds_total": 20,
            "icu_beds_available": 5,
            "ventilators_total": 15,
            "ventilators_available": 4,
            "oxygen_cylinders": 50,
            "doctors_total": 12,
            "doctors_available": 6,
            "triage_status": "NORMAL",
            "notes": "Shift handover: 6 doctors active on ER floor.",
        }

        created = client.post("/hospitals-data/", json=payload)
        assert created.status_code == 201
        data = created.json()
        assert data["hospital_id"] == hosp_id
        assert data["icu_beds_available"] == 5
        assert data["doctors_total"] == 12
        assert data["doctors_available"] == 6
        assert data["triage_status"] == "NORMAL"
        assert data["doctors"][0]["doctor_id"] == "DOC-001"
        assert data["doctors"][0]["is_available"] is True
        assert data["doctors"][1]["is_available"] is False
        assert "created_at" not in data
        assert "updated_at" not in data
        data_id = data["id"]

        # Check get single record endpoint
        single = client.get(f"/hospitals-data/{data_id}")
        assert single.status_code == 200
        assert single.json()["id"] == data_id
        assert single.json()["doctors_available"] == 6

        # Check latest endpoint
        latest = client.get(f"/hospitals-data/hospital/{hosp_id}/latest")
        assert latest.status_code == 200
        assert latest.json()["id"] == data_id
        assert latest.json()["oxygen_cylinders"] == 50

        # Check history endpoint
        history = client.get(f"/hospitals-data/hospital/{hosp_id}/history")
        assert history.status_code == 200
        assert len(history.json()) == 1

        # Check list all endpoint
        all_data = client.get("/hospitals-data/")
        assert all_data.status_code == 200
        assert len(all_data.json()) >= 1


def test_update_and_delete_hospital_data():
    with TestClient(app) as client:
        hosp_id = create_sample_hospital(client)

        created = client.post(
            "/hospitals-data/",
            json={
                "hospital_id": hosp_id,
                "general_beds_total": 50,
                "general_beds_available": 20,
                "icu_beds_total": 10,
                "icu_beds_available": 3,
                "doctors_total": 8,
                "doctors_available": 4,
                "triage_status": "NORMAL",
            },
        )
        assert created.status_code == 201
        data_id = created.json()["id"]

        # Update data (elevate triage, change doctors)
        updated = client.put(
            f"/hospitals-data/{data_id}",
            json={
                "triage_status": "ELEVATED",
                "doctors_available": 2,
                "notes": "Mass casualty surge incoming.",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["triage_status"] == "ELEVATED"
        assert updated.json()["doctors_available"] == 2
        assert updated.json()["notes"] == "Mass casualty surge incoming."

        # Delete data
        deleted = client.delete(f"/hospitals-data/{data_id}")
        assert deleted.status_code == 200
        assert deleted.json()["message"] == "Hospital data deleted successfully"

        # Verify not found after deletion
        assert client.get(f"/hospitals-data/{data_id}").status_code == 404


def test_partial_resource_update_cannot_exceed_existing_capacity():
    with TestClient(app) as client:
        hosp_id = create_sample_hospital(client)
        created = client.post(
            "/hospitals-data/",
            json={
                "hospital_id": hosp_id,
                "general_beds_total": 10,
                "general_beds_available": 5,
            },
        )
        data_id = created.json()["id"]

        response = client.patch(
            f"/hospitals-data/{data_id}",
            json={"general_beds_available": 11},
        )
        assert response.status_code == 422
        assert client.patch(f"/hospitals-data/{data_id}", json={}).status_code == 422


def test_doctor_details_are_required_and_validated():
    with TestClient(app) as client:
        hosp_id = create_sample_hospital(client)
        invalid_doctor = client.post(
            "/hospitals-data/",
            json={
                "hospital_id": hosp_id,
                "doctors": [
                    {
                        "doctor_id": "DOC-INVALID",
                        "name": "Dr. Invalid",
                        "specialization": "Emergency Medicine",
                    }
                ],
            },
        )
        assert invalid_doctor.status_code == 422

        blank_doctor = client.post(
            "/hospitals-data/",
            json={
                "hospital_id": hosp_id,
                "doctors": [
                    {
                        "doctor_id": " ",
                        "name": "Dr. Blank",
                        "specialization": "Emergency Medicine",
                        "is_available": True,
                    }
                ],
            },
        )
        assert blank_doctor.status_code == 422


def test_hospital_data_for_invalid_hospital_fails():
    dummy_id = "507f1f77bcf86cd799439011"
    with TestClient(app) as client:
        create_sample_hospital(client)
        payload = {
            "hospital_id": dummy_id,
            "general_beds_total": 50,
            "general_beds_available": 20,
            "icu_beds_total": 10,
            "icu_beds_available": 2,
            "ventilators_total": 5,
            "ventilators_available": 1,
            "oxygen_cylinders": 10,
            "doctors_total": 5,
            "doctors_available": 2,
            "triage_status": "NORMAL",
        }
        res = client.post("/hospitals-data/", json=payload)
        assert res.status_code == 403
        assert "authorized" in res.json()["detail"].lower()


def test_hospital_data_validation_errors():
    with TestClient(app) as client:
        hosp_id = create_sample_hospital(client)

        # available beds exceeds total beds
        res = client.post(
            "/hospitals-data/",
            json={
                "hospital_id": hosp_id,
                "general_beds_total": 10,
                "general_beds_available": 20,
            },
        )
        assert res.status_code == 422

        # available doctors exceeds total doctors
        res_doc = client.post(
            "/hospitals-data/",
            json={
                "hospital_id": hosp_id,
                "doctors_total": 5,
                "doctors_available": 10,
            },
        )
        assert res_doc.status_code == 422


def test_hospital_cannot_access_another_hospitals_operational_data():
    with TestClient(app) as client:
        first_id = create_sample_hospital(client)
        created = client.post(
            "/hospitals-data/",
            json={"hospital_id": first_id, "general_beds_total": 10},
        )
        assert created.status_code == 201
        data_id = created.json()["id"]

        second = client.post(
            "/hospitals/register",
            json={
                "name": "Second Hospital",
                "registration_number": "MTC-1000",
                "password": "securepassword123",
                "address": "46 Emergency Blvd",
                "latitude": 19.077,
                "longitude": 72.873,
            },
        )
        assert second.status_code == 201
        token = client.post(
            "/hospitals/login",
            json={
                "registration_number": "MTC-1000",
                "password": "securepassword123",
            },
        )
        client.headers.update(
            {"Authorization": f"Bearer {token.json()['access_token']}"}
        )

        assert client.get(f"/hospitals-data/{data_id}").status_code == 404
        assert client.delete(f"/hospitals-data/{data_id}").status_code == 404
        assert client.post(
            "/hospitals-data/",
            json={"hospital_id": first_id, "general_beds_total": 20},
        ).status_code == 403
