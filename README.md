# MedGraph

MedGraph is a small digital outpatient-book MVP. It provides a FastAPI backend, a Streamlit UI, and FalkorDB graph persistence. The backend runs directly on the host and connects to the Docker-published FalkorDB port at `localhost:6379`.

## Requirements

- Python 3.10+
- Docker with FalkorDB running locally
- Optional Gemini API key for hosted grounded chat summaries

The application does not download or run a local language model. Without `GEMINI_API_KEY`, chat still answers common history/report questions using deterministic responses based on FalkorDB data.

## Start FalkorDB

For reliable data persistence, run the database with a named volume:

```powershell
docker run --name MedGraph-falkordb -p 6379:6379 -p 3000:3000 -v "${PWD}\data:/var/lib/falkordb/data" -d falkordb/falkordb
```

The Python client connects to port `6379`. Port `3000` is the FalkorDB Browser UI. The graph named `MedGraph` is created on the first graph query.

## Install and configure

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `GEMINI_API_KEY` in `.env` to enable hosted Gemini responses. `GEMINI_MODEL` can select the model available to your API key. MedGraph uses Google's `google-genai` Python SDK (`client.models.generate_content`) rather than making direct HTTP requests. Only visit history is sent to Gemini for non-report questions. Report contents and attachments are never sent to a model; report questions are answered directly from FalkorDB.

## Run the backend and UI

In a PowerShell window:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

In another PowerShell window:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run ui\streamlit_app.py
```

Open <http://localhost:8501>. FastAPI docs are at <http://localhost:8000/docs>. Check database connectivity at <http://localhost:8000/health>.

## API

- `GET /patient/{id}` returns patient details, visits, prescriptions, and report text.
- `POST /visit` records a visit and its medicine nodes/relationships. JSON fields: `patient_id`, optional `patient_name`, `visit_date` (`YYYY-MM-DD`), `condition`, `medicines` (list of `{name, dosage?, frequency?, duration?}`), and optional `notes`.
- `POST /report` accepts multipart form fields `patient_id`, `visit_id`, `title`, `report_type`, and a `file` (PDF, TXT, or CSV). Report metadata and any extractable text are stored as a FalkorDB Report node connected to the visit. The original file bytes are saved unchanged under `uploads/reports` by default (`REPORT_STORAGE_DIR` can override this); the graph stores the generated attachment ID and original filename. Image-only/scanned PDFs are accepted without OCR or model analysis.
- `GET /report/{report_id}/file` downloads the original uploaded attachment.
- `POST /chat` accepts `{"message":"Show last visit for Patient 123"}` or an explicit `patient_id` and `message`.

## Graph shape

- `(:Patient {patient_id, name, created_at})-[:HAS_VISIT]->(:Visit {visit_id, visit_date, condition, notes})`
- `(:Visit)-[:PRESCRIBED {dosage, frequency, duration}]->(:Medicine {name})`
- `(:Visit)-[:HAS_REPORT]->(:Report {report_id, title, report_type, uploaded_at, content, attachment_id, original_filename})`

Uploads are preserved unchanged as local files, while report metadata and extracted text (when available) are stored in FalkorDB. The original binary PDF is not stored in FalkorDB; it is retained on the API host under `uploads/reports` and must be backed up separately. This directory is separate from the `data` directory commonly mounted into the FalkorDB Docker container. Image-only reports can be downloaded for clinician review but are not OCR'd or sent to Gemini.

## MVP limitations

Authentication/authorization is intentionally omitted per the requested scope. Do not expose this service or the FalkorDB port to untrusted networks or use it with real patient data until access controls, transport security, audit logging, backup, retention, and healthcare privacy/compliance requirements are addressed. The UI and API should be used on a trusted development machine.
