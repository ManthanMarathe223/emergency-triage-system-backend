from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.hospitals.dto import (
    HospitalAvailabilityUpdateDTO,
    HospitalLoginDTO,
    HospitalLoginResponseDTO,
    HospitalRegisterDTO,
    HospitalResponseDTO,
    HospitalUpdateDTO,
)
from app.utils.database import serialize_doc, to_object_id
from app.utils.security import hash_password, verify_password


def register_hospital(db: Database, payload: HospitalRegisterDTO) -> dict[str, Any]:
    """Register a new hospital in MongoDB collection 'hospitals'."""
    # Check if a hospital with this registration number already exists
    existing = db.hospitals.find_one({"registration_number": payload.registration_number})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A hospital with this registration_number already exists.",
        )

    now = datetime.now(timezone.utc)
    dump = payload.model_dump()
    raw_password = dump.pop("password", None)
    password_hash = hash_password(raw_password) if raw_password else None

    hospital_doc = {
        **dump,
        "password_hash": password_hash,
        "availability_updated_at": now,
        "created_at": now,
        "updated_at": now,
    }

    try:
        result = db.hospitals.insert_one(hospital_doc)
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A hospital with this registration_number already exists.",
        ) from exc

    hospital_doc["_id"] = result.inserted_id
    return serialize_doc(hospital_doc)


def login_hospital(db: Database, payload: HospitalLoginDTO) -> HospitalLoginResponseDTO:
    """Verify hospital registration number and password without JWT."""
    hospital = db.hospitals.find_one({"registration_number": payload.registration_number})
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid registration number or password.",
        )

    stored_hash = hospital.get("password_hash")
    if stored_hash and not verify_password(payload.password, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid registration number or password.",
        )

    serialized = serialize_doc(hospital)
    return HospitalLoginResponseDTO(
        message="Login successful",
        hospital=HospitalResponseDTO.model_validate(serialized),
    )


def update_hospital(
    db: Database, hospital_id: str, payload: HospitalUpdateDTO
) -> dict[str, Any]:
    """Update general hospital details in MongoDB."""
    obj_id = to_object_id(hospital_id)
    hospital = db.hospitals.find_one({"_id": obj_id})
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hospital with id '{hospital_id}' not found.",
        )

    update_fields = payload.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one hospital field must be provided.",
        )

    now = datetime.now(timezone.utc)
    update_fields["updated_at"] = now

    # If beds are being updated, check consistency with current values
    current_total = update_fields.get("total_beds", hospital.get("total_beds", 0))
    current_avail = update_fields.get("available_beds", hospital.get("available_beds", 0))
    if current_avail > current_total:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="available_beds cannot exceed total_beds",
        )

    if "total_beds" in update_fields or "available_beds" in update_fields:
        update_fields["availability_updated_at"] = now

    updated = db.hospitals.find_one_and_update(
        {"_id": obj_id},
        {"$set": update_fields},
        return_document=ReturnDocument.AFTER,
    )
    return serialize_doc(updated)


def update_hospital_availability(
    db: Database, hospital_id: str, payload: HospitalAvailabilityUpdateDTO
) -> dict[str, Any]:
    """Update bed availability for a hospital."""
    obj_id = to_object_id(hospital_id)
    hospital = db.hospitals.find_one({"_id": obj_id})
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hospital with id '{hospital_id}' not found.",
        )

    now = datetime.now(timezone.utc)
    update_fields = {
        "total_beds": payload.total_beds,
        "available_beds": payload.available_beds,
        "availability_updated_at": now,
        "updated_at": now,
    }

    updated = db.hospitals.find_one_and_update(
        {"_id": obj_id},
        {"$set": update_fields},
        return_document=ReturnDocument.AFTER,
    )
    return serialize_doc(updated)


def get_hospital_by_id(db: Database, hospital_id: str) -> dict[str, Any]:
    """Retrieve hospital details by ID."""
    obj_id = to_object_id(hospital_id)
    hospital = db.hospitals.find_one({"_id": obj_id})
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hospital with id '{hospital_id}' not found.",
        )
    return serialize_doc(hospital)


def list_hospitals(db: Database) -> list[dict[str, Any]]:
    """Retrieve all hospitals ordered by creation date."""
    hospitals = list(db.hospitals.find().sort("created_at", 1))
    return [serialize_doc(h) for h in hospitals]
