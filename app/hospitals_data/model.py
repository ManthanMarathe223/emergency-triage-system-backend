from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HospitalDataModel(BaseModel):
    """Document model representing hospital operational resources in MongoDB collection 'hospitals_data'."""

    hospital_id: str
    general_beds_total: int = 0
    general_beds_available: int = 0
    icu_beds_total: int = 0
    icu_beds_available: int = 0
    ventilators_total: int = 0
    ventilators_available: int = 0
    oxygen_cylinders: int = 0
    doctors_total: int = 0
    doctors_available: int = 0
    triage_status: str = "NORMAL"
    notes: Optional[str] = None
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime
