import os
from datetime import date

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 30


def response_error_detail(exc: requests.RequestException) -> str:
    response = exc.response
    if response is None:
        return str(exc)
    try:
        detail = response.json().get("detail", str(exc))
    except ValueError:
        return str(exc)
    if isinstance(detail, list):
        return "; ".join(
            item.get("msg", str(item)) if isinstance(item, dict) else str(item)
            for item in detail
        )
    return str(detail)


st.set_page_config(page_title="MedGraph", page_icon="🩺", layout="wide")
st.title("MedGraph")
st.caption("Digital outpatient visit history · Powered by FalkorDB")

search_tab, chat_tab = st.tabs(["Patient Search", "Chat"])

with search_tab:
    st.subheader("Patient record")
    with st.form("patient_search"):
        search_id = st.text_input("Patient ID", placeholder="e.g. 123")
        search_submit = st.form_submit_button("Search patient")

    if search_submit:
        if not search_id.strip():
            st.warning("Enter a patient ID.")
        else:
            try:
                response = requests.get(
                    f"{API_BASE_URL}/patient/{search_id.strip()}",
                    timeout=REQUEST_TIMEOUT,
                )
                if response.status_code == 404:
                    st.session_state.pop("patient_record", None)
                    st.error("Patient not found.")
                else:
                    response.raise_for_status()
                    st.session_state["patient_record"] = response.json()
            except requests.RequestException as exc:
                st.error(f"Could not reach MedGraph API: {exc}")

    patient = st.session_state.get("patient_record")
    if patient:
        st.markdown(f"### {patient.get('name') or 'Patient'}")
        st.write(f"**Patient ID:** {patient['patient_id']}")
        st.write(f"**Visits:** {len(patient['visits'])} · **Reports:** {len(patient['reports'])}")

        st.subheader("Visit history")
        if not patient["visits"]:
            st.info("No visits recorded.")
        for visit in patient["visits"]:
            with st.expander(f"{visit['visit_date']} · {visit['condition']}"):
                st.write(visit.get("notes") or "No visit notes.")
                if visit["medicines"]:
                    st.markdown("**Prescriptions**")
                    for medicine in visit["medicines"]:
                        details = ", ".join(
                            value for value in (
                                medicine.get("dosage"),
                                medicine.get("frequency"),
                                medicine.get("duration"),
                            ) if value
                        )
                        st.write(f"- {medicine['name']}" + (f" — {details}" if details else ""))

        st.subheader("Medical reports")
        if not patient["reports"]:
            st.info("No reports uploaded.")
        for report in patient["reports"]:
            with st.expander(f"{report['title']} · {report['report_type']} · {report['uploaded_at']}"):
                st.caption(f"Linked visit: {report['visit_id']}")
                if report.get("content"):
                    st.text(report["content"])
                elif report.get("original_filename", "").lower().endswith(".pdf"):
                    st.info("This report has no extractable text. Download the original PDF to review it.")
                if report.get("download_url"):
                    try:
                        file_response = requests.get(
                            f"{API_BASE_URL}{report['download_url']}",
                            timeout=REQUEST_TIMEOUT,
                        )
                        file_response.raise_for_status()
                        st.download_button(
                            "Download original report",
                            data=file_response.content,
                            file_name=report.get("original_filename", report["title"]),
                            mime=file_response.headers.get("content-type", "application/octet-stream"),
                            key=f"download-{report['report_id']}",
                        )
                    except requests.RequestException as exc:
                        st.error(f"Could not load report attachment: {response_error_detail(exc)}")

    st.divider()
    st.subheader("Record a visit")
    with st.form("visit_form"):
        visit_patient_id = st.text_input("Patient ID", key="visit_patient_id")
        patient_name = st.text_input("Patient name (used when creating a new patient)")
        visit_date = st.date_input("Visit date", value=date.today())
        condition = st.text_input("Condition")
        notes = st.text_area("Clinical notes")
        medicine_text = st.text_input("Medicines (comma-separated)")
        visit_submit = st.form_submit_button("Save visit")
    if visit_submit:
        payload = {
            "patient_id": visit_patient_id.strip(),
            "patient_name": patient_name.strip() or None,
            "visit_date": visit_date.isoformat(),
            "condition": condition.strip(),
            "notes": notes.strip() or None,
            "medicines": [
                {"name": name.strip()}
                for name in medicine_text.split(",")
                if name.strip()
            ],
        }
        try:
            response = requests.post(
                f"{API_BASE_URL}/visit",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            st.success(f"Visit saved (ID: {response.json()['visit_id']}). Search the patient to refresh.")
        except requests.RequestException as exc:
            st.error(f"Could not save visit: {exc}")

    st.subheader("Upload a medical report")
    with st.form("report_form"):
        report_patient_id = st.text_input("Patient ID", key="report_patient_id")
        report_visit_id = st.text_input("Visit ID")
        report_title = st.text_input("Report title")
        report_type = st.selectbox("Report type", ["Blood test", "MRI", "CT", "X-ray", "Other"])
        report_file = st.file_uploader("Report file (PDF, TXT, or CSV)", type=["pdf", "txt", "csv"])
        report_submit = st.form_submit_button("Upload report")
    if report_submit:
        if report_file is None:
            st.warning("Choose a report file.")
        elif not all(
            value.strip()
            for value in (
                report_patient_id,
                report_visit_id,
                report_title,
                report_type,
            )
        ):
            st.warning("Patient ID, Visit ID, report title, and report type are required.")
        else:
            data = {
                "patient_id": report_patient_id.strip(),
                "visit_id": report_visit_id.strip(),
                "title": report_title.strip(),
                "report_type": report_type,
            }
            try:
                response = requests.post(
                    f"{API_BASE_URL}/report",
                    data=data,
                    files={"file": (report_file.name, report_file.getvalue(), report_file.type)},
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                st.success(f"Report saved (ID: {response.json()['report_id']}). Search the patient to refresh.")
            except requests.RequestException as exc:
                st.error(f"Could not upload report: {response_error_detail(exc)}")

with chat_tab:
    st.subheader("Ask about a patient")
    st.caption("Enter the patient ID separately from your question.")
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []
    for item in st.session_state["chat_messages"]:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])

    with st.form("patient_chat_form", clear_on_submit=True):
        patient_id_column, question_column = st.columns([1, 4])
        with patient_id_column:
            chat_patient_id = st.text_input(
                "Patient ID",
                placeholder="123",
                max_chars=100,
            )
        with question_column:
            chat_question = st.text_area(
                "Question",
                placeholder="Ask about this patient's visits, medicines, or reports…",
                max_chars=4_000,
                height=100,
            )
        chat_submit = st.form_submit_button("Ask")

    if chat_submit:
        if not chat_patient_id.strip():
            st.warning("Enter a patient ID.")
        elif not chat_question.strip():
            st.warning("Enter a question.")
        else:
            prompt = chat_question.strip()
            display_prompt = f"Patient {chat_patient_id.strip()}: {prompt}"
            st.session_state["chat_messages"].append(
                {"role": "user", "content": display_prompt}
            )
            with st.chat_message("user"):
                st.markdown(display_prompt)
            with st.chat_message("assistant"):
                with st.spinner("Looking up the patient record…"):
                    try:
                        response = requests.post(
                            f"{API_BASE_URL}/chat",
                            json={
                                "patient_id": chat_patient_id.strip(),
                                "message": prompt,
                            },
                            timeout=45,
                        )
                        response.raise_for_status()
                        result = response.json()
                        answer = result["answer"]
                        st.markdown(answer)
                        st.caption(
                            f"Patient {result['patient_id']} · source: {result['source']}"
                        )
                    except requests.RequestException as exc:
                        answer = f"Request failed: {response_error_detail(exc)}"
                        st.error(answer)
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": answer}
            )
