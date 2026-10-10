from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HospitalRegisterDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200, description="Hospital name")
    registration_number: str = Field(
        min_length=1, max_length=100, description="Unique registration license/number"
    )
    password: Optional[str] = Field(
        default=None,
        min_length=4,
        max_length=128,
        description="Password for hospital portal",
    )
    address: str = Field(min_length=1, max_length=500, description="Physical address")
    latitude: float = Field(ge=-90, le=90, description="Latitude coordinates")
    longitude: float = Field(ge=-180, le=180, description="Longitude coordinates")
    contact_number: Optional[str] = Field(
        default=None, max_length=20, description="Contact phone number"
    )
    email: Optional[str] = Field(
        default=None, max_length=100, description="Contact email address"
    )
    total_beds: int = Field(ge=0, default=0, description="Total bed count")
    available_beds: int = Field(ge=0, default=0, description="Available bed count")
    is_active: bool = True

    @field_validator("name", "registration_number", "address")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_bed_capacity(self) -> "HospitalRegisterDTO":
        if self.available_beds > self.total_beds:
            raise ValueError("available_beds cannot exceed total_beds")
        return self


# Backward-compatible alias
HospitalCreateDTO = HospitalRegisterDTO


class HospitalLoginDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registration_number: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)

    @field_validator("registration_number", "password")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class HospitalUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    address: Optional[str] = Field(default=None, min_length=1, max_length=500)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    contact_number: Optional[str] = Field(default=None, max_length=20)
    email: Optional[str] = Field(default=None, max_length=100)
    total_beds: Optional[int] = Field(default=None, ge=0)
    available_beds: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_beds(self) -> "HospitalUpdateDTO":
        if (
            self.total_beds is not None
            and self.available_beds is not None
            and self.available_beds > self.total_beds
        ):
            raise ValueError("available_beds cannot exceed total_beds")
        return self

    def has_updates(self) -> bool:
        return bool(self.model_dump(exclude_unset=True))


class HospitalAvailabilityUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_beds: int = Field(ge=0, description="Updated total bed count")
    available_beds: int = Field(ge=0, description="Updated available bed count")

    @model_validator(mode="after")
    def validate_bed_capacity(self) -> "HospitalAvailabilityUpdateDTO":
        if self.available_beds > self.total_beds:
            raise ValueError("available_beds cannot exceed total_beds")
        return self


class HospitalResponseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    registration_number: str
    address: str
    latitude: float
    longitude: float
    total_beds: int
    available_beds: int
    is_active: bool
    availability_updated_at: datetime


class HospitalLoginResponseDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = "Login successful"
    hospital: HospitalResponseDTO
