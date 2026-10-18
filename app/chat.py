import json
import re
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError
from fastapi import HTTPException

from app.config import settings

PATIENT_ID_PATTERN = re.compile(
    r"\bpatient(?:\s+id)?\s*[:#]?\s*([A-Za-z0-9_-]+)\b", re.IGNORECASE
)
REPORT_QUERY_TERMS = (
    "report",
    "mri",
    "scan",
    "x-ray",
    "x ray",
    "xray",
    "blood test",
    "blood report",
    "lab result",
    "ultrasound",
    "ct scan",
)


def find_patient_id(message: str) -> str | None:
    match = PATIENT_ID_PATTERN.search(message)
    return match.group(1) if match else None


def is_report_query(message: str) -> bool:
    lowered = message.lower()
    return any(term in lowered for term in REPORT_QUERY_TERMS)


def relevant_history(message: str, patient: dict[str, Any]) -> dict[str, Any]:
    lowered = message.lower()
    visits = patient["visits"]
    reports = patient["reports"]

    count_match = re.search(r"\blast\s+(\d+)\s+visits?\b", lowered)
    if count_match:
        visits = visits[: int(count_match.group(1))]
    elif "last visit" in lowered or "latest visit" in lowered:
        visits = visits[:1]

    report_terms = re.findall(r"\b(mri|ct|x[- ]?ray|blood|lab|scan|ultrasound)\b", lowered)
    if report_terms:
        reports = [
            report
            for report in reports
            if any(term.replace(" ", "") in report["report_type"].lower().replace(" ", "")
                   or term.replace(" ", "") in report["title"].lower().replace(" ", "")
                   for term in report_terms)
        ]

    return {
        "patient_id": patient["patient_id"],
        "name": patient["name"],
        "visits": visits,
        "reports": reports,
    }


def deterministic_answer(message: str, context: dict[str, Any]) -> str:
    if is_report_query(message):
        reports = context["reports"]
        if not reports:
            return "No matching medical reports were found in this patient's record."
        lines = [
            f"- {report['title']} ({report['report_type']}) uploaded {report['uploaded_at']}: "
            f"{report['content']}"
            for report in reports
        ]
        return "Matching reports:\n" + "\n".join(lines)

    visits = context["visits"]
    if not visits:
        return "No visits were found in this patient's record."
    lines = []
    for visit in visits:
        medicines = ", ".join(
            medicine["name"]
            + (f" ({medicine['dosage']})" if medicine.get("dosage") else "")
            for medicine in visit["medicines"]
        )
        entry = f"- {visit['visit_date']}: {visit['condition']}."
        if medicines:
            entry += f" Medicines: {medicines}."
        if visit.get("notes"):
            entry += f" Notes: {visit['notes']}"
        lines.append(entry)
    return "Relevant visit history:\n" + "\n".join(lines)


def answer_with_gemini(message: str, context: dict[str, Any]) -> str:
    system_instruction = (
        "Answer the doctor's question using only the patient record JSON provided. "
        "If the record does not contain the answer, say so. Do not diagnose, "
        "recommend treatment, or infer facts that are not present. "
        "Keep the response concise and cite visit dates when available."
    )
    prompt = (
        f"Doctor's question: {message}\n\nPatient record JSON:\n"
        f"{json.dumps(context, ensure_ascii=False)}"
    )
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
            ),
        )
    except APIError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {exc}") from exc

    answer = response.text
    if not answer or not answer.strip():
        raise HTTPException(status_code=502, detail="Gemini returned no text response.")
    return answer.strip()
