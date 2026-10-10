import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import create_tables
from app.routers import router as hospital_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not os.getenv("TESTING"):
        create_tables()
    yield


app = FastAPI(
    title="Emergency Resource Allocator API",
    description="Hospital registration and bed availability foundation for HLTH-02.",
    version="0.1.0",
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
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)
app.include_router(hospital_router)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
