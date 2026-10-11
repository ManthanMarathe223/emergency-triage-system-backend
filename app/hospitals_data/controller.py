from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.database import Database

from app.hospitals_data.dto import (
    HospitalDataCreateDTO,
    HospitalDataDeleteResponseDTO,
    HospitalDataUpdateDTO,
)
from app.triage.allocation_service import reconcile_allocations_for_hospital_capacity_change
from app.utils.database import serialize_doc, to_object_id


def create_hospital_data(
    db: Database, payload: HospitalDataCreateDTO, authenticated_hospital_id: str
) -> dict[str, Any]:
    """Create a new operational data record for a hospital and sync bed summaries."""
    hosp_obj_id = to_object_id(payload.hospital_id)
    if payload.hospital_id != authenticated_hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to update this hospital.",
        )
    hospital = db.hospitals.find_one({"_id": hosp_obj_id})
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hospital with id '{payload.hospital_id}' not found.",
        )

    now = datetime.now(timezone.utc)
    doc = {
        **payload.model_dump(),
        "recorded_at": now,
        "created_at": now,
        "updated_at": now,
    }

    result = db.hospitals_data.insert_one(doc)
    doc["_id"] = result.inserted_id

    # Automatically keep the parent hospital's bed summary synchronized
    total_beds = payload.general_beds_total + payload.icu_beds_total
    available_beds = payload.general_beds_available + payload.icu_beds_available
    db.hospitals.update_one(
        {"_id": hosp_obj_id},
        {
            "$set": {
                "total_beds": total_beds,
                "available_beds": available_beds,
                "availability_updated_at": now,
                "updated_at": now,
            }
        },
    )
    reconcile_allocations_for_hospital_capacity_change(db, payload.hospital_id)

    return serialize_doc(doc)


def update_hospital_data(
    db: Database,
    data_id: str,
    payload: HospitalDataUpdateDTO,
    authenticated_hospital_id: str,
) -> dict[str, Any]:
    """Update an existing operational data record and sync bed summaries if changed."""
    data_obj_id = to_object_id(data_id)
    existing = db.hospitals_data.find_one(
        {"_id": data_obj_id, "hospital_id": authenticated_hospital_id}
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hospital operational data record with id '{data_id}' not found.",
        )

    update_fields = payload.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one operational data field must be provided.",
        )

    merged = {**existing, **update_fields}
    capacity_pairs = (
        ("general_beds_total", "general_beds_available"),
        ("icu_beds_total", "icu_beds_available"),
        ("ventilators_total", "ventilators_available"),
        ("doctors_total", "doctors_available"),
    )
    for total_field, available_field in capacity_pairs:
        if merged.get(available_field, 0) > merged.get(total_field, 0):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{available_field} cannot exceed {total_field}",
            )

    now = datetime.now(timezone.utc)
    update_fields["updated_at"] = now

    updated = db.hospitals_data.find_one_and_update(
        {"_id": data_obj_id, "hospital_id": authenticated_hospital_id},
        {"$set": update_fields},
        return_document=ReturnDocument.AFTER,
    )

    # Sync parent hospital if bed counts were changed
    hosp_id = existing.get("hospital_id")
    if hosp_id:
        try:
            hosp_obj_id = to_object_id(hosp_id)
            gen_total = updated.get("general_beds_total", 0)
            gen_avail = updated.get("general_beds_available", 0)
            icu_total = updated.get("icu_beds_total", 0)
            icu_avail = updated.get("icu_beds_available", 0)
            total = gen_total + icu_total
            avail = gen_avail + icu_avail
            db.hospitals.update_one(
                {"_id": hosp_obj_id},
                {
                    "$set": {
                        "total_beds": total,
                        "available_beds": avail,
                        "availability_updated_at": now,
                        "updated_at": now,
                    }
                },
            )
            reconcile_allocations_for_hospital_capacity_change(db, str(hosp_obj_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Hospital resource data was updated, but the hospital summary could not be synchronized.",
            ) from exc

    return serialize_doc(updated)


def delete_hospital_data(
    db: Database, data_id: str, authenticated_hospital_id: str
) -> HospitalDataDeleteResponseDTO:
    """Delete an operational data record by its ID."""
    data_obj_id = to_object_id(data_id)
    result = db.hospitals_data.delete_one(
        {"_id": data_obj_id, "hospital_id": authenticated_hospital_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hospital operational data record with id '{data_id}' not found.",
        )

    return HospitalDataDeleteResponseDTO(
        message="Hospital data deleted successfully",
        id=data_id,
    )


def get_hospital_data_by_id(
    db: Database, data_id: str, authenticated_hospital_id: str
) -> dict[str, Any]:
    """Retrieve a single operational data record by ID."""
    data_obj_id = to_object_id(data_id)
    record = db.hospitals_data.find_one(
        {"_id": data_obj_id, "hospital_id": authenticated_hospital_id}
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hospital operational data record with id '{data_id}' not found.",
        )
    return serialize_doc(record)


def get_latest_hospital_data(
    db: Database, hospital_id: str, authenticated_hospital_id: str
) -> dict[str, Any]:
    """Retrieve the most recent operational data record for a given hospital."""
    hosp_obj_id = to_object_id(hospital_id)
    if hospital_id != authenticated_hospital_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found.",
        )
    hospital = db.hospitals.find_one({"_id": hosp_obj_id})
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hospital with id '{hospital_id}' not found.",
        )

    record = db.hospitals_data.find_one(
        {"hospital_id": hospital_id},
        sort=[("recorded_at", -1), ("_id", -1)],
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No operational data found for hospital '{hospital_id}'.",
        )
    return serialize_doc(record)


def get_hospital_data_history(
    db: Database,
    hospital_id: str,
    authenticated_hospital_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Retrieve operational data history for a given hospital."""
    hosp_obj_id = to_object_id(hospital_id)
    if hospital_id != authenticated_hospital_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found.",
        )
    hospital = db.hospitals.find_one({"_id": hosp_obj_id})
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hospital with id '{hospital_id}' not found.",
        )

    records = list(
        db.hospitals_data.find({"hospital_id": hospital_id})
        .sort("recorded_at", -1)
        .limit(limit)
    )
    return [serialize_doc(r) for r in records]


def list_all_hospitals_data(
    db: Database, authenticated_hospital_id: str, limit: int = 100
) -> list[dict[str, Any]]:
    """Retrieve recent operational data entries across all hospitals."""
    records = list(
        db.hospitals_data.find(
            {"hospital_id": authenticated_hospital_id}
        ).sort("recorded_at", -1).limit(limit)
    )
    return [serialize_doc(r) for r in records]
