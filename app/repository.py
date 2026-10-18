from datetime import date
from typing import Any
from uuid import uuid4

from app.database import client, graph
from app.models import VisitCreate


def check_connection() -> bool:
    return bool(client.execute_command("PING"))


def initialize_graph() -> None:
    graph.query("MERGE (:MedGraphMetadata {key: 'initialized'})")


def fetch_patient(patient_id: str) -> dict[str, Any] | None:
    result = graph.ro_query(
        """
        MATCH (p:Patient {patient_id: $patient_id})
        RETURN p.patient_id AS patient_id, p.name AS name,
               p.created_at AS created_at
        """,
        {"patient_id": patient_id},
    )
    if not result.result_set:
        return None

    patient_row = result.result_set[0]
    visits_result = graph.ro_query(
        """
        MATCH (p:Patient {patient_id: $patient_id})-[:HAS_VISIT]->(v:Visit)
        OPTIONAL MATCH (v)-[rx:PRESCRIBED]->(m:Medicine)
        RETURN v.visit_id AS visit_id, v.visit_date AS visit_date,
               v.condition AS condition, v.notes AS notes,
               collect({name: m.name, dosage: rx.dosage,
                        frequency: rx.frequency, duration: rx.duration}) AS medicines
        ORDER BY v.visit_date DESC
        """,
        {"patient_id": patient_id},
    )
    reports_result = graph.ro_query(
        """
        MATCH (p:Patient {patient_id: $patient_id})-[:HAS_VISIT]->(v:Visit)
              -[:HAS_REPORT]->(r:Report)
        RETURN r.report_id AS report_id, v.visit_id AS visit_id,
               r.title AS title, r.report_type AS report_type,
               r.uploaded_at AS uploaded_at, r.content AS content,
               r.original_filename AS original_filename
        ORDER BY r.uploaded_at DESC
        """,
        {"patient_id": patient_id},
    )

    visits = []
    for row in visits_result.result_set:
        medicines = [
            medicine
            for medicine in (row[4] or [])
            if isinstance(medicine, dict) and medicine.get("name") is not None
        ]
        visits.append(
            {
                "visit_id": row[0],
                "visit_date": row[1],
                "condition": row[2],
                "notes": row[3],
                "medicines": medicines,
            }
        )

    reports = [
        {
            "report_id": row[0],
            "visit_id": row[1],
            "title": row[2],
            "report_type": row[3],
            "uploaded_at": row[4],
            "content": row[5],
            "original_filename": row[6],
            "download_url": f"/report/{row[0]}/file" if row[6] is not None else None,
        }
        for row in reports_result.result_set
    ]
    return {
        "patient_id": patient_row[0],
        "name": patient_row[1],
        "created_at": patient_row[2],
        "visits": visits,
        "reports": reports,
    }


def create_visit(visit: VisitCreate) -> dict[str, str]:
    visit_id = str(uuid4())
    graph.query(
        """
        MERGE (p:Patient {patient_id: $patient_id})
        ON CREATE SET p.name = $patient_name, p.created_at = $created_at
        SET p.name = CASE
            WHEN $patient_name IS NOT NULL AND (p.name IS NULL OR p.name = '')
            THEN $patient_name ELSE p.name END
        CREATE (v:Visit {
            visit_id: $visit_id, visit_date: $visit_date,
            condition: $condition, notes: $notes
        })
        CREATE (p)-[:HAS_VISIT]->(v)
        WITH v
        UNWIND $medicines AS medicine
        MERGE (m:Medicine {name: medicine.name})
        CREATE (v)-[rx:PRESCRIBED {
            dosage: medicine.dosage, frequency: medicine.frequency,
            duration: medicine.duration
        }]->(m)
        RETURN v.visit_id AS visit_id
        """,
        {
            "patient_id": visit.patient_id,
            "patient_name": visit.patient_name,
            "created_at": date.today().isoformat(),
            "visit_id": visit_id,
            "visit_date": visit.visit_date.isoformat(),
            "condition": visit.condition,
            "notes": visit.notes,
            "medicines": [medicine.model_dump() for medicine in visit.medicines],
        },
    )
    return {"visit_id": visit_id}


def create_report(
    patient_id: str,
    visit_id: str,
    title: str,
    report_type: str,
    content: str,
    uploaded_at: str,
    attachment_id: str,
    original_filename: str,
) -> dict[str, str] | None:
    report_id = str(uuid4())
    result = graph.query(
        """
        MATCH (p:Patient {patient_id: $patient_id})-[:HAS_VISIT]->(v:Visit {visit_id: $visit_id})
        CREATE (r:Report {
            report_id: $report_id, title: $title, report_type: $report_type,
            content: $content, uploaded_at: $uploaded_at,
            attachment_id: $attachment_id, original_filename: $original_filename
        })
        CREATE (v)-[:HAS_REPORT]->(r)
        RETURN r.report_id AS report_id
        """,
        {
            "patient_id": patient_id,
            "visit_id": visit_id,
            "report_id": report_id,
            "title": title,
            "report_type": report_type,
            "content": content,
            "uploaded_at": uploaded_at,
            "attachment_id": attachment_id,
            "original_filename": original_filename,
        },
    )
    if not result.result_set:
        return None
    return {
        "report_id": report_id,
        "visit_id": visit_id,
        "download_url": f"/report/{report_id}/file",
    }


def fetch_report_attachment(report_id: str) -> dict[str, str] | None:
    result = graph.ro_query(
        """
        MATCH (r:Report {report_id: $report_id})
        RETURN r.attachment_id AS attachment_id,
               r.original_filename AS original_filename
        """,
        {"report_id": report_id},
    )
    if not result.result_set:
        return None
    row = result.result_set[0]
    if not row[0] or not row[1]:
        return None
    return {"attachment_id": row[0], "original_filename": row[1]}
