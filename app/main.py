from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
import logging
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from redis.exceptions import RedisError

from app.chat import (
    answer_with_gemini,
    deterministic_answer,
    find_patient_id,
    is_report_query,
    relevant_history,
)
from app.config import settings
from app.models import ChatRequest, ChatResponse, VisitCreate
from app import repository
from app import report_storage

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        repository.initialize_graph()
    except RedisError as exc:
        raise RuntimeError(f"Could not initialize the FalkorDB graph: {exc}") from exc
    yield


app = FastAPI(title="MedGraph API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

MAX_REPORT_BYTES = 10 * 1024 * 1024
MAX_REPORT_CHARS = 200_000


@app.get("/health")
def health() -> dict[str, str]:
    try:
        connected = repository.check_connection()
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"FalkorDB is unavailable: {exc}") from exc
    if not connected:
        raise HTTPException(status_code=503, detail="FalkorDB health check failed.")
    return {"status": "ok", "database": "falkordb"}


@app.get("/patient/{patient_id}")
def get_patient(patient_id: str) -> dict:
    try:
        patient = repository.fetch_patient(patient_id)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"FalkorDB query failed: {exc}") from exc
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient was not found.")
    return patient


@app.post("/visit", status_code=201)
def add_visit(visit: VisitCreate) -> dict[str, str]:
    try:
        return repository.create_visit(visit)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"Could not save visit to FalkorDB: {exc}") from exc


async def read_report(file: UploadFile) -> tuple[bytes, str]:
    raw = await file.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise HTTPException(status_code=413, detail="Report files must be 10 MB or smaller.")

    content_type = (file.content_type or "").lower()
    filename = report_storage.safe_original_filename(file.filename)
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"pdf", "txt", "csv"}:
        raise HTTPException(status_code=415, detail="Upload a PDF, TXT, or CSV report.")

    text = ""
    if content_type == "application/pdf" or suffix == "pdf":
        try:
            reader = PdfReader(BytesIO(raw))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError:
            logger.warning("Could not extract text from uploaded PDF %s.", filename)
    elif content_type.startswith("text/") or suffix in {"txt", "csv"}:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            logger.warning("Could not decode text from uploaded report %s.", filename)

    text = text.strip()
    if len(text) > MAX_REPORT_CHARS:
        logger.warning("Skipping extracted text larger than the report text limit: %s.", filename)
        text = ""
    return raw, text


@app.post("/report", status_code=201)
async def add_report(
    patient_id: str = Form(min_length=1, max_length=100),
    visit_id: str = Form(min_length=1, max_length=100),
    title: str = Form(min_length=1, max_length=300),
    report_type: str = Form(min_length=1, max_length=100),
    file: UploadFile = File(...),
) -> dict[str, str]:
    raw, content = await read_report(file)
    original_filename = report_storage.safe_original_filename(file.filename)
    attachment_id = str(uuid4())
    try:
        await run_in_threadpool(
            report_storage.save_attachment,
            attachment_id,
            original_filename,
            raw,
        )
    except OSError as exc:
        logger.exception("Could not save uploaded report attachment.")
        raise HTTPException(
            status_code=500,
            detail="Could not save the original report file on the server.",
        ) from exc

    try:
        report = await run_in_threadpool(
            repository.create_report,
            patient_id,
            visit_id,
            title,
            report_type,
            content,
            datetime.now(timezone.utc).isoformat(),
            attachment_id,
            original_filename,
        )
    except RedisError as exc:
        try:
            await run_in_threadpool(
                report_storage.remove_attachment,
                attachment_id,
                original_filename,
            )
        except OSError:
            logger.exception("Could not remove an unlinked report attachment.")
        raise HTTPException(status_code=503, detail=f"Could not save report to FalkorDB: {exc}") from exc
    if report is None:
        try:
            await run_in_threadpool(
                report_storage.remove_attachment,
                attachment_id,
                original_filename,
            )
        except OSError:
            logger.exception("Could not remove an unlinked report attachment.")
        raise HTTPException(
            status_code=404,
            detail="The specified patient visit was not found; report was not saved.",
        )
    return report


@app.get("/report/{report_id}/file")
def download_report_file(report_id: str) -> FileResponse:
    try:
        attachment = repository.fetch_report_attachment(report_id)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"FalkorDB query failed: {exc}") from exc
    if attachment is None:
        raise HTTPException(status_code=404, detail="Report attachment was not found.")
    try:
        path = report_storage.find_attachment(
            attachment["attachment_id"],
            attachment["original_filename"],
        )
    except ValueError as exc:
        logger.exception("Invalid attachment metadata for report %s.", report_id)
        raise HTTPException(status_code=500, detail="Report attachment metadata is invalid.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The original report file is missing from local storage.")
    return FileResponse(
        path,
        filename=attachment["original_filename"],
        media_type={
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".csv": "text/csv",
        }[path.suffix.lower()],
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    patient_id = request.patient_id or find_patient_id(request.message)
    if patient_id is None:
        raise HTTPException(
            status_code=422,
            detail="Include a patient ID in the request or ask about 'Patient 123'.",
        )
    try:
        patient = await run_in_threadpool(repository.fetch_patient, patient_id)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"FalkorDB query failed: {exc}") from exc
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient was not found.")

    context = relevant_history(request.message, patient)
    if is_report_query(request.message):
        answer = deterministic_answer(request.message, context)
        source = "falkordb"
    elif settings.gemini_api_key:
        model_context = {
            "patient_id": context["patient_id"],
            "name": context["name"],
            "visits": context["visits"],
        }
        answer = await run_in_threadpool(
            answer_with_gemini,
            request.message,
            model_context,
        )
        source = f"falkordb+{settings.gemini_model}"
    else:
        answer = deterministic_answer(request.message, context)
        source = "falkordb"
    return ChatResponse(patient_id=patient_id, answer=answer, source=source)
