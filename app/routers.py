from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Hospital
from app.schemas import HospitalAvailabilityUpdate, HospitalCreate, HospitalResponse


router = APIRouter(prefix="/hospitals", tags=["hospitals"])


@router.post("/", response_model=HospitalResponse, status_code=status.HTTP_201_CREATED)
def create_hospital(payload: HospitalCreate, db: Session = Depends(get_db)) -> Hospital:
    hospital = Hospital(
        **payload.model_dump(),
        availability_updated_at=datetime.now(timezone.utc),
    )
    db.add(hospital)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A hospital with this registration_number already exists.",
        ) from exc
    db.refresh(hospital)
    return hospital


@router.get("/", response_model=list[HospitalResponse])
def list_hospitals(db: Session = Depends(get_db)) -> list[Hospital]:
    return list(db.scalars(select(Hospital).order_by(Hospital.id)))


@router.get("/{hospital_id}", response_model=HospitalResponse)
def get_hospital(hospital_id: int, db: Session = Depends(get_db)) -> Hospital:
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found.",
        )
    return hospital


@router.patch(
    "/{hospital_id}/availability",
    response_model=HospitalResponse,
)
def update_hospital_availability(
    hospital_id: int,
    payload: HospitalAvailabilityUpdate,
    db: Session = Depends(get_db),
) -> Hospital:
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found.",
        )

    hospital.total_beds = payload.total_beds
    hospital.available_beds = payload.available_beds
    hospital.availability_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(hospital)
    return hospital
