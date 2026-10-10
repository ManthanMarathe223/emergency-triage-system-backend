from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DoctorDTO(BaseModel):
    """Doctor details reported as part of a hospital's operational snapshot."""

    model_config = ConfigDict(extra="forbid")

    doctor_id: str = Field(
        min_length=1,
        max_length=100,
        description="Hospital-assigned doctor identifier",
    )
    name: str = Field(min_length=1, max_length=200, description="Doctor's name")
    specialization: str = Field(
        min_length=1,
        max_length=100,
        description="Primary medical specialization",
    )
    is_available: bool = Field(
        description="Whether the doctor is currently available for emergency duty"
    )

    @model_validator(mode="after")
    def reject_blank_text(self) -> "DoctorDTO":
        for field_name in ("doctor_id", "name", "specialization"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} must not be blank")
            setattr(self, field_name, value)
        return self


class HospitalDataCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hospital_id: str = Field(min_length=1, description="Target hospital ID")
    doctors: list[DoctorDTO] = Field(
        default_factory=list,
        description="Doctors and their current emergency-duty availability",
    )
    general_beds_total: int = Field(ge=0, default=0, description="Total general ward beds")
    general_beds_available: int = Field(
        ge=0, default=0, description="Available general ward beds"
    )
    icu_beds_total: int = Field(ge=0, default=0, description="Total ICU beds")
    icu_beds_available: int = Field(
        ge=0, default=0, description="Available ICU beds"
    )
    ventilators_total: int = Field(ge=0, default=0, description="Total ventilators")
    ventilators_available: int = Field(
        ge=0, default=0, description="Available ventilators"
    )
    oxygen_cylinders: int = Field(
        ge=0, default=0, description="Available oxygen cylinders"
    )
    doctors_total: int = Field(
        ge=0, default=0, description="Total emergency & duty doctors"
    )
    doctors_available: int = Field(
        ge=0, default=0, description="Currently active / on-duty available doctors"
    )
    triage_status: str = Field(
        default="NORMAL",
        pattern=r"^(NORMAL|ELEVATED|CRITICAL|DIVERT)$",
        description="Current triage operational status",
    )
    notes: Optional[str] = Field(
        default=None, max_length=500, description="Operational handover notes"
    )

    @model_validator(mode="after")
    def validate_capacities(self) -> "HospitalDataCreateDTO":
        if self.general_beds_available > self.general_beds_total:
            raise ValueError("general_beds_available cannot exceed general_beds_total")
        if self.icu_beds_available > self.icu_beds_total:
            raise ValueError("icu_beds_available cannot exceed icu_beds_total")
        if self.ventilators_available > self.ventilators_total:
            raise ValueError("ventilators_available cannot exceed ventilators_total")
        if self.doctors_available > self.doctors_total:
            raise ValueError("doctors_available cannot exceed doctors_total")
        return self


class HospitalDataUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doctors: Optional[list[DoctorDTO]] = None
    general_beds_total: Optional[int] = Field(default=None, ge=0)
    general_beds_available: Optional[int] = Field(default=None, ge=0)
    icu_beds_total: Optional[int] = Field(default=None, ge=0)
    icu_beds_available: Optional[int] = Field(default=None, ge=0)
    ventilators_total: Optional[int] = Field(default=None, ge=0)
    ventilators_available: Optional[int] = Field(default=None, ge=0)
    oxygen_cylinders: Optional[int] = Field(default=None, ge=0)
    doctors_total: Optional[int] = Field(default=None, ge=0)
    doctors_available: Optional[int] = Field(default=None, ge=0)
    triage_status: Optional[str] = Field(
        default=None,
        pattern=r"^(NORMAL|ELEVATED|CRITICAL|DIVERT)$",
    )
    notes: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_update_capacities(self) -> "HospitalDataUpdateDTO":
        if (
            self.general_beds_total is not None
            and self.general_beds_available is not None
            and self.general_beds_available > self.general_beds_total
        ):
            raise ValueError("general_beds_available cannot exceed general_beds_total")
        if (
            self.icu_beds_total is not None
            and self.icu_beds_available is not None
            and self.icu_beds_available > self.icu_beds_total
        ):
            raise ValueError("icu_beds_available cannot exceed icu_beds_total")
        if (
            self.ventilators_total is not None
            and self.ventilators_available is not None
            and self.ventilators_available > self.ventilators_total
        ):
            raise ValueError("ventilators_available cannot exceed ventilators_total")
        if (
            self.doctors_total is not None
            and self.doctors_available is not None
            and self.doctors_available > self.doctors_total
        ):
            raise ValueError("doctors_available cannot exceed doctors_total")
        return self


class HospitalDataResponseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hospital_id: str
    doctors: list[DoctorDTO] = Field(default_factory=list)
    general_beds_total: int
    general_beds_available: int
    icu_beds_total: int
    icu_beds_available: int
    ventilators_total: int
    ventilators_available: int
    oxygen_cylinders: int
    doctors_total: int
    doctors_available: int
    triage_status: str
    notes: Optional[str]
    recorded_at: datetime


class HospitalDataDeleteResponseDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = "Hospital data deleted successfully"
    id: str
