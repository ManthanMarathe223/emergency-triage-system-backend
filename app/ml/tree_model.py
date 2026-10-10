"""Bed-availability model for the backend. Plain Python: no third-party packages.

The model is a set of small decision trees stored in ``availability_model.json``.
This file reads that JSON and walks the trees, so the backend does not need
scikit-learn, numpy or pandas, and nothing is unpickled.

Question the model answers, for ONE hospital and ONE resource type:

    "The hospital last reported N free units. If the ambulance leaves now,
     how likely is it that enough units are still free when it arrives?"

Inputs (exactly what a hospital snapshot plus a route estimate can provide):

    resource_type              "GENERAL_BED", "ICU_BED" or "VENTILATOR"
    units_required             whole number, 1 or more
    total_capacity             total units of that resource at the hospital
    reported_available         free units in the hospital's latest report
    report_age_minutes         minutes since that report
    estimated_travel_minutes   planned travel time to the hospital

    model = TreeModel("availability_model.json", "model_metadata.json")
    result = model.predict({...})
    result["probability"]      # None when the inputs are outside the training ranges

A prediction is advice for ranking. It never reserves anything.
The model was trained on SIMULATED data only.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

MODEL_FORMAT = "gradient-boosted-trees-json-v1"
FEATURE_SCHEMA = "fs-snapshot-1"
STATUS_OK = "OK"
STATUS_OUT_OF_DOMAIN = "OUT_OF_DOMAIN"

INPUT_FIELDS: tuple[str, ...] = (
    "resource_type",
    "units_required",
    "total_capacity",
    "reported_available",
    "report_age_minutes",
    "estimated_travel_minutes",
)
#: Order of the numbers handed to the trees. Must match the training code.
FEATURE_NAMES: tuple[str, ...] = (
    "resource_type",
    "units_required",
    "total_capacity",
    "reported_available",
    "report_age_minutes",
    "estimated_travel_minutes",
    "available_margin",
    "horizon_minutes",
    "free_fraction",
)
_COUNT_FIELDS = ("units_required", "total_capacity", "reported_available")
_MINUTE_FIELDS = ("report_age_minutes", "estimated_travel_minutes")


class ModelUnavailableError(RuntimeError):
    """The model files cannot be used. ``code`` says why. Use the capacity rule instead."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InvalidModelInputError(ValueError):
    """The inputs are not a valid request (wrong type, negative count, unknown resource...)."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


class _Tree:
    """One decision tree, stored as parallel lists indexed by node number."""

    __slots__ = ("feature", "threshold", "left", "right", "value", "left_categories")

    def __init__(self, raw: dict[str, Any], n_features: int) -> None:
        self.feature: list[int] = raw["feature"]
        self.threshold: list[float] = raw["threshold"]
        self.left: list[int] = raw["left"]
        self.right: list[int] = raw["right"]
        self.value: list[float] = raw["value"]
        self.left_categories: dict[int, frozenset[int]] = {
            int(node): frozenset(codes) for node, codes in raw.get("left_categories", {}).items()
        }
        size = len(self.feature)
        if size == 0 or not all(len(part) == size for part in (self.threshold, self.left, self.right, self.value)):
            raise ValueError("tree arrays have different lengths")
        for node in range(size):
            if self.feature[node] < 0:  # leaf
                continue
            if self.feature[node] >= n_features:
                raise ValueError("tree refers to an unknown feature")
            # Children always come after their parent, so a walk can never loop.
            if not (node < self.left[node] < size and node < self.right[node] < size):
                raise ValueError("tree has an invalid child index")

    def output(self, features: list[float]) -> float:
        node = 0
        while True:
            index = self.feature[node]
            if index < 0:
                return self.value[node]
            categories = self.left_categories.get(node)
            if categories is not None:
                go_left = int(features[index]) in categories
            else:
                go_left = features[index] <= self.threshold[node]
            node = self.left[node] if go_left else self.right[node]


class TreeModel:
    """Loads the model once. Safe to share between requests: prediction changes nothing."""

    def __init__(self, model_path: str | Path, metadata_path: str | Path) -> None:
        model_path, metadata_path = Path(model_path), Path(metadata_path)
        if not model_path.is_file():
            raise ModelUnavailableError("MODEL_FILE_MISSING", f"model file not found: {model_path.name}")
        if not metadata_path.is_file():
            raise ModelUnavailableError("MODEL_METADATA_MISSING", f"metadata file not found: {metadata_path.name}")
        try:
            self.metadata: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ModelUnavailableError("MODEL_METADATA_INVALID", f"metadata is unreadable: {error}") from error
        if self.metadata.get("feature_schema_version") != FEATURE_SCHEMA:
            raise ModelUnavailableError(
                "FEATURE_SCHEMA_MISMATCH",
                f"this code computes features for {FEATURE_SCHEMA}; the metadata says {self.metadata.get('feature_schema_version')}",
            )
        if self.metadata.get("model_sha256") != _sha256(model_path):
            raise ModelUnavailableError("MODEL_HASH_MISMATCH", "the model file does not match model_metadata.json")
        try:
            raw = json.loads(model_path.read_text(encoding="utf-8"))
            if raw.get("format") != MODEL_FORMAT:
                raise ValueError(f"unknown model format: {raw.get('format')}")
            if tuple(raw["feature_names"]) != FEATURE_NAMES:
                raise ValueError("feature list differs from this code")
            self._resource_codes: dict[str, int] = {name: code for code, name in enumerate(raw["categories"]["resource_type"])}
            self._baseline = float(raw["baseline"])
            self._trees = [_Tree(tree, len(FEATURE_NAMES)) for tree in raw["trees"]]
            if not self._trees or not self._resource_codes:
                raise ValueError("model has no trees or no resource types")
        except ModelUnavailableError:
            raise
        except Exception as error:  # noqa: BLE001 - any malformed file means "no model"
            raise ModelUnavailableError("MODEL_LOAD_FAILED", f"could not read the model: {type(error).__name__}: {error}") from error

    # ------------------------------------------------------------------ info
    @property
    def model_id(self) -> str:
        return str(self.metadata["model_id"])

    @property
    def model_version(self) -> str:
        return str(self.metadata["model_version"])

    @property
    def supported_resource_types(self) -> list[str]:
        return sorted(self._resource_codes, key=self._resource_codes.get)

    @property
    def decision_threshold(self) -> float:
        return float(self.metadata["decision_threshold"])

    @property
    def tree_count(self) -> int:
        return len(self._trees)

    # ------------------------------------------------------------ validation
    def validate_input(self, row: dict[str, Any]) -> dict[str, Any]:
        """Return the six inputs, checked. Raises InvalidModelInputError."""
        missing = [name for name in INPUT_FIELDS if name not in row]
        if missing:
            raise InvalidModelInputError(f"missing input(s): {missing}")
        clean: dict[str, Any] = {}
        resource = row["resource_type"]
        if not isinstance(resource, str) or resource not in self._resource_codes:
            raise InvalidModelInputError(f"unsupported resource_type: {resource!r}; supported: {self.supported_resource_types}")
        clean["resource_type"] = resource
        for name in _COUNT_FIELDS:
            value = row[name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidModelInputError(f"{name} must be a whole number")
            clean[name] = value
        for name in _MINUTE_FIELDS:
            value = row[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise InvalidModelInputError(f"{name} must be a finite number")
            clean[name] = value
        if clean["units_required"] < 1:
            raise InvalidModelInputError("units_required must be at least 1")
        if clean["total_capacity"] < 1:
            raise InvalidModelInputError("total_capacity must be at least 1")
        if not 0 <= clean["reported_available"] <= clean["total_capacity"]:
            raise InvalidModelInputError("reported_available must be between 0 and total_capacity")
        if clean["units_required"] > clean["total_capacity"]:
            raise InvalidModelInputError("units_required exceeds total_capacity: this hospital can never serve the request")
        if clean["report_age_minutes"] < 0:
            raise InvalidModelInputError("report_age_minutes cannot be negative")
        if clean["estimated_travel_minutes"] <= 0:
            raise InvalidModelInputError("estimated_travel_minutes must be greater than 0")
        return clean

    def out_of_domain_fields(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        """Inputs outside what the model saw in training. Empty list means the model may be used."""
        ranges = self.metadata["training_ranges"]
        issues = []
        for name, bounds in ranges["numeric"].items():
            if name == "total_capacity":
                bounds = ranges["total_capacity_by_resource"][row["resource_type"]]
            if row[name] < bounds["min"] or row[name] > bounds["max"]:
                issues.append({"field": name, "value": row[name], "training_min": bounds["min"], "training_max": bounds["max"]})
        return issues

    # ------------------------------------------------------------ prediction
    def features(self, row: dict[str, Any]) -> list[float]:
        """The nine numbers the trees look at, in FEATURE_NAMES order."""
        available, total, units = row["reported_available"], row["total_capacity"], row["units_required"]
        age, travel = row["report_age_minutes"], row["estimated_travel_minutes"]
        return [
            float(self._resource_codes[row["resource_type"]]),
            float(units),
            float(total),
            float(available),
            float(age),
            float(travel),
            float(available - units),  # available_margin: spare units after this patient
            float(age + travel),  # horizon_minutes: how far the report is from the arrival
            available / total,  # free_fraction
        ]

    def probability(self, row: dict[str, Any]) -> float:
        """Probability for inputs that are already validated. No range check here."""
        features = self.features(row)
        total = self._baseline
        for tree in self._trees:
            total += tree.output(features)
        result = _sigmoid(total)
        if not math.isfinite(result) or not 0.0 <= result <= 1.0:
            raise ArithmeticError("the model produced a value that is not a probability")
        return result

    def predict(self, row: dict[str, Any]) -> dict[str, Any]:
        """Validate, check the training ranges, then predict. Never returns a made-up number."""
        clean = self.validate_input(row)
        issues = self.out_of_domain_fields(clean)
        probability = None if issues else self.probability(clean)
        return {
            "status": STATUS_OUT_OF_DOMAIN if issues else STATUS_OK,
            "probability": probability,
            "out_of_domain_fields": issues,
            "model_id": self.model_id,
        }
