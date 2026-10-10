import os
from datetime import datetime
from pathlib import Path

os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


TEST_DATABASE_PATH = Path(__file__).with_name("test_hospitals.sqlite")
test_engine = create_engine(
    f"sqlite:///{TEST_DATABASE_PATH}",
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def setup_function():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)


def teardown_module():
    app.dependency_overrides.clear()
    test_engine.dispose()
    if TEST_DATABASE_PATH.exists():
        TEST_DATABASE_PATH.unlink()


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
        assert client.post("/hospitals/", json=hospital_payload()).status_code == 201
        duplicate = client.post("/hospitals/", json=hospital_payload(name="Another Hospital"))
    assert duplicate.status_code == 409


def test_invalid_coordinates_and_bed_values_are_rejected():
    with TestClient(app) as client:
        assert client.post("/hospitals/", json=hospital_payload(latitude=91)).status_code == 422
        assert client.post("/hospitals/", json=hospital_payload(longitude=-181)).status_code == 422
        assert client.post("/hospitals/", json=hospital_payload(total_beds=-1)).status_code == 422
        assert client.post(
            "/hospitals/", json=hospital_payload(available_beds=101)
        ).status_code == 422


def test_update_availability_updates_value_and_timestamp():
    with TestClient(app) as client:
        created = client.post("/hospitals/", json=hospital_payload())
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
        assert datetime.fromisoformat(updated.json()["availability_updated_at"]) >= original_timestamp


def test_missing_hospital_returns_not_found():
    with TestClient(app) as client:
        assert client.get("/hospitals/999").status_code == 404
        assert client.patch(
            "/hospitals/999/availability",
            json={"total_beds": 10, "available_beds": 5},
        ).status_code == 404


def test_records_persist_in_isolated_database():
    with TestClient(app) as client:
        assert client.post("/hospitals/", json=hospital_payload()).status_code == 201

    with TestClient(app) as new_client:
        response = new_client.get("/hospitals/")
    assert response.status_code == 200
    assert len(response.json()) == 1
