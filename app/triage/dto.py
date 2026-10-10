from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SymptomKey = Literal[
    "chest_pain",
    "breathing",
    "bleeding",
    "unconscious",
    "abdominal",
    "head_injury",
    "stroke",
    "burns",
    "trauma",
    "seizure",
    "fever",
]


class VitalsDTO(BaseModel):
    """Vital signs. Every field is optional; send what you have."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    spo2: Optional[float] = Field(default=None, ge=0, le=100, description="Oxygen saturation, %")
    hr: Optional[float] = Field(default=None, ge=0, le=350, description="Heart rate, beats per minute")
    sbp: Optional[float] = Field(default=None, ge=0, le=350, description="Systolic blood pressure, mmHg")
    dbp: Optional[float] = Field(default=None, ge=0, le=250, description="Diastolic blood pressure, mmHg")
    rr: Optional[float] = Field(default=None, ge=0, le=120, description="Respiratory rate, breaths per minute")
    temp: Optional[float] = Field(default=None, ge=20, le=46, description="Body temperature, °C")
    gcs: Optional[float] = Field(default=None, ge=3, le=15, description="Glasgow Coma Scale, 3 to 15")


class TriageRecommendRequestDTO(BaseModel):
    """One patient: where they are and what is wrong."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    latitude: float = Field(ge=-90, le=90, description="Patient or ambulance latitude")
    longitude: float = Field(ge=-180, le=180, description="Patient or ambulance longitude")
    symptoms: list[SymptomKey] = Field(default_factory=list, max_length=11, description="Symptom keys")
    vitals: VitalsDTO = Field(default_factory=VitalsDTO)
    age: Optional[float] = Field(default=None, ge=0, le=130, description="Age in years")
    described_as_severe: bool = Field(default=False, description="The caller used words like severe, major, massive")
    max_results: int = Field(default=10, ge=1, le=50, description="How many ranked hospitals to return")

    @model_validator(mode="after")
    def needs_some_clinical_information(self) -> "TriageRecommendRequestDTO":
        self.symptoms = list(dict.fromkeys(self.symptoms))  # drop repeats, keep order
        if not self.symptoms and not self.vitals.model_dump(exclude_none=True):
            raise ValueError("send at least one symptom or one vital sign")
        return self


class TriageAssessmentDTO(BaseModel):
    severity: Literal["critical", "high", "moderate", "low"]
    urgency_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    category: str
    score: int
    reasons: list[str]
    required_facilities: list[str] = Field(description="Same keys the frontend uses: emergency, icu, ventilator, ...")
    required_resources: list[str] = Field(description="Counted resources the patient needs one free unit of")
    required_specialists: list[str]
    not_checked_by_server: list[str] = Field(description="Needs the server cannot verify from hospital snapshots")


class ResourceCountDTO(BaseModel):
    total: int
    available: int


class LiveSnapshotDTO(BaseModel):
    """The hospital's latest report, so a client can show the same numbers the ranking used."""

    general_beds: ResourceCountDTO
    icu_beds: ResourceCountDTO
    ventilators: ResourceCountDTO
    oxygen_cylinders: int
    doctors_on_duty: int
    specialists_on_duty: list[str] = Field(description="Specializations with at least one available doctor")
    triage_status: str
    reported_at: datetime
    report_age_minutes: float


class ResourceForecastDTO(BaseModel):
    resource_type: str
    total: int
    reported_available: int
    probability_available_at_arrival: Optional[float] = Field(
        description="Model estimate that one unit is still free on arrival. null when the model was not used."
    )
    prediction_status: Literal["OK", "OUT_OF_DOMAIN", "NOT_USED"]


class RankedHospitalDTO(BaseModel):
    rank: int
    hospital_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    distance_km: float
    estimated_travel_minutes: int
    reported_at: datetime
    report_age_minutes: float
    triage_status: str
    live: LiveSnapshotDTO
    resources: list[ResourceForecastDTO]
    reports_enough_units: bool = Field(description="The latest report shows a free unit of every needed resource")
    probability_all_resources: Optional[float] = Field(description="Product of the resource probabilities; null in fallback mode")
    expected_minutes_to_care: Optional[float] = Field(description="travel + (1 - probability) x penalty; null in fallback mode")
    specialists_on_duty: Optional[bool] = Field(description="null when the case needs no specialist")
    missing_specialists: list[str]
    reasons: list[str]
    warnings: list[str]


class NotRankedHospitalDTO(BaseModel):
    hospital_id: str
    name: str
    reason: Literal["NO_LIVE_DATA", "STALE_DATA", "DIVERTING", "TOO_FAR", "RESOURCE_NOT_OFFERED", "OUT_OF_MODEL_RANGE"]
    detail: str
    distance_km: Optional[float] = None
    estimated_travel_minutes: Optional[int] = None
    live: Optional[LiveSnapshotDTO] = Field(default=None, description="null when the hospital has never reported")


class RankingInfoDTO(BaseModel):
    method: Literal["ML_EXPECTED_TIME", "FALLBACK_CAPACITY"]
    ml_outcome: str = Field(description="ML_OK, or why the model was not used")
    model_id: Optional[str]
    diversion_penalty_minutes: float
    order: str = Field(description="Plain-language description of the sort order used")
    hospitals_considered: int
    is_reservation: bool = Field(default=False, description="Always false: a recommendation holds nothing")


class TriageRecommendResponseDTO(BaseModel):
    request_id: str
    generated_at: datetime
    triage: TriageAssessmentDTO
    ranking: RankingInfoDTO
    recommended: list[RankedHospitalDTO]
    not_ranked: list[NotRankedHospitalDTO]
    disclaimer: str


class ModelStatusDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    model_loaded: bool
