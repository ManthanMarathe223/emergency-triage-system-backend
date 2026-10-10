from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HospitalModel(BaseModel):
    """Document model representing a hospital in MongoDB collection 'hospitals'."""

    name: str
    registration_number: str
    password_hash: Optional[str] = None
    address: str
    latitude: float
    longitude: float
    contact_number: Optional[str] = None
    email: Optional[str] = None
    total_beds: int = 0
    available_beds: int = 0
    is_active: bool = True
    availability_updated_at: datetime
    created_at: datetime
    updated_at: datetime
