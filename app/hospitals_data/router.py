from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pymongo.database import Database

from app.hospitals_data.controller import (
    create_hospital_data,
    delete_hospital_data,
    get_hospital_data_by_id,
    get_hospital_data_history,
    get_latest_hospital_data,
    list_all_hospitals_data,
    update_hospital_data,
)
from app.hospitals_data.dto import (
    HospitalDataCreateDTO,
    HospitalDataDeleteResponseDTO,
    HospitalDataResponseDTO,
    HospitalDataUpdateDTO,
)
from app.utils.database import get_db
from app.utils.security import get_current_hospital_id

router = APIRouter(prefix="/hospitals-data", tags=["hospitals_data"])


@router.post(
    "/",
    response_model=HospitalDataResponseDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Record operational data for a hospital",
)
def create_hospital_data_endpoint(
    payload: HospitalDataCreateDTO,
    db: Database = Depends(get_db),
    _: str = Depends(get_current_hospital_id),
) -> dict[str, Any]:
    """Create a new hospital resource data entry (beds, ICU, ventilators, oxygen, doctors)."""
    return create_hospital_data(db, payload)


@router.get(
    "/",
    response_model=list[HospitalDataResponseDTO],
    summary="List recent operational data records",
)
def list_all_data_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    db: Database = Depends(get_db),
    _: str = Depends(get_current_hospital_id),
) -> list[dict[str, Any]]:
    """Retrieve operational data entries across all hospitals."""
    return list_all_hospitals_data(db, limit=limit)


@router.get(
    "/hospital/{hospital_id}/latest",
    response_model=HospitalDataResponseDTO,
    summary="Get latest operational data for a hospital",
)
def get_latest_data_endpoint(
    hospital_id: str,
    db: Database = Depends(get_db),
    _: str = Depends(get_current_hospital_id),
) -> dict[str, Any]:
    """Retrieve latest operational metrics for a specific hospital."""
    return get_latest_hospital_data(db, hospital_id)


@router.get(
    "/hospital/{hospital_id}/history",
    response_model=list[HospitalDataResponseDTO],
    summary="Get operational data history for a hospital",
)
def get_data_history_endpoint(
    hospital_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Database = Depends(get_db),
    _: str = Depends(get_current_hospital_id),
) -> list[dict[str, Any]]:
    """Retrieve historical operational records for a specific hospital."""
    return get_hospital_data_history(db, hospital_id, limit=limit)


@router.get(
    "/{data_id}",
    response_model=HospitalDataResponseDTO,
    summary="Get operational data record by ID",
)
def get_data_by_id_endpoint(
    data_id: str,
    db: Database = Depends(get_db),
    _: str = Depends(get_current_hospital_id),
) -> dict[str, Any]:
    """Retrieve a single operational data entry by its ID."""
    return get_hospital_data_by_id(db, data_id)


@router.put(
    "/{data_id}",
    response_model=HospitalDataResponseDTO,
    summary="Update operational data record",
)
@router.patch(
    "/{data_id}",
    response_model=HospitalDataResponseDTO,
    summary="Update operational data record (partial)",
)
def update_data_endpoint(
    data_id: str,
    payload: HospitalDataUpdateDTO,
    db: Database = Depends(get_db),
    _: str = Depends(get_current_hospital_id),
) -> dict[str, Any]:
    """Update an operational data record and its resource counts."""
    return update_hospital_data(db, data_id, payload)


@router.delete(
    "/{data_id}",
    response_model=HospitalDataDeleteResponseDTO,
    summary="Delete operational data record",
)
def delete_data_endpoint(
    data_id: str,
    db: Database = Depends(get_db),
    _: str = Depends(get_current_hospital_id),
) -> HospitalDataDeleteResponseDTO:
    """Delete an operational data record by its ID."""
    return delete_hospital_data(db, data_id)
