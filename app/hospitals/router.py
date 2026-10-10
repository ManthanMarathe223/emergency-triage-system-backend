from typing import Any

from fastapi import APIRouter, Depends, status
from pymongo.database import Database

from app.hospitals.controller import (
    get_hospital_by_id,
    list_hospitals,
    login_hospital,
    register_hospital,
    update_hospital,
    update_hospital_availability,
)
from app.hospitals.dto import (
    HospitalAvailabilityUpdateDTO,
    HospitalLoginDTO,
    HospitalLoginResponseDTO,
    HospitalRegisterDTO,
    HospitalResponseDTO,
    HospitalUpdateDTO,
)
from app.utils.database import get_db

router = APIRouter(prefix="/hospitals", tags=["hospitals"])


@router.post(
    "/register",
    response_model=HospitalResponseDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new hospital",
)
def register_hospital_endpoint(
    payload: HospitalRegisterDTO,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Register a new hospital with bed capacity and optional credentials."""
    return register_hospital(db, payload)


@router.post(
    "/",
    response_model=HospitalResponseDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new hospital (Root alias)",
    include_in_schema=False,
)
def register_hospital_alias_endpoint(
    payload: HospitalRegisterDTO,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Backwards-compatible alias for registering a hospital at POST /hospitals/."""
    return register_hospital(db, payload)


@router.post(
    "/login",
    response_model=HospitalLoginResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Hospital simple login",
)
def login_hospital_endpoint(
    payload: HospitalLoginDTO,
    db: Database = Depends(get_db),
) -> HospitalLoginResponseDTO:
    """Simple login endpoint using registration_number and password without JWT."""
    return login_hospital(db, payload)


@router.get(
    "/",
    response_model=list[HospitalResponseDTO],
    summary="List all hospitals",
)
def list_hospitals_endpoint(
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve all registered hospitals."""
    return list_hospitals(db)


@router.get(
    "/{hospital_id}",
    response_model=HospitalResponseDTO,
    summary="Get hospital details",
)
def get_hospital_endpoint(
    hospital_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve hospital details by ID."""
    return get_hospital_by_id(db, hospital_id)


@router.put(
    "/{hospital_id}",
    response_model=HospitalResponseDTO,
    summary="Update hospital details",
)
@router.patch(
    "/{hospital_id}",
    response_model=HospitalResponseDTO,
    summary="Update hospital details (partial)",
)
def update_hospital_endpoint(
    hospital_id: str,
    payload: HospitalUpdateDTO,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Update details for a registered hospital."""
    return update_hospital(db, hospital_id, payload)


@router.patch(
    "/{hospital_id}/availability",
    response_model=HospitalResponseDTO,
    summary="Update hospital bed availability",
)
def update_hospital_availability_endpoint(
    hospital_id: str,
    payload: HospitalAvailabilityUpdateDTO,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Update bed availability for a registered hospital."""
    return update_hospital_availability(db, hospital_id, payload)
