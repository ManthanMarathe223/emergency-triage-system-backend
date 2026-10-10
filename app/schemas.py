from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HospitalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    registration_number: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    total_beds: int = Field(ge=0)
    available_beds: int = Field(ge=0)
    is_active: bool = True

    @field_validator("name", "registration_number", "address")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_bed_capacity(self) -> "HospitalCreate":
        if self.available_beds > self.total_beds:
            raise ValueError("available_beds cannot exceed total_beds")
        return self


class HospitalAvailabilityUpdate(BaseModel):
    total_beds: int = Field(ge=0)
    available_beds: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_bed_capacity(self) -> "HospitalAvailabilityUpdate":
        if self.available_beds > self.total_beds:
            raise ValueError("available_beds cannot exceed total_beds")
        return self


class HospitalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    registration_number: str
    address: str
    latitude: float
    longitude: float
    total_beds: int
    available_beds: int
    is_active: bool
    availability_updated_at: datetime
