import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.hospitals.router import router as hospital_router
from app.hospitals_data.router import router as hospitals_data_router
from app.utils.database import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Emergency Resource Allocator API",
    description="Hospital registration, management, and operational resource allocation API powered by MongoDB.",
    version="0.2.0",
    lifespan=lifespan,
)

allowed_origins = [
    "https://emergency-triage-six.vercel.app",
    "http://localhost:3000",
    "http://localhost:5173",
]
configured_origin = os.getenv("FRONTEND_ORIGIN")
if configured_origin and configured_origin not in allowed_origins:
    allowed_origins.append(configured_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(hospital_router)
app.include_router(hospitals_data_router)


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse, status_code=200, tags=["health"])
def health_check() -> HealthResponse:
    return {"status": "ok"}
