"""Loads the availability model once and hands it to the rest of the app.

The model files live next to this file:

    availability_model.json   the decision trees
    model_metadata.json       version, allowed input ranges, hash of the model file

If the files are missing or damaged the app still works: ``get_availability_model``
returns ``None`` and the triage endpoint ranks hospitals with the capacity rule.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from app.ml.tree_model import ModelUnavailableError, TreeModel

MODEL_DIR = Path(__file__).resolve().parent
MODEL_FILE = "availability_model.json"
METADATA_FILE = "model_metadata.json"

_lock = threading.Lock()
_loaded = False
_model: Optional[TreeModel] = None
_unavailable_reason: Optional[str] = None


def get_availability_model() -> Optional[TreeModel]:
    """Return the model, loading it on first use. ``None`` means "use the capacity rule"."""
    global _loaded, _model, _unavailable_reason
    if _loaded:
        return _model
    with _lock:
        if not _loaded:
            try:
                _model = TreeModel(MODEL_DIR / MODEL_FILE, MODEL_DIR / METADATA_FILE)
                _unavailable_reason = None
            except ModelUnavailableError as error:
                _model = None
                _unavailable_reason = error.code
            _loaded = True
    return _model


def reset_model_cache() -> None:
    """Forget the loaded model so the next call reads the files again (used by tests)."""
    global _loaded, _model, _unavailable_reason
    with _lock:
        _loaded = False
        _model = None
        _unavailable_reason = None


def model_unavailable_reason() -> Optional[str]:
    get_availability_model()
    return _unavailable_reason


def model_status() -> dict[str, Any]:
    """What the model is and whether it loaded. Safe to show publicly."""
    model = get_availability_model()
    if model is None:
        return {"model_loaded": False, "reason": _unavailable_reason, "fallback": "capacity rule"}
    metadata = model.metadata
    ranges = metadata["training_ranges"]
    return {
        "model_loaded": True,
        "model_id": model.model_id,
        "model_version": model.model_version,
        "model_type": metadata.get("model_type"),
        "trees": model.tree_count,
        "inputs": metadata.get("input_fields"),
        "supported_resource_types": model.supported_resource_types,
        "max_report_age_minutes": ranges["numeric"]["report_age_minutes"]["max"],
        "max_travel_minutes": ranges["numeric"]["estimated_travel_minutes"]["max"],
        "capacity_ranges": ranges["total_capacity_by_resource"],
        "data_origin": metadata.get("data_origin"),
        "test_summary": metadata.get("test_summary"),
    }
