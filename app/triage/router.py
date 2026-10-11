from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pymongo.database import Database

from app.ml.service import model_status
from app.triage.allocation_service import (
    allocate_batch_patients,
    cancel_allocation,
    complete_allocation,
    reject_allocation,
    replan_allocation,
)
from app.triage.controller import recommend_hospitals
from app.triage.dto import (
    AllocationBatchRequestDTO,
    AllocationBatchResponseDTO,
    AllocationDecisionDTO,
    AllocationReplanDTO,
    BatchAllocationResultDTO,
    ModelStatusDTO,
    TriageRecommendRequestDTO,
    TriageRecommendResponseDTO,
)
from app.utils.database import get_db
from app.utils.security import get_current_hospital_id

router = APIRouter(prefix="/triage", tags=["triage"])


@router.post(
    "/recommend",
    response_model=TriageRecommendResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Assess a patient and recommend hospitals from live data",
)
def recommend_endpoint(
    payload: TriageRecommendRequestDTO,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Public, like the hospital list: the triage page works without a login.

    Reads the latest snapshot of every active hospital at the moment of the
    request, so a portal update changes the next answer. Reserves nothing.
    """
    return recommend_hospitals(db, payload)


@router.get(
    "/model-status",
    response_model=ModelStatusDTO,
    status_code=status.HTTP_200_OK,
    summary="Is the availability model loaded, and which version",
)
def model_status_endpoint() -> dict[str, Any]:
    return model_status()


@router.post(
    "/allocations/batch",
    response_model=AllocationBatchResponseDTO,
    status_code=status.HTTP_200_OK,
    summary="Allocate a batch of patients while respecting current resource capacity",
)
def batch_allocation_endpoint(
    payload: Any = Body(...),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    if isinstance(payload, list):
        normalized = {"patients": payload}
    elif isinstance(payload, dict):
        normalized = payload
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Expected a list of patients or a batch object.")
    parsed = AllocationBatchRequestDTO.model_validate(normalized)
    return allocate_batch_patients(db, parsed)


@router.post(
    "/allocations/{allocation_id}/reject",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Reject a currently assigned hospital for an allocation",
)
def reject_allocation_endpoint(
    allocation_id: str,
    payload: AllocationDecisionDTO,
    db: Database = Depends(get_db),
    authenticated_hospital_id: str = Depends(get_current_hospital_id),
) -> dict[str, Any]:
    return reject_allocation(db, allocation_id, payload.reason, payload.notes, authenticated_hospital_id)


@router.post(
    "/allocations/{allocation_id}/cancel",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Cancel an active allocation and release capacity",
)
def cancel_allocation_endpoint(
    allocation_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    return cancel_allocation(db, allocation_id)


@router.post(
    "/allocations/{allocation_id}/complete",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Complete an allocation and release the held capacity",
)
def complete_allocation_endpoint(
    allocation_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    return complete_allocation(db, allocation_id)


@router.post(
    "/allocations/{allocation_id}/replan",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Re-evaluate an allocation using current capacity and travel estimates",
)
def replan_allocation_endpoint(
    allocation_id: str,
    payload: AllocationReplanDTO,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    return replan_allocation(db, allocation_id, payload)
