# MedGraph: Clinical Context That Remembers

## Project overview

**MedGraph** is a digital outpatient-book prototype for clinicians. It turns a patient's visits, prescriptions, and reports into connected FalkorDB records, then retrieves that connected history for patient search and a conversational interface.

The core idea is that a medical record is not just a collection of notes. A medicine belongs to a particular visit; a report belongs to a particular visit; and each visit belongs to a patient. MedGraph represents those relationships directly so a query can follow the patient's graph rather than guess which isolated record is relevant.

> **One-line pitch:** Give a clinician a patient-scoped, persistent graph memory they can search conversationally and use to revisit the connected history behind a patient's care.

MedGraph is a hackathon MVP and a record-retrieval aid. It does not diagnose, recommend treatment, interpret medical images, or replace clinical judgment.

## The challenge and MedGraph's track

The Graph Hacks brief asks builders to make a graph shape an agent's context and decisions: follow connections, retain useful memory, coordinate state, and explain answers.

MedGraph's closest fit is **Track 01: Agents That Act on Connected Data**:

| Challenge theme | MedGraph today |
| --- | --- |
| Follow connections across data | Patient lookup traverses `HAS_VISIT`, then retrieves `PRESCRIBED` medicines and `HAS_REPORT` reports through their visit relationships. |
| Remember across sessions | Patient, visit, prescription, and report metadata are persisted in FalkorDB, not only in Streamlit session state. A future visit can retrieve the previous graph records by patient ID. |
| Share state between agents | Not implemented. MedGraph currently has one API/chat flow and no multi-agent coordination. |
| Show the path behind an answer | Graph traversal grounds retrieval in connected records, but the current chat response does not yet return a structured traversal path or evidence citations. This is a clear next enhancement, not a claimed shipped feature. |

The graph is the context source for patient history, not a sidecar database that the chat ignores.

## The problem

During an outpatient visit, clinicians may need to recall a patient's previous conditions, prescriptions, or test reports. Those details are connected by patient and visit, but can be difficult to find if they are scattered across separate records.

MedGraph offers a focused workflow:

1. Identify the patient explicitly by patient ID.
2. Retrieve the patient's connected visit history, prescriptions, and report metadata.
3. Ask a question about that patient's record.
4. Review a report attachment in its original form when needed.

The explicit patient-ID field is intentionally separate from the question. The application does not have to guess which number in natural language is a patient identifier.

## Architecture

```text
Clinician
   |
   v
Streamlit UI (ui/streamlit_app.py)
   | HTTP: patient search, visits, report uploads/downloads, chat
   v
FastAPI (app/main.py)
   |                         \
   | FalkorDB Python client   \ Google GenAI SDK (optional)
   v                           v
FalkorDB graph                 Hosted Gemini
   |                           Receives visit history only
   |                           for non-report questions
   v
Patient / Visit / Medicine / Report nodes

Original uploaded file bytes
   |
   v
Local API-host directory: uploads/reports/
   (attachment ID and original filename are linked from the Report node)
```

The backend runs as a regular Python process and connects to FalkorDB at the configured Redis-compatible host and port. The Streamlit frontend calls FastAPI; it does not query FalkorDB directly.

## Graph data model

```text
(:Patient)-[:HAS_VISIT]->(:Visit)
                         ├──[:PRESCRIBED {
                         │      dosage, frequency, duration
                         │  }]->(:Medicine)
                         └──[:HAS_REPORT]->(:Report)
```

### Nodes and relationships

| Graph element | Example properties | Purpose |
| --- | --- | --- |
| `Patient` | `patient_id`, `name`, `created_at` | Stable patient identity used to scope search and chat. |
| `Visit` | `visit_id`, `visit_date`, `condition`, `notes` | One encounter in the patient's longitudinal history. |
| `Medicine` | `name` | A medicine referenced by a prescription. |
| `PRESCRIBED` relationship | `dosage`, `frequency`, `duration` | Prescription details specific to the visit-to-medicine connection. |
| `Report` | `report_id`, `title`, `report_type`, `uploaded_at`, `content`, `attachment_id`, `original_filename` | Searchable report metadata/text plus a reference to the original local attachment. |

The corresponding graph pattern is:

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

## How graph creation and memory work

### Selecting and initializing the graph

`app/database.py` reads `FALKORDB_GRAPH` and selects that graph through the official `FalkorDB` Python client. The current default is `MedGraph`.

