from typing import Any

from fastapi import APIRouter, Depends, status
from pymongo.database import Database

from app.hospitals.controller import (
    get_hospital_by_id,
    list_hospitals,
    register_hospital,
    update_hospital,
    update_hospital_availability,
)
from app.hospitals.dto import (
    HospitalAvailabilityUpdateDTO,
    HospitalLoginDTO,
    HospitalRegisterDTO,
    HospitalResponseDTO,
    HospitalUpdateDTO,
)
from app.auth_dto import PublicHospitalDTO, RefreshTokenDTO, TokenResponseDTO
from app.utils.database import get_db
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_hospital_id,
)
from app.hospitals.controller import issue_tokens

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
    response_model=TokenResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Hospital simple login",
)
def login_hospital_endpoint(
    payload: HospitalLoginDTO,
    db: Database = Depends(get_db),
) -> HospitalLoginResponseDTO:
    """Verify credentials and issue access and refresh JWTs."""
    return issue_tokens(db, payload)


@router.post(
    "/token",
    response_model=TokenResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Issue JWT access and refresh tokens",
)
def token_endpoint(
    payload: HospitalLoginDTO,
    db: Database = Depends(get_db),
) -> TokenResponseDTO:
    return issue_tokens(db, payload)


@router.post(
    "/refresh",
    response_model=TokenResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Refresh JWT access and refresh tokens",
)
def refresh_token_endpoint(payload: RefreshTokenDTO) -> TokenResponseDTO:
    hospital_id = str(decode_token(payload.refresh_token, "refresh")["sub"])
    from app.utils.security import ACCESS_TOKEN_EXPIRE_MINUTES

    return TokenResponseDTO(
        access_token=create_access_token(hospital_id),
        refresh_token=create_refresh_token(hospital_id),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get(
    "/public",
    response_model=list[PublicHospitalDTO],
    status_code=status.HTTP_200_OK,
    summary="List public hospital names and locations",
)
def list_public_hospitals_endpoint(
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        {
            "id": hospital["id"],
            "name": hospital["name"],
            "address": hospital["address"],
            "latitude": hospital["latitude"],
            "longitude": hospital["longitude"],
        }
        for hospital in list_hospitals(db)
        if hospital.get("is_active", True)
    ]


@router.get(
    "/",
    response_model=list[HospitalResponseDTO],
    summary="List all hospitals",
)
def list_hospitals_endpoint(
    db: Database = Depends(get_db),
    _: str = Depends(get_current_hospital_id),
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
    _: str = Depends(get_current_hospital_id),
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
    _: str = Depends(get_current_hospital_id),
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
    _: str = Depends(get_current_hospital_id),
) -> dict[str, Any]:
    """Update bed availability for a registered hospital."""
    return update_hospital_availability(db, hospital_id, payload)
