"""Rule-based triage: patient condition -> severity and what the patient needs.

This is the same scoring the frontend uses (``src/lib/triage.ts``), moved to the
server so every client gets the same answer. ``tests/test_triage_rules.py``
replays cases produced by the frontend code and checks both sides agree.

Decision support only. It does not diagnose; a clinician makes the final call.
"""
from __future__ import annotations

from typing import Optional

SYMPTOM_KEYS: tuple[str, ...] = (
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
)

_SYMPTOM_POINTS: dict[str, tuple[int, str]] = {
    "unconscious": (5, "Patient is unconscious"),
    "bleeding": (4, "Severe bleeding"),
    "stroke": (4, "Stroke-like symptoms"),
    "breathing": (3, "Breathing difficulty"),
    "chest_pain": (3, "Chest pain"),
    "head_injury": (3, "Head injury"),
    "trauma": (3, "Accident / trauma"),
    "burns": (3, "Burns"),
    "seizure": (2, "Seizure"),
    "abdominal": (2, "Abdominal pain"),
    "fever": (1, "High fever"),
}

#: Frontend facility key -> specialist a hospital needs on duty for it.
SPECIALIST_FOR_FACILITY: dict[str, str] = {
    "trauma": "Trauma Surgeon",
    "cardiac": "Cardiologist",
    "neuro": "Neurologist",
    "burn": "Burn Specialist",
}
URGENCY_FOR_SEVERITY: dict[str, str] = {"critical": "CRITICAL", "high": "HIGH", "moderate": "MEDIUM", "low": "LOW"}
#: Needs the backend cannot check, because hospital snapshots do not carry this data.
UNCHECKED_FACILITIES: dict[str, str] = {
    "emergency": "free ER bays are not reported to the server",
    "bloodBank": "blood stock is not reported to the server",
}


def _number(value: float) -> str:
    """Print 88.0 as '88' and 39.8 as '39.8', as JavaScript does."""
    return str(int(value)) if float(value).is_integer() else str(value)


def assess_patient(
    symptoms: list[str],
    vitals: dict[str, Optional[float]],
    age: Optional[float] = None,
    described_as_severe: bool = False,
) -> dict:
    """Score the case. Returns severity, category, reasons and the facilities needed."""
    score = 0
    reasons: list[str] = []

    def add(points: int, why: str) -> None:
        nonlocal score
        score += points
        reasons.append(why)

    spo2, hr, sbp = vitals.get("spo2"), vitals.get("hr"), vitals.get("sbp")
    rr, temp, gcs = vitals.get("rr"), vitals.get("temp"), vitals.get("gcs")
    if spo2 is not None:
        if spo2 < 90:
            add(5, f"SpO₂ {_number(spo2)}% is very low")
        elif spo2 < 94:
            add(3, f"SpO₂ {_number(spo2)}% is low")
    if hr is not None:
        if hr > 130 or hr < 45:
            add(3, f"Heart rate {_number(hr)} is critical")
        elif hr > 110:
            add(2, f"Heart rate {_number(hr)} is high")
    if sbp is not None:
        if sbp < 90:
            add(4, f"Systolic BP {_number(sbp)} is low")
        elif sbp > 180:
            add(2, f"Systolic BP {_number(sbp)} is very high")
    if rr is not None:
        if rr > 30 or rr < 8:
            add(4, f"Respiratory rate {_number(rr)} is critical")
        elif rr > 24:
            add(2, f"Respiratory rate {_number(rr)} is raised")
    if temp is not None and (temp > 39.5 or temp < 35):
        add(2, f"Temperature {_number(temp)}°C is abnormal")
    if gcs is not None:
        if gcs <= 8:
            add(5, f"GCS {_number(gcs)}: severely reduced consciousness")
        elif gcs <= 12:
            add(3, f"GCS {_number(gcs)}: reduced consciousness")

    for key in symptoms:
        points, why = _SYMPTOM_POINTS[key]
        add(points, why)
    if described_as_severe and symptoms:
        add(2, "Described as severe")
    if age is not None and (age >= 65 or age <= 5):
        add(1, f"Age {_number(age)} is higher risk")

    severity = "critical" if score >= 7 else "high" if score >= 4 else "moderate" if score >= 2 else "low"
    has = set(symptoms).__contains__
    respiratory = has("breathing") or (spo2 is not None and spo2 < 92)

    if has("chest_pain") and respiratory:
        category = "Cardio-respiratory emergency"
    elif has("chest_pain"):
        category = "Cardiac emergency"
    elif respiratory:
        category = "Respiratory emergency"
    elif has("trauma") or has("bleeding"):
        category = "Major trauma"
    elif has("stroke") or has("head_injury") or has("seizure") or has("unconscious"):
        category = "Neurological emergency"
    elif has("burns"):
        category = "Burn injury"
    elif has("abdominal"):
        category = "Abdominal emergency"
    else:
        category = "General emergency"

    required: list[str] = ["emergency"]

    def need(key: str) -> None:
        if key not in required:
            required.append(key)

    serious = severity in ("critical", "high")
    if severity == "critical":
        need("icu")
    if has("chest_pain"):
        need("cardiac")
        if serious:
            need("icu")
    if respiratory and serious:
        need("icu")
    if respiratory and severity == "critical":
        need("ventilator")
    if has("trauma") or has("bleeding"):
        need("trauma")
        if serious:
            need("bloodBank")
    if has("stroke") or has("head_injury"):
        need("neuro")
    if has("seizure") and serious:
        need("neuro")
    if has("unconscious"):
        need("icu")
    if has("burns"):
        need("burn")

    return {"severity": severity, "category": category, "score": score, "reasons": reasons, "required": required}


def resources_needed(required_facilities: list[str]) -> list[str]:
    """Which counted resources the patient needs a free unit of.

    An ICU patient needs an ICU bed, not a general bed. A ventilator is always
    needed together with an ICU bed. Everyone else needs a general bed.
    """
    needed: list[str] = []
    if "icu" in required_facilities or "ventilator" in required_facilities:
        needed.append("ICU_BED")
    if "ventilator" in required_facilities:
        needed.append("VENTILATOR")
    if not needed:
        needed.append("GENERAL_BED")
    return needed


def specialists_needed(required_facilities: list[str]) -> list[str]:
    return [SPECIALIST_FOR_FACILITY[key] for key in required_facilities if key in SPECIALIST_FOR_FACILITY]
