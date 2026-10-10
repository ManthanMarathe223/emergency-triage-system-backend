"""Hospital recommendation for one patient, from live hospital data.

Steps for every request:

1. Assess the patient (``rules.assess_patient``): severity and what is needed.
2. Read every active hospital and its LATEST snapshot from MongoDB.
3. Drop hospitals that cannot be recommended (no data, diverting, too far,
   resource not offered) and say why.
4. Ask the model, per hospital and needed resource: "how likely is a unit
   still free when the patient arrives?"
5. Order the rest: hospitals whose report shows a free unit first, then the
   smallest expected time to care.

Nothing here reserves a bed. The answer is advice for a dispatcher.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo.database import Database

from app.ml.service import get_availability_model, model_unavailable_reason
from app.ml.tree_model import STATUS_OK, InvalidModelInputError, TreeModel
from app.triage.dto import TriageRecommendRequestDTO
from app.triage.rules import (
    UNCHECKED_FACILITIES,
    URGENCY_FOR_SEVERITY,
    assess_patient,
    resources_needed,
    specialists_needed,
)

METHOD_ML = "ML_EXPECTED_TIME"
METHOD_FALLBACK = "FALLBACK_CAPACITY"

#: Minutes added to the expected time, weighted by the chance the hospital turns out to be full.
DIVERSION_PENALTY_MINUTES = 60.0
#: Used when the model is not loaded. With the model, its own limits apply.
DEFAULT_MAX_TRAVEL_MINUTES = 90.0
DEFAULT_MAX_REPORT_AGE_MINUTES = 1440.0
#: Travel estimate, same formula as the frontend (src/lib/geo.ts): straight line x 1.35 at 32 km/h.
ROAD_FACTOR = 1.35
AVERAGE_SPEED_KMH = 32.0
EARTH_RADIUS_KM = 6371.0

#: Resource type -> (total field, available field, words for messages) in a hospitals_data snapshot.
RESOURCE_FIELDS: dict[str, tuple[str, str, str]] = {
    "GENERAL_BED": ("general_beds_total", "general_beds_available", "general beds"),
    "ICU_BED": ("icu_beds_total", "icu_beds_available", "ICU beds"),
    "VENTILATOR": ("ventilators_total", "ventilators_available", "ventilators"),
}
DISCLAIMER = (
    "Decision support only. This is not a diagnosis and not a reservation. "
    "The availability model was trained on simulated data. Confirm with the hospital before transport."
)


# ------------------------------------------------------------------ helpers
def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    x = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(x))


def estimate_travel_minutes(distance_km: float) -> int:
    """Straight-line estimate. Replace with a routing service for real road times."""
    return max(2, round(distance_km * ROAD_FACTOR / AVERAGE_SPEED_KMH * 60))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def latest_snapshots(db: Database, hospital_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Newest hospitals_data document of each hospital, in one query."""
    if not hospital_ids:
        return {}
    pipeline = [
        {"$match": {"hospital_id": {"$in": hospital_ids}}},
        {"$sort": {"recorded_at": -1, "_id": -1}},
        {"$group": {"_id": "$hospital_id", "snapshot": {"$first": "$$ROOT"}}},
    ]
    return {row["_id"]: row["snapshot"] for row in db.hospitals_data.aggregate(pipeline)}


def _age_text(minutes: float) -> str:
    if minutes < 1:
        return "just now"
    if minutes < 90:
        return f"{round(minutes)} min ago"
    if minutes < 48 * 60:
        return f"{round(minutes / 60)} h ago"
    return f"{round(minutes / 1440)} days ago"


def _percent(probability: float) -> str:
    """Never print a model estimate as a certainty."""
    if probability >= 0.995:
        return "over 99%"
    if probability < 0.005:
        return "under 1%"
    return f"{round(probability * 100)}%"


def _count(snapshot: dict[str, Any], field: str) -> int:
    return int(snapshot.get(field, 0) or 0)


