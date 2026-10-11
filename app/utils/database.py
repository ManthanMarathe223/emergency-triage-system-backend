import os
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pymongo import MongoClient
from pymongo.database import Database


MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "emergency_triage_db")

_client: Optional[MongoClient] = None
_database: Optional[Database] = None


def get_client() -> MongoClient:
    """Get or initialize the MongoDB client."""
    global _client
    if _client is None:
        if os.getenv("TESTING") == "1":
            import mongomock

            _client = mongomock.MongoClient()
        else:
            environment = os.getenv("ENVIRONMENT", "development").lower()
            if environment in {"production", "prod"} or os.getenv("VERCEL") == "1":
                if not os.getenv("MONGODB_URL") or not os.getenv("DATABASE_NAME"):
                    raise RuntimeError(
                        "MONGODB_URL and DATABASE_NAME must be configured in production."
                    )
                if not MONGODB_URL.startswith("mongodb+srv://"):
                    raise RuntimeError(
                        "Production MongoDB configuration must use a TLS-enabled mongodb+srv:// Atlas URI."
                    )
            _client = MongoClient(
                MONGODB_URL,
                connectTimeoutMS=5_000,
                serverSelectionTimeoutMS=5_000,
                socketTimeoutMS=10_000,
                maxPoolSize=10,
                retryWrites=True,
            )
    return _client


def get_database() -> Database:
    """Get or initialize the MongoDB database."""
    global _database
    if _database is None:
        client = get_client()
        _database = client[DATABASE_NAME]
    return _database


def get_db() -> Database:
    """FastAPI dependency to inject database."""
    return get_database()


def to_object_id(id_str: str) -> ObjectId:
    """Convert a string to a BSON ObjectId with validation."""
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ID format: '{id_str}'. Must be a 24-character hexadecimal string.",
        ) from exc


def serialize_doc(doc: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:

    """Convert MongoDB _id into a readable string id and ensure UTC tzinfo on datetimes."""
    if doc is None:
        return None
    doc_copy = dict(doc)
    if "_id" in doc_copy:
        doc_copy["id"] = str(doc_copy.pop("_id"))
    for key, val in doc_copy.items():
        if isinstance(val, datetime) and val.tzinfo is None:
            doc_copy[key] = val.replace(tzinfo=timezone.utc)
    return doc_copy



def init_db() -> None:
    """Create essential MongoDB indexes."""
    db = get_database()
    db.hospitals.create_index("registration_number", unique=True)
    db.hospitals_data.create_index("hospital_id")
    db.hospitals_data.create_index([("recorded_at", -1)])
    # Latest snapshot per hospital: used by /triage/recommend and by the "latest" endpoint.
    db.hospitals_data.create_index([("hospital_id", 1), ("recorded_at", -1)])
    db.triage_allocations.create_index("patient_id")
    db.triage_allocations.create_index("status")
    db.triage_allocations.create_index([("assigned_hospital_id", 1), ("status", 1)])
    db.triage_batches.create_index("batch_id")