During FastAPI startup, `initialize_graph` in `app/repository.py` executes:

```cypher
MERGE (:MedGraphMetadata {key: 'initialized'})
```

FalkorDB creates a named graph automatically on its first graph query. The metadata `MERGE` is an initialization marker; actual patient records are created by the visit/report write operations.

### Saving a visit

The Streamlit form posts the visit to `POST /visit`. FastAPI validates the payload and calls `create_visit` in `app/repository.py`. Its Cypher operation:

1. `MERGE`s a `Patient` using the supplied `patient_id`, creating that patient if necessary.
2. Creates a new `Visit` node with its own generated ID and the visit date, condition, and notes.
3. Connects patient to visit with `HAS_VISIT`.
4. For each submitted medicine, matches or creates a `Medicine` node and creates a `PRESCRIBED` relationship with dosage/frequency/duration.

Each saved visit is a new event. An existing patient's previous visit nodes remain connected, so later retrieval can assemble a longitudinal history.

### Saving a report

The report upload endpoint accepts PDF, TXT, and CSV files:

- The original upload bytes are saved unchanged under `uploads/reports/` by default. `REPORT_STORAGE_DIR` can override this location.
- Extractable text is stored as the `Report.content` property when available. An image-only/scanned PDF is still accepted with empty extracted text.
- FalkorDB stores a `Report` node linked to the selected `Visit` with `HAS_REPORT`. Its `attachment_id` and `original_filename` properties point the API to the local file.
- `GET /report/{report_id}/file` retrieves the attachment through the API for download in the UI.

The binary PDF itself is **not** stored in FalkorDB. The local attachment directory must be backed up separately from the FalkorDB Docker data directory.

## How patient search follows the graph

The Search tab calls `GET /patient/{patient_id}`. `fetch_patient` in `app/repository.py` uses read-only parameterized Cypher queries to:

1. Match the `Patient` by exact `patient_id`.
2. Follow `(:Patient)-[:HAS_VISIT]->(:Visit)` to retrieve visits.
3. Optionally follow `(:Visit)-[:PRESCRIBED]->(:Medicine)` to retrieve medicines and prescription relationship properties.
4. Follow `(:Patient)-[:HAS_VISIT]->(:Visit)-[:HAS_REPORT]->(:Report)` to retrieve reports associated with those visits.
5. Sort visits by visit date and reports by upload time.

Simplified example of the visit/medicine traversal:

```cypher
MATCH (p:Patient {patient_id: $patient_id})-[:HAS_VISIT]->(v:Visit)
OPTIONAL MATCH (v)-[rx:PRESCRIBED]->(m:Medicine)
RETURN v.visit_id, v.visit_date, v.condition, v.notes,
       collect({
         name: m.name,
         dosage: rx.dosage,
         frequency: rx.frequency,
         duration: rx.duration
       }) AS medicines
ORDER BY v.visit_date DESC
```

This is a graph lookup, not a free-text search across unrelated notes: the patient ID identifies a specific patient node, and the edges determine which visits, prescriptions, and reports belong in the returned record.

## How chat uses graph memory

1. The clinician enters **Patient ID** and a separate question in the Chat tab.
2. The UI sends both values in `POST /chat`, for example:

   ```json
   {
     "patient_id": "123",
     "message": "Which medicines were prescribed in the last 3 visits?"
   }
   ```

3. FastAPI retrieves that patient's connected history from FalkorDB.
4. The request is handled according to its type:
   - **Report question:** returns matching report records directly from FalkorDB-backed context. Report text and attachments are not sent to Gemini.
   - **Other history question with `GEMINI_API_KEY`:** sends patient visit history (not reports or attachment bytes) to the configured hosted Gemini model for a grounded summary.
   - **Without a Gemini API key:** uses deterministic responses over the retrieved context.
5. The response identifies the patient and reports its source.

Report questions in this MVP are limited to records and extracted text. The system does not visually inspect, OCR, or interpret X-rays or other report images. Clinicians can download the original report and review it themselves.

## What persists—and what does not

