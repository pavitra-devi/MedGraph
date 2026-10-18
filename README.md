# MedGraph: Clinical Context That Remembers

**MedGraph is a digital outpatient-book prototype that gives patient history a persistent graph structure.** It connects patients to visits, visits to prescribed medicines and reports, and lets a clinician retrieve that connected history by patient ID through search or chat.

The system consists of a Streamlit interface, a FastAPI service, FalkorDB for graph persistence, and optional hosted Gemini summaries. Patient and visit records remain in the graph across backend restarts; chat transcripts are not stored. MedGraph is a hackathon MVP focused on connected-record retrieval, not diagnosis or treatment recommendations.

## Hackathon submission

### Track

> **Submitting to Graph Hacks — Track 01: Agents That Act on Connected Data.**

MedGraph uses graph relationships to retrieve a patient's visits, prescriptions, and associated reports together, and retains those records in FalkorDB for later sessions. The current product has one API/chat flow. Multi-agent coordination and structured graph-path citations are planned enhancements.

### Submission checklist

| Requirement | MedGraph submission |
| --- | --- |
| Public source-code repository | [pavitra-devi/MedGraph on GitHub](https://github.com/pavitra-devi/MedGraph) |
| README, setup instructions, and graph data model | This README |
| Cypher queries / graph algorithms | See [Cypher and graph operations](#cypher-and-graph-operations) |
| Demo video | **YouTube demo:** https://youtu.be/KDf3FXspL_w |
| Live deployment or complete local setup | No live deployment is provided; follow [Local setup](#local-setup) |
| Track | **Track 01: Agents That Act on Connected Data** |

## How the system works

```text
Clinician
   |
   v
Streamlit UI (ui/streamlit_app.py)
   | HTTP requests
   v
FastAPI (app/main.py)
   | FalkorDB Python client       \ Optional Google GenAI SDK
   v                               v
FalkorDB graph                 Hosted Gemini
   |                           Receives visit history for
   |                           non-report questions only
   v
Patient / Visit / Medicine / Report nodes

Original report files -> API host's uploads/reports/ directory
                         (Report nodes store a reference to each file)
```

The UI talks to FastAPI; it does not access FalkorDB directly. FastAPI reads and writes graph records using parameterized Cypher queries. For non-report questions, Gemini can summarize visit history when configured. Without an API key, the app uses deterministic answers from the retrieved records. Report questions are answered from graph-backed report metadata and extracted text; report content and attachments are not sent to Gemini.

## FalkorDB usage

MedGraph uses the [FalkorDB](https://www.falkordb.com/) Python client and a named graph (default: `MedGraph`). The service connects to FalkorDB's Redis-compatible host and port, and initializes the graph when FastAPI starts. It uses Cypher to create and connect patient-care records and to traverse those connections for patient history.

FalkorDB stores patient, visit, medicine, prescription, and report metadata/text. Original uploaded PDF, TXT, and CSV bytes are kept unchanged on the API host under `uploads/reports/` by default—not inside FalkorDB. Back up that directory separately from FalkorDB's data volume. Scanned PDFs can be uploaded as-is; OCR-based text extraction is a planned enhancement.

### Graph data model

<img width="1102" height="565" alt="image" src="https://github.com/user-attachments/assets/7886d634-a81a-4934-b0d4-7a99a00b671b" />


<img width="1010" height="584" alt="image" src="https://github.com/user-attachments/assets/297be0c3-43a9-4190-a3ba-15f742ef87d5" />


```text
(:Patient {patient_id, name, created_at})
  -[:HAS_VISIT]->
(:Visit {visit_id, visit_date, condition, notes})
  -[:PRESCRIBED {dosage, frequency, duration}]->
(:Medicine {name})

(:Visit)-[:HAS_REPORT]->
(:Report {
  report_id, title, report_type, uploaded_at, content,
  attachment_id, original_filename
})
```

| Element | Properties | Meaning |
| --- | --- | --- |
| `Patient` | `patient_id`, `name`, `created_at` | Stable identity used to scope history lookups. |
| `Visit` | `visit_id`, `visit_date`, `condition`, `notes` | One encounter in the patient's history. |
| `Medicine` | `name` | Medicine referenced by a prescription. |
| `PRESCRIBED` | `dosage`, `frequency`, `duration` | Prescription details attached to a specific visit-to-medicine relationship. |
| `Report` | `report_id`, `title`, `report_type`, `uploaded_at`, `content`, `attachment_id`, `original_filename` | Report metadata and extracted text, plus a reference to the original local file. |

## Cypher and graph operations

MedGraph's current graph operations use Cypher writes and relationship traversals. Dedicated graph algorithms, such as shortest path or centrality, could be explored in future iterations.

**Initialize the named graph** with an idempotent marker:

```cypher
MERGE (:MedGraphMetadata {key: 'initialized'})
```

**Create a visit and connect its patient and medicines** (simplified from `create_visit`):

```cypher
MERGE (p:Patient {patient_id: $patient_id})
ON CREATE SET p.name = $patient_name, p.created_at = $created_at
CREATE (v:Visit {
  visit_id: $visit_id, visit_date: $visit_date,
  condition: $condition, notes: $notes
})
CREATE (p)-[:HAS_VISIT]->(v)
WITH v
UNWIND $medicines AS medicine
MERGE (m:Medicine {name: medicine.name})
CREATE (v)-[:PRESCRIBED {
  dosage: medicine.dosage, frequency: medicine.frequency,
  duration: medicine.duration
}]->(m)
```

**Retrieve a patient's visits and prescription details**:

```cypher
MATCH (p:Patient {patient_id: $patient_id})-[:HAS_VISIT]->(v:Visit)
OPTIONAL MATCH (v)-[rx:PRESCRIBED]->(m:Medicine)
RETURN v.visit_id AS visit_id, v.visit_date AS visit_date,
       v.condition AS condition, v.notes AS notes,
       collect({name: m.name, dosage: rx.dosage,
                frequency: rx.frequency, duration: rx.duration}) AS medicines
ORDER BY v.visit_date DESC
```

Report retrieval follows the same patient-to-visit path and then `HAS_REPORT` to collect reports. The implementation is in [`app/repository.py`](./app/repository.py).

## Local setup

### Requirements

- Python 3.10 or newer
- Docker Desktop (or Docker Engine) for local FalkorDB
- Gemini API key only if you want hosted Gemini summaries; it is optional

### 1. Start FalkorDB

From the project root in PowerShell:

```powershell
New-Item -ItemType Directory -Force data
docker run --name medgraph-falkordb -p 6379:6379 -p 3000:3000 -v "${PWD}\data:/var/lib/falkordb/data" -d falkordb/falkordb
```

The app uses port `6379`; FalkorDB's browser UI is available on port `3000`. The named host directory persists database data across container restarts.

### 2. Install dependencies and configure the environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` as needed. The repository includes `.env.example` with local defaults. Keep secrets in `.env` and do not commit that file.

#### `.env` variables

| Variable | Default | When to configure |
| --- | --- | --- |
| `FALKORDB_HOST` | `localhost` | FalkorDB hostname reachable from the API process. |
| `FALKORDB_PORT` | `6379` | FalkorDB port. |
| `FALKORDB_GRAPH` | `MedGraph` | Named graph selected by the application. |
| `FALKORDB_PASSWORD` | Empty / unset | Set only when the FalkorDB server requires a password. |
| `GEMINI_API_KEY` | Empty / unset | Optional; set to enable hosted Gemini responses for non-report history questions. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Gemini model name available to the configured API key. |
| `REPORT_STORAGE_DIR` | `<project>/uploads/reports` | Local directory for original uploaded report files. |
| `API_BASE_URL` | `http://localhost:8000` | FastAPI base URL used by the Streamlit UI. |
| `ALLOWED_ORIGINS` | `http://localhost:8501` | Comma-separated browser origins allowed by FastAPI CORS. |

The backend and UI read `.env` from the project working directory. With no `GEMINI_API_KEY`, chat uses deterministic responses based on the graph data.

### 3. Run the backend and UI

In one PowerShell window:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

In a second PowerShell window:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run ui\streamlit_app.py
```

Open the app at <http://localhost:8501>. FastAPI documentation is at <http://localhost:8000/docs>; the database health endpoint is <http://localhost:8000/health>.

## Features and API

- Search a patient by exact patient ID and view connected visits, prescriptions, and reports.
- Record a visit with its condition, notes, and prescribed medicines.
- Upload PDF, TXT, or CSV reports (maximum 10 MB); extracted text is stored with the report when available. Original file downloads are served by the API.
- Ask patient-scoped questions about visit history and report records.

Main endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Check FalkorDB connectivity. |
| `GET` | `/patient/{patient_id}` | Retrieve a patient's connected history. |
| `POST` | `/visit` | Save a visit and prescription relationships. |
| `POST` | `/report` | Upload a report for an existing patient visit. |
| `GET` | `/report/{report_id}/file` | Download the original report attachment. |
| `POST` | `/chat` | Ask a question with a patient ID and message. |

## Demo walkthrough

Use synthetic or de-identified data only.

1. Start FalkorDB, the API, and the Streamlit UI using the setup steps above.
2. Save more than one visit for a patient, including medicines and different dates.
3. Upload a report to a visit and search for the patient to review the connected records.
4. Ask about the latest visit, recent medicines, or a report in the Chat tab.
5. Restart the API and search again to demonstrate that graph records persist independently of API process memory.

**Working demo video:** https://youtu.be/KDf3FXspL_w

## Project structure

| Area | Source |
| --- | --- |
| FalkorDB connection and settings | [`app/database.py`](./app/database.py), [`app/config.py`](./app/config.py) |
| Cypher writes and patient-history traversal | [`app/repository.py`](./app/repository.py) |
| FastAPI endpoints and upload handling | [`app/main.py`](./app/main.py) |
| Local report attachment storage | [`app/report_storage.py`](./app/report_storage.py) |
| Chat routing and optional Gemini integration | [`app/chat.py`](./app/chat.py) |
| Streamlit interface | [`ui/streamlit_app.py`](./ui/streamlit_app.py) |
| Tests | [`tests/test_chat.py`](./tests/test_chat.py), [`tests/test_report_uploads.py`](./tests/test_report_uploads.py) |

## Future enhancements

MedGraph's current focus is a working graph-backed record-retrieval experience. Planned enhancements include:

- Authentication, authorization, and clinician roles for controlled access.
- OCR-based text extraction for scanned reports, with richer report exploration.
- Evidence citations and visible graph paths in chat responses, so clinicians can follow an answer to its connected records.
- Optional persistence of chat history with clear patient and session boundaries.
- Multi-agent coordination for workflows that benefit from shared graph context.
- Deployment-readiness features such as audit logging, configurable retention, secure transport, and appropriate privacy/compliance review.
