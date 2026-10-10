from pydantic import BaseModel, ConfigDict, Field


class TokenResponseDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds")


class RefreshTokenDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class PublicHospitalDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    address: str
    latitude: float
    longitude: float