def live_view(snapshot: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Public summary of a snapshot. Counts and specializations only: no doctor names, no notes."""
    reported_at = _as_utc(snapshot.get("updated_at") or snapshot["recorded_at"])
    on_duty = [d for d in snapshot.get("doctors") or [] if d.get("is_available")]
    return {
        "general_beds": {"total": _count(snapshot, "general_beds_total"), "available": _count(snapshot, "general_beds_available")},
        "icu_beds": {"total": _count(snapshot, "icu_beds_total"), "available": _count(snapshot, "icu_beds_available")},
        "ventilators": {"total": _count(snapshot, "ventilators_total"), "available": _count(snapshot, "ventilators_available")},
        "oxygen_cylinders": _count(snapshot, "oxygen_cylinders"),
        "doctors_on_duty": len(on_duty) if snapshot.get("doctors") else _count(snapshot, "doctors_available"),
        "specialists_on_duty": sorted({str(d.get("specialization", "")).strip() for d in on_duty} - {""}),
        "triage_status": snapshot.get("triage_status", "NORMAL"),
        "reported_at": reported_at,
        "report_age_minutes": round(max(0.0, (now - reported_at).total_seconds() / 60.0), 1),
    }


def _on_duty_specializations(snapshot: dict[str, Any]) -> set[str]:
    return {
        str(doctor.get("specialization", "")).strip().lower()
        for doctor in snapshot.get("doctors") or []
        if doctor.get("is_available")
    }


# --------------------------------------------------------------- main logic
def recommend_hospitals(
    db: Database,
    payload: TriageRecommendRequestDTO,
    model: Optional[TreeModel] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Rank hospitals for one patient. ``model`` and ``now`` can be passed in by tests."""
    now = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    if model is None:
        model = get_availability_model()

    assessment = assess_patient(
        payload.symptoms, payload.vitals.model_dump(), age=payload.age, described_as_severe=payload.described_as_severe
    )
    needed_resources = resources_needed(assessment["required"])
    needed_specialists = specialists_needed(assessment["required"])
    triage = {
        "severity": assessment["severity"],
        "urgency_level": URGENCY_FOR_SEVERITY[assessment["severity"]],
        "category": assessment["category"],
        "score": assessment["score"],
        "reasons": assessment["reasons"],
        "required_facilities": assessment["required"],
        "required_resources": needed_resources,
        "required_specialists": needed_specialists,
        "not_checked_by_server": [f"{key}: {why}" for key, why in UNCHECKED_FACILITIES.items() if key in assessment["required"]],
    }

    if model is not None:
        ranges = model.metadata["training_ranges"]["numeric"]
        max_travel = float(ranges["estimated_travel_minutes"]["max"])
        max_age = float(ranges["report_age_minutes"]["max"])
    else:
        max_travel, max_age = DEFAULT_MAX_TRAVEL_MINUTES, DEFAULT_MAX_REPORT_AGE_MINUTES

    hospitals = [h for h in db.hospitals.find({}) if h.get("is_active", True)]
    snapshots = latest_snapshots(db, [str(h["_id"]) for h in hospitals])

    candidates: list[dict[str, Any]] = []  # within the travel limit, report fresh enough for the model
    stale: list[dict[str, Any]] = []  # within the travel limit, report older than the age limit
    far: list[dict[str, Any]] = []  # beyond the travel limit; used only when nothing is closer
    not_ranked: list[dict[str, Any]] = []

    for hospital in hospitals:
        hospital_id = str(hospital["_id"])
        distance = haversine_km(payload.latitude, payload.longitude, hospital["latitude"], hospital["longitude"])
        travel = estimate_travel_minutes(distance)
        base = {
            "hospital_id": hospital_id,
            "name": hospital["name"],
            "distance_km": round(distance, 2),
            "estimated_travel_minutes": travel,
        }
        snapshot = snapshots.get(hospital_id)
        if snapshot is None:
            not_ranked.append({**base, "reason": "NO_LIVE_DATA", "detail": "This hospital has not reported its resources yet."})
            continue
        live = live_view(snapshot, now)
        base["live"] = live
        if snapshot.get("triage_status") == "DIVERT":
            not_ranked.append({**base, "reason": "DIVERTING", "detail": "The hospital reports that it is diverting emergency cases."})
            continue
        missing_resource = next((r for r in needed_resources if _count(snapshot, RESOURCE_FIELDS[r][0]) < 1), None)
        if missing_resource is not None:
            not_ranked.append(
                {**base, "reason": "RESOURCE_NOT_OFFERED", "detail": f"The hospital has no {RESOURCE_FIELDS[missing_resource][2]}."}
            )
            continue

        reported_at = live["reported_at"]
        age = max(0.0, (now - reported_at).total_seconds() / 60.0)
        on_duty = _on_duty_specializations(snapshot)
        missing_specialists = [s for s in needed_specialists if s.lower() not in on_duty]
        resources = [
            {
                "resource_type": resource,
                "total": _count(snapshot, RESOURCE_FIELDS[resource][0]),
                "reported_available": _count(snapshot, RESOURCE_FIELDS[resource][1]),
                "probability_available_at_arrival": None,
                "prediction_status": "NOT_USED",
            }
            for resource in needed_resources
        ]
        candidate = {
            **base,
            "address": hospital.get("address", ""),
            "latitude": hospital["latitude"],
            "longitude": hospital["longitude"],
            "reported_at": reported_at,
            "report_age_minutes": round(age, 1),
            "triage_status": snapshot.get("triage_status", "NORMAL"),
            "resources": resources,
            "reports_enough_units": all(r["reported_available"] >= 1 for r in resources),
            "probability_all_resources": None,
            "expected_minutes_to_care": None,
            "specialists_on_duty": (not missing_specialists) if needed_specialists else None,
            "missing_specialists": missing_specialists,
        }
        if travel > max_travel:
            far.append(candidate)
        elif age > max_age:
            stale.append(candidate)
        else:
            candidates.append(candidate)

    # ---- model probabilities for hospitals with fresh enough data
    ml_outcome = "ML_OK"
    scored: list[dict[str, Any]] = []
    if model is None:
        ml_outcome = f"MODEL_UNAVAILABLE:{model_unavailable_reason() or 'NOT_LOADED'}"
    else:
        try:
            for candidate in candidates:
                probability = 1.0
                in_range = True
                for resource in candidate["resources"]:
                    result = model.predict(
                        {
                            "resource_type": resource["resource_type"],
                            "units_required": 1,
                            "total_capacity": resource["total"],
                            "reported_available": resource["reported_available"],
                            "report_age_minutes": candidate["report_age_minutes"],
                            "estimated_travel_minutes": candidate["estimated_travel_minutes"],
                        }
                    )
                    resource["prediction_status"] = result["status"]
                    if result["status"] == STATUS_OK:
                        resource["probability_available_at_arrival"] = round(result["probability"], 4)
                        probability *= result["probability"]
                    else:
                        in_range = False
                if in_range:
                    candidate["probability_all_resources"] = round(probability, 4)
                    candidate["expected_minutes_to_care"] = round(
                        candidate["estimated_travel_minutes"] + (1.0 - probability) * DIVERSION_PENALTY_MINUTES, 1
                    )
                    scored.append(candidate)
        except (InvalidModelInputError, ArithmeticError, KeyError) as error:
            # A hospital snapshot the model cannot read (for example available > total). Use the fallback for everyone.
            ml_outcome = f"PREDICTION_FAILED:{type(error).__name__}"
            scored = []

    if ml_outcome == "ML_OK" and not scored:
        ml_outcome = "NO_HOSPITAL_WITH_USABLE_PREDICTION"

    def specialist_gap(candidate: dict[str, Any]) -> int:
        return len(candidate["missing_specialists"])

    def by_capacity_rule(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The simple order, with no model numbers left on any hospital."""
        for candidate in group:
            candidate["probability_all_resources"] = None
            candidate["expected_minutes_to_care"] = None
            for resource in candidate["resources"]:
                resource["probability_available_at_arrival"] = None
                resource["prediction_status"] = "NOT_USED"
        return sorted(
            group,
            key=lambda c: (
                0 if c["reports_enough_units"] else 1,
                0 if c["report_age_minutes"] <= max_age else 1,
                specialist_gap(c),
                c["estimated_travel_minutes"],
                c["hospital_id"],
            ),
        )

    capacity_order = (
        "Capacity rule: 1) hospitals whose latest report shows a free unit of every needed resource, "
        "2) reports newer than the age limit, 3) needed specialist on duty, 4) shortest travel."
    )

    if scored:
        method = METHOD_ML
        ranked = sorted(
            scored,
            key=lambda c: (
                0 if c["reports_enough_units"] else 1,
                specialist_gap(c),
                c["expected_minutes_to_care"],
                c["estimated_travel_minutes"],
                c["hospital_id"],
            ),
        )
        order = (
            "1) hospitals whose latest report shows a free unit of every needed resource, "
            "2) hospitals with the needed specialist on duty, "
            f"3) smallest expected minutes to care = travel + (1 - probability) x {DIVERSION_PENALTY_MINUTES:g}."
        )
        scored_ids = {c["hospital_id"] for c in scored}
        for candidate in candidates:
            if candidate["hospital_id"] not in scored_ids:
                not_ranked.append(_not_ranked_entry(candidate, "OUT_OF_MODEL_RANGE", "The hospital's numbers are outside the range the model was trained on."))
        for candidate in stale:
            not_ranked.append(
                _not_ranked_entry(candidate, "STALE_DATA", f"Last report was {_age_text(candidate['report_age_minutes'])}; the limit is {round(max_age / 60)} h.")
            )
    else:
        # No usable model answer: one simple rule for every hospital within the travel limit that has ever reported.
        method = METHOD_FALLBACK
        ranked = by_capacity_rule(candidates + stale)
        order = capacity_order

    if not ranked and far:
        # Nobody within the travel limit. A far hospital is still better than no answer.
        method = METHOD_FALLBACK
        ml_outcome = "NO_HOSPITAL_WITHIN_TRAVEL_LIMIT"
        ranked = by_capacity_rule(far)
        order = capacity_order
    else:
        for candidate in far:
            not_ranked.append(
                _not_ranked_entry(
                    candidate, "TOO_FAR", f"About {candidate['estimated_travel_minutes']} min away; the limit is {round(max_travel)} min."
                )
            )

    recommended = []
    for position, candidate in enumerate(ranked[: payload.max_results], start=1):
        reasons, warnings = _explain(candidate, method, max_age, max_travel)
        recommended.append({**candidate, "rank": position, "reasons": reasons, "warnings": warnings})

    return {
        "request_id": uuid.uuid4().hex,
        "generated_at": now,
        "triage": triage,
        "ranking": {
            "method": method,
            "ml_outcome": ml_outcome,
            "model_id": model.model_id if (model is not None and method == METHOD_ML) else None,
            "diversion_penalty_minutes": DIVERSION_PENALTY_MINUTES,
            "order": order,
            "hospitals_considered": len(hospitals),
            "is_reservation": False,
        },
        "recommended": recommended,
        "not_ranked": sorted(not_ranked, key=lambda entry: (entry.get("estimated_travel_minutes") or 0, entry["hospital_id"])),
        "disclaimer": DISCLAIMER,
    }


def _not_ranked_entry(candidate: dict[str, Any], reason: str, detail: str) -> dict[str, Any]:
    return {
        "hospital_id": candidate["hospital_id"],
        "name": candidate["name"],
        "reason": reason,
        "detail": detail,
        "distance_km": candidate["distance_km"],
        "estimated_travel_minutes": candidate["estimated_travel_minutes"],
        "live": candidate["live"],
    }


def _explain(candidate: dict[str, Any], method: str, max_age: float, max_travel: float) -> tuple[list[str], list[str]]:
    """Short sentences a dispatcher can read: why this hospital, and what to watch out for."""
    reasons: list[str] = []
    warnings: list[str] = []
    age_text = _age_text(candidate["report_age_minutes"])
    for resource in candidate["resources"]:
        words = RESOURCE_FIELDS[resource["resource_type"]][2]
        reasons.append(f"{resource['reported_available']} of {resource['total']} {words} reported free ({age_text})")
        if resource["reported_available"] < 1:
            warnings.append(f"No free {words} in the latest report")
        probability = resource["probability_available_at_arrival"]
        if probability is not None:
            reasons.append(f"{_percent(probability)} chance one of the {words} is still free on arrival (model estimate)")
    reasons.append(f"About {candidate['estimated_travel_minutes']} min away ({candidate['distance_km']:.1f} km, straight-line estimate)")
    if candidate["specialists_on_duty"]:
        reasons.append("Needed specialist on duty")
    for specialist in candidate["missing_specialists"]:
        warnings.append(f"No {specialist.lower()} listed on duty")
    if candidate["triage_status"] in ("ELEVATED", "CRITICAL"):
        warnings.append(f"Hospital reports {candidate['triage_status'].lower()} load")
    if candidate["report_age_minutes"] > max_age:
        warnings.append(f"Data is old (last report {age_text})")
    if candidate["estimated_travel_minutes"] > max_travel:
        warnings.append(f"Far away: about {candidate['estimated_travel_minutes']} min, and no hospital is closer than {round(max_travel)} min")
    if method == METHOD_FALLBACK:
        warnings.append("Ranked by the capacity rule; no model estimate")
    return reasons, warnings
