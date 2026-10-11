from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo.database import Database

from app.triage.controller import recommend_hospitals
from app.triage.dto import (
    AllocationBatchRequestDTO,
    AllocationReplanDTO,
    BatchAllocationPatientDTO,
    TriageRecommendRequestDTO,
)
from app.triage.rules import assess_patient, resources_needed

PRIORITY_ORDER = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
ALLOCATION_RESOURCE_FIELDS = {
    "GENERAL_BED": ("general_beds_total", "general_beds_available"),
    "ICU_BED": ("icu_beds_total", "icu_beds_available"),
    "VENTILATOR": ("ventilators_total", "ventilators_available"),
}


def _as_utc(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _priority_for_severity(severity: str) -> int:
    return PRIORITY_ORDER.get(severity.lower(), 99)


def _reserve_usage(db: Database, hospital_id: str) -> dict[str, int]:
    usage: dict[str, int] = {}
    for allocation in db.triage_allocations.find(
        {"assigned_hospital_id": hospital_id, "status": "ALLOCATED"},
        {"reserved_resources": 1},
    ):
        for resource, qty in (allocation.get("reserved_resources") or {}).items():
            usage[resource] = usage.get(resource, 0) + int(qty)
    return usage


def _snapshot_fields(snapshot: dict[str, Any]) -> dict[str, int]:
    values: dict[str, int] = {}
    for key, (total_field, available_field) in ALLOCATION_RESOURCE_FIELDS.items():
        total = int(snapshot.get(total_field, 0) or 0)
        available = int(snapshot.get(available_field, 0) or 0)
        values[key] = min(total, max(0, available))
    return values


def _latest_snapshot_for_hospital(db: Database, hospital_id: str) -> Optional[dict[str, Any]]:
    if hospital_id is None:
        return None
    return db.hospitals_data.find_one({"hospital_id": hospital_id}, sort=[("recorded_at", -1), ("_id", -1)])


def _current_capacity_for_hospital(db: Database, hospital_id: str) -> tuple[Optional[dict[str, Any]], dict[str, int]]:
    snapshot = _latest_snapshot_for_hospital(db, hospital_id)
    return snapshot, _snapshot_fields(snapshot or {})


def _patient_payload(patient: BatchAllocationPatientDTO) -> dict[str, Any]:
    return {
        "latitude": patient.latitude,
        "longitude": patient.longitude,
        "symptoms": patient.symptoms,
        "vitals": patient.vitals.model_dump(),
        "age": patient.age,
        "described_as_severe": patient.described_as_severe,
        "max_results": 20,
    }


def _sort_key_for_patient(patient: BatchAllocationPatientDTO, index: int) -> tuple[int, datetime, int]:
    assessment = assess_patient(
        patient.symptoms,
        patient.vitals.model_dump(),
        age=patient.age,
        described_as_severe=patient.described_as_severe,
    )
    timestamp = _as_utc(patient.created_at)
    return (_priority_for_severity(assessment["severity"]), timestamp, index)


def _eligible_hospital_candidates(db: Database, patient: BatchAllocationPatientDTO) -> list[dict[str, Any]]:
    payload = TriageRecommendRequestDTO.model_validate(_patient_payload(patient))
    response = recommend_hospitals(db, payload)
    return response.get("recommended", [])


def _can_honor_resources(db: Database, hospital_id: str, resources: list[str]) -> bool:
    snapshot, available = _current_capacity_for_hospital(db, hospital_id)
    if not snapshot:
        return False
    usage = _reserve_usage(db, hospital_id)
    for resource in resources:
        available_units = available.get(resource, 0) - usage.get(resource, 0)
        if available_units < 1:
            return False
    return True


def _build_allocation_record(
    patient: BatchAllocationPatientDTO,
    hospital_id: str,
    travel_minutes: int,
    reserved_resources: dict[str, int],
) -> dict[str, Any]:
    assessment = assess_patient(
        patient.symptoms,
        patient.vitals.model_dump(),
        age=patient.age,
        described_as_severe=patient.described_as_severe,
    )
    now = datetime.now(timezone.utc)
    return {
        "_id": ObjectId(),
        "patient_id": patient.patient_id,
        "status": "ALLOCATED",
        "assigned_hospital_id": hospital_id,
        "priority": assessment["severity"],
        "severity": assessment["severity"],
        "triage": {
            "severity": assessment["severity"],
            "urgency_level": "CRITICAL" if assessment["severity"] == "critical" else "HIGH" if assessment["severity"] == "high" else "MEDIUM" if assessment["severity"] == "moderate" else "LOW",
            "score": assessment["score"],
            "reasons": assessment["reasons"],
            "required_resources": resources_needed(assessment["required"]),
        },
        "travel_minutes": travel_minutes,
        "reserved_resources": reserved_resources,
        "patient_payload": {
            "latitude": patient.latitude,
            "longitude": patient.longitude,
            "symptoms": patient.symptoms,
            "vitals": patient.vitals.model_dump(),
            "age": patient.age,
            "described_as_severe": patient.described_as_severe,
        },
        "created_at": now,
        "updated_at": now,
        "history": [],
    }


def allocate_batch_patients(db: Database, payload: AllocationBatchRequestDTO) -> dict[str, Any]:
    if not payload.patients:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one patient must be included in the batch.")
    if len(payload.patients) > 50:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Batch size cannot exceed 50 patients.")

    ordered = []
    seen: set[str] = set()
    for index, patient in enumerate(payload.patients):
        if patient.patient_id in seen:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Duplicate patient_id '{patient.patient_id}'.")
        seen.add(patient.patient_id)
        ordered.append((index, patient))
    ordered.sort(key=lambda item: _sort_key_for_patient(item[1], item[0]))

    results: list[dict[str, Any]] = []
    for _, patient in ordered:
        assessment = assess_patient(
            patient.symptoms,
            patient.vitals.model_dump(),
            age=patient.age,
            described_as_severe=patient.described_as_severe,
        )
        needed_resources = resources_needed(assessment["required"])
        chosen_hospital = None
        for hospital in _eligible_hospital_candidates(db, patient):
            hospital_id = str(hospital["hospital_id"])
            if _can_honor_resources(db, hospital_id, needed_resources):
                chosen_hospital = hospital
                break
        if chosen_hospital is None:
            results.append({
                "patient_id": patient.patient_id,
                "status": "UNALLOCATED",
                "priority": assessment["severity"],
                "severity": assessment["severity"],
                "hospital_id": None,
                "estimated_travel_minutes": None,
                "reserved_resources": {},
                "reason": "No eligible hospital had enough verified resources to safely accommodate the patient.",
            })
            continue

        hospital_id = str(chosen_hospital["hospital_id"])
        reserved = {resource: 1 for resource in needed_resources}
        record = _build_allocation_record(patient, hospital_id, int(chosen_hospital.get("estimated_travel_minutes", 0) or 0), reserved)
        db.triage_allocations.insert_one(record)
        results.append({
            "patient_id": patient.patient_id,
            "status": "ALLOCATED",
            "priority": assessment["severity"],
            "severity": assessment["severity"],
            "hospital_id": hospital_id,
            "estimated_travel_minutes": int(chosen_hospital.get("estimated_travel_minutes", 0) or 0),
            "reserved_resources": reserved,
            "reason": f"Assigned to {chosen_hospital.get('name', hospital_id)}.",
        })

    return {
        "batch_id": str(ObjectId()),
        "generated_at": datetime.now(timezone.utc),
        "results": results,
    }


def reject_allocation(db: Database, allocation_id: str, reason: str, notes: Optional[str], hospital_id: str) -> dict[str, Any]:
    allocation = db.triage_allocations.find_one({"_id": ObjectId(allocation_id)})
    if allocation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allocation not found.")
    current_status = allocation.get("status")
    if current_status in {"REJECTED", "CANCELLED", "COMPLETED", "UNALLOCATED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This allocation is no longer active and cannot be rejected.")
    if str(allocation.get("assigned_hospital_id") or "") != hospital_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This hospital is not assigned to this allocation.")

    db.triage_allocations.update_one(
        {"_id": ObjectId(allocation_id)},
        {"$set": {"status": "REJECTED", "reserved_resources": {}, "updated_at": datetime.now(timezone.utc)}},
    )
    db.triage_allocations.update_one(
        {"_id": ObjectId(allocation_id)},
        {"$push": {"history": {"event": "REJECTED", "timestamp": datetime.now(timezone.utc), "hospital_id": hospital_id, "reason": reason, "notes": notes}}},
    )

    patient_payload = allocation.get("patient_payload") or {}
    allocation_patient = BatchAllocationPatientDTO.model_validate({
        "patient_id": allocation["patient_id"],
        "latitude": patient_payload.get("latitude"),
        "longitude": patient_payload.get("longitude"),
        "symptoms": patient_payload.get("symptoms", []),
        "vitals": patient_payload.get("vitals", {}),
        "age": patient_payload.get("age"),
        "described_as_severe": patient_payload.get("described_as_severe", False),
    })
    request = AllocationBatchRequestDTO(patients=[allocation_patient])
    result = allocate_batch_patients(db, request)["results"][0]

    db.triage_allocations.update_one(
        {"_id": ObjectId(allocation_id)},
        {"$set": {
            "status": result["status"],
            "assigned_hospital_id": result.get("hospital_id"),
            "travel_minutes": result.get("estimated_travel_minutes"),
            "reserved_resources": result.get("reserved_resources") or {},
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    db.triage_allocations.update_one(
        {"_id": ObjectId(allocation_id)},
        {"$push": {"history": {"event": "REPLAN_AFTER_REJECTION", "timestamp": datetime.now(timezone.utc), "result": result}}},
    )
    return {"allocation_id": allocation_id, "status": result["status"], "hospital_id": result.get("hospital_id")}


def cancel_allocation(db: Database, allocation_id: str) -> dict[str, Any]:
    allocation = db.triage_allocations.find_one({"_id": ObjectId(allocation_id)})
    if allocation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allocation not found.")
    if allocation.get("status") not in {"ALLOCATED", "REJECTED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This allocation cannot be cancelled in its current state.")
    db.triage_allocations.update_one(
        {"_id": ObjectId(allocation_id)},
        {"$set": {"status": "CANCELLED", "reserved_resources": {}, "updated_at": datetime.now(timezone.utc)}},
    )
    db.triage_allocations.update_one(
        {"_id": ObjectId(allocation_id)},
        {"$push": {"history": {"event": "CANCELLED", "timestamp": datetime.now(timezone.utc)}}},
    )
    return {"allocation_id": allocation_id, "status": "CANCELLED"}


def complete_allocation(db: Database, allocation_id: str) -> dict[str, Any]:
    allocation = db.triage_allocations.find_one({"_id": ObjectId(allocation_id)})
    if allocation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allocation not found.")
    if allocation.get("status") not in {"ALLOCATED", "REJECTED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This allocation cannot be completed in its current state.")
    db.triage_allocations.update_one(
        {"_id": ObjectId(allocation_id)},
        {"$set": {"status": "COMPLETED", "reserved_resources": {}, "updated_at": datetime.now(timezone.utc)}},
    )
    db.triage_allocations.update_one(
        {"_id": ObjectId(allocation_id)},
        {"$push": {"history": {"event": "COMPLETED", "timestamp": datetime.now(timezone.utc)}}},
    )
    return {"allocation_id": allocation_id, "status": "COMPLETED"}


def replan_allocation(db: Database, allocation_id: str, payload: AllocationReplanDTO) -> dict[str, Any]:
    allocation = db.triage_allocations.find_one({"_id": ObjectId(allocation_id)})
    if allocation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allocation not found.")
    if allocation.get("status") not in {"ALLOCATED", "REJECTED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This allocation is not active and cannot be replanned.")

    previous_hospital = allocation.get("assigned_hospital_id")
    previous_travel = allocation.get("travel_minutes")
    if previous_hospital:
        db.triage_allocations.update_one(
            {"_id": ObjectId(allocation_id)},
            {"$set": {"status": "REPLAN_PENDING", "reserved_resources": {}, "updated_at": datetime.now(timezone.utc)}},
        )

    patient_payload = allocation.get("patient_payload") or {}
    lat = payload.latitude if payload.latitude is not None else patient_payload.get("latitude")
    lon = payload.longitude if payload.longitude is not None else patient_payload.get("longitude")
    if lat is None or lon is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A valid patient latitude and longitude are required.")

    patient = BatchAllocationPatientDTO.model_validate({
        "patient_id": allocation["patient_id"],
        "latitude": lat,
        "longitude": lon,
        "symptoms": patient_payload.get("symptoms", []),
        "vitals": patient_payload.get("vitals", {}),
        "age": patient_payload.get("age"),
        "described_as_severe": patient_payload.get("described_as_severe", False),
    })
    result = allocate_batch_patients(db, AllocationBatchRequestDTO(patients=[patient]))["results"][0]
    if result["status"] == "ALLOCATED":
        db.triage_allocations.update_one(
            {"_id": ObjectId(allocation_id)},
            {"$set": {
                "status": "ALLOCATED",
                "assigned_hospital_id": result.get("hospital_id"),
                "travel_minutes": result.get("estimated_travel_minutes"),
                "reserved_resources": result.get("reserved_resources") or {},
                "updated_at": datetime.now(timezone.utc),
            }},
        )
    else:
        db.triage_allocations.update_one(
            {"_id": ObjectId(allocation_id)},
            {"$set": {
                "status": "UNALLOCATED",
                "assigned_hospital_id": None,
                "travel_minutes": None,
                "reserved_resources": {},
                "updated_at": datetime.now(timezone.utc),
            }},
        )

    db.triage_allocations.update_one(
        {"_id": ObjectId(allocation_id)},
        {"$push": {
            "history": {
                "event": "REPLAN",
                "timestamp": datetime.now(timezone.utc),
                "reason": payload.reason,
                "notes": payload.notes,
                "previous_hospital_id": previous_hospital,
                "new_hospital_id": result.get("hospital_id"),
                "previous_travel_minutes": previous_travel,
                "new_travel_minutes": result.get("estimated_travel_minutes"),
                "outcome": result["status"],
            }
        }},
    )
    return {
        "allocation_id": allocation_id,
        "status": result["status"],
        "hospital_id": result.get("hospital_id"),
        "reason": result.get("reason"),
    }


def reconcile_allocations_for_hospital_capacity_change(db: Database, hospital_id: str) -> list[str]:
    affected: list[str] = []
    for allocation in db.triage_allocations.find({"assigned_hospital_id": hospital_id, "status": "ALLOCATED"}):
        payload = allocation.get("patient_payload") or {}
        patient = BatchAllocationPatientDTO.model_validate({
            "patient_id": allocation["patient_id"],
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "symptoms": payload.get("symptoms", []),
            "vitals": payload.get("vitals", {}),
            "age": payload.get("age"),
            "described_as_severe": payload.get("described_as_severe", False),
        })
        assessment = assess_patient(
            patient.symptoms,
            patient.vitals.model_dump(),
            age=patient.age,
            described_as_severe=patient.described_as_severe,
        )
        if _can_honor_resources(db, hospital_id, resources_needed(assessment["required"])):
            continue
        db.triage_allocations.update_one(
            {"_id": allocation["_id"]},
            {"$set": {"status": "UNALLOCATED", "reserved_resources": {}, "updated_at": datetime.now(timezone.utc)}},
        )
        affected.append(str(allocation["_id"]))
    return affected