| Information | Where it lives | Persists across backend restarts? |
| --- | --- | --- |
| Patient nodes, visits, medicines, prescription edges, report metadata/text | FalkorDB graph | Yes, subject to FalkorDB data-volume configuration. |
| Original PDF/TXT/CSV upload | API host under `uploads/reports/` by default | Yes, as a local file, but it must be backed up separately. |
| Current visible Streamlit page state/chat transcript | Streamlit session state | Not a durable conversation archive. |
| Chat prompt/answer history as patient-memory nodes | Not implemented | No. |

MedGraph's persistent memory is the clinical graph data entered through its workflows. It does not claim to remember prior chat turns as conversation memory. On a later visit, the clinician identifies the patient again and the app retrieves the persisted graph history.

## Explainability: current capability and next step

### Implemented now

- Patient ID scopes every chat and search request.
- The answer context is retrieved from graph-connected patient visits and related records.
- The chat response includes the selected patient ID and a source label.
- The UI presents dated visits, medicines, and report associations so a clinician can inspect the returned underlying record.

### Not implemented yet

The current chat API does not return a machine-readable evidence list or explicit path such as:

```text
Patient 123
  -> HAS_VISIT -> Visit on 2026-10-18
  -> PRESCRIBED -> Medicine A (10 mg)
```

The graph traversal is what selects the context, but the UI does not yet display that exact traversal as provenance beside each answer. A high-value next step is to return evidence records from the same query—for example, visit IDs/dates and report IDs/titles—and render them as clickable citations in chat.

## Hackathon demo walkthrough

Use synthetic or de-identified records only.

1. Start FalkorDB, the FastAPI backend, and the Streamlit UI.
2. Save multiple visits for one patient, including different medicines and visit dates.
3. Upload a text-based report and an image-only sample PDF to distinct visits.
4. Search by patient ID. Show how visits, prescriptions, and reports are assembled through graph relationships.
5. In Chat, enter the ID separately and ask for the last visit or medicines from the last three visits.
6. Ask for the image-only report; show that it is linked to the visit and can be downloaded as-is, without sending it to a model.
7. Restart the backend and search the same patient again to demonstrate that graph records persist independently of API process memory.
8. Explain the honest boundary: patient records are durable graph memory; chat transcripts are not yet stored.

## Implementation map

| Area | Source |
| --- | --- |
| FalkorDB connection and graph selection | [`app/database.py`](./app/database.py), [`app/config.py`](./app/config.py) |
| Cypher graph initialization, writes, and traversals | [`app/repository.py`](./app/repository.py) |
| FastAPI routes, upload handling, and attachment downloads | [`app/main.py`](./app/main.py) |
| Local original-file storage | [`app/report_storage.py`](./app/report_storage.py) |
| Question routing and hosted Gemini integration | [`app/chat.py`](./app/chat.py) |
| Search, chat, visit-entry, and report UI | [`ui/streamlit_app.py`](./ui/streamlit_app.py) |
| Automated behavior checks | [`tests/test_chat.py`](./tests/test_chat.py), [`tests/test_report_uploads.py`](./tests/test_report_uploads.py) |

## Run the demo

From the project root in PowerShell, activate the virtual environment and run the backend:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

In another PowerShell window:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run ui\streamlit_app.py
```

Open <http://localhost:8501> for the app and <http://localhost:8000/docs> for the API. Ensure FalkorDB is reachable at the host/port configured in `.env`.

## Scope, safety, and next milestones

### Current MVP boundaries

- No authentication or authorization is implemented.
- The app is a development prototype, not a production clinical system.
- Gemini is optional and hosted. When enabled, non-report questions may send visit history to the configured provider; report content and attachments are excluded.
- Image-only reports are stored as files and linked in the graph; there is no OCR or image analysis.
- Chat transcripts are not persisted.
- The graph provides connected retrieval, but explicit path/evidence citations in chat are future work.
- Original attachment files are local to the API host and need separate backup/retention controls.

Do not expose the app publicly or use it with identifiable real patient records without appropriate authentication, authorization, encryption, audit logging, data governance, backup/recovery, and healthcare privacy/compliance review.

### Suggested next milestones

1. Return and display evidence IDs and graph paths for every answer.
2. Add indexes/constraints and measure graph-query latency with a representative dataset.
3. Add authenticated clinician identity and access controls.
4. Add auditable, opt-in conversation memory linked to patient/session with strict privacy boundaries.
5. Add retention and backup management for local attachments.
6. Evaluate grounded answer quality using synthetic cases and clinician review; never treat generated summaries as autonomous medical decisions.
