from typing import Any

from fastapi import APIRouter, Depends, status
from pymongo.database import Database

from app.ml.service import model_status
from app.triage.controller import recommend_hospitals
from app.triage.dto import ModelStatusDTO, TriageRecommendRequestDTO, TriageRecommendResponseDTO
from app.utils.database import get_db

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
