# TriageAide — FHIR-First Pre-Consultation Triage

TriageAide is an AI agent that retrieves a patient's FHIR clinical history, conducts a personalized pre-consultation triage via chat, and writes structured triage results back to the FHIR server — so the physician receives a ready-made clinical summary before the appointment.

> "TriageAide first retrieves patient history from a FHIR server, builds contextual clinical understanding, and performs an adaptive pre-consultation triage that enriches and updates the longitudinal patient record."

TriageAide is an autonomous AI agent that operates **on top of FHIR data** — it queries the patient's clinical history from a FHIR server (InterSystems IRIS for Health), conducts an intelligent contextual pre-consultation triage, and writes new FHIR resources back to the patient record.

This is **not** a generic chatbot that generates FHIR from scratch. It is an interoperable AI agent that reasons over existing clinical data:

1. **FHIR-First** — consults patient history BEFORE interacting with the patient
2. **Contextual Triage** — asks intelligent questions based on real clinical history, not generic checklists
3. **Bidirectional** — reads from AND writes back to the FHIR server
4. **Longitudinal** — understands care continuity (e.g., "last visit 8 months ago — follow-up overdue")

## 5-Step Workflow

1. **FHIR Query** — Agent retrieves Patient, Condition, MedicationRequest, Observation, AllergyIntolerance, Encounter
2. **Contextual Triage** — With history in hand, generates intelligent, personalized questions
3. **Interactive Conversation** — Chat loop: agent asks one question at a time, patient responds, agent deepens
4. **Clinical Reasoning** — Cross-references FHIR history + new symptoms → risk assessment, priority suggestion
5. **FHIR Update** — Creates Observation, QuestionnaireResponse, Flag, Task, Encounter back on the server

## Architecture

```
FHIR Server (InterSystems IRIS for Health)
    |
    +-- fhir_server.py          (MCP :8000) — 12 FHIR CRUD tools
    +-- triage_server.py        (MCP :8001) — 4 contextual triage tools
    +-- clinical_reasoning_server.py (MCP :8002) — 4 clinical reasoning tools
    |
    +-- agent.py  (LangChain + OpenAI gpt-4o-mini) — core agent, system prompt
    +-- cli.py    — interactive CLI interface
    +-- app.py    (Gradio :7860) — web chat UI
```

3 specialized MCP servers expose 20 tools via [FastMCP](https://github.com/jlowin/fastmcp) (streamable-http transport). A LangChain agent orchestrates them with a detailed system prompt that enforces the 5-step workflow and one-question-at-a-time conversation rules.

## Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop) + Docker Compose
- OpenAI API key (gpt-4o-mini)

## How to Run

1. Copy the environment template and set your OpenAI API key:

```bash
cd python/triage
cp .env.example .env
# Edit .env and paste your real OPENAI_API_KEY
```

2. Build and start the container:

```bash
docker compose build --no-cache --progress=plain
docker compose up -d
```

3. Open the Gradio UI: **http://localhost:7860**

All MCP servers start automatically on container boot via `custom-entrypoint.sh` → `start_mcp_servers.sh`. Test patients (4 scenarios) are loaded automatically on first boot.

### Running Manually (inside the container)

For debugging:

```bash
docker compose exec iris bash
cd /home/irisowner/irisdev/python/triage
bash start_servers.sh
```

Or start each component separately:

```bash
# Terminal 1: FHIR MCP Server
FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 fhir_server.py

# Terminal 2: Triage MCP Server
python3 triage_server.py

# Terminal 3: Clinical Reasoning MCP Server
python3 clinical_reasoning_server.py

# Terminal 4: Gradio UI
FHIR_BASE_URL=http://localhost:52773/fhir/r4 OPENAI_API_KEY=sk-... python3 app.py
```

## Test Patients

4 patients with distinct clinical scenarios are loaded via `seed_data.py`:

| Patient | Age | Conditions | Expected Scenario |
|---|---|---|---|
| **Maria Silva** | 58, F | DM2 + Hypertension + HbA1c 8.2% | Uncontrolled diabetes, elevated cardiovascular risk |
| **Joao Santos** | 72, M | HF + AFib + DM2 + HTN + CKD stage 3 | Polypharmacy, drug interactions, high risk |
| **Ana Costa** | 28, F | No active conditions | Generic questions, no red flags, routine priority |
| **Roberto Lima** | 65, M | COPD + HTN + Osteoarthritis + Depression + SpO2 93% | Respiratory red flags, severe allergy (anaphylaxis), urgent priority |

To reload test data (inside the container):

```bash
FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py clean
FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py load
```

To list loaded patients:

```bash
FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py list
```

> **Note:** Patient IDs change on each reload. Use the patient name when talking to the agent.

## File Structure

```
python/triage/
  .env                    # Config (FHIR_BASE_URL, OPENAI_API_KEY) — NOT tracked in git
  .env.example            # Template without credentials
  requirements.txt        # Python dependencies
  seed_data.py            # Load/clean/list test patients
  seed_data/              # FHIR Bundle JSON files for 4 test patients
    patient_maria_silva.json
    patient_joao_santos.json
    patient_ana_costa.json
    patient_roberto_lima.json
  fhir_server.py                  # MCP Server 1 — FHIR CRUD (port 8000)
  triage_server.py                # MCP Server 2 — Contextual triage (port 8001)
  clinical_reasoning_server.py    # MCP Server 3 — Clinical reasoning (port 8002)
  agent.py                        # Core agent (SYSTEM_PROMPT, create_triage_agent, extract_ai_response)
  cli.py                          # Interactive CLI interface
  app.py                          # Gradio web chat UI (port 7860)
  start_servers.sh                # Manual start script (MCP servers + Gradio)
  PLAN.md                         # Architecture plan & tool specs
  PROGRESS.md                     # Progress history & technical discoveries
  README.md                       # This file
```

## MCP Servers & Tools

### fhir_server.py (port 8000) — 12 FHIR CRUD tools

| Tool | FHIR Method | Description |
|---|---|---|
| `search_patients` | GET /Patient?name={name} | Search patients by name (partial match) |
| `get_patient` | GET /Patient/{id} | Demographics |
| `get_patient_conditions` | GET /Condition?patient={id} | Conditions |
| `get_patient_medications` | GET /MedicationRequest?patient={id} | Medications |
| `get_patient_observations` | GET /Observation?patient={id} | Observations |
| `get_patient_allergies` | GET /AllergyIntolerance?patient={id} | Allergies |
| `get_patient_encounters` | GET /Encounter?patient={id} | Encounters |
| `create_observation` | POST /Observation | New observation |
| `create_condition` | POST /Condition | New condition |
| `create_questionnaire_response` | POST /QuestionnaireResponse | Structured triage |
| `create_encounter` | POST /Encounter | Pre-consultation encounter |
| `create_flag_and_task` | POST /Flag + POST /Task | Alert + follow-up task |

### triage_server.py (port 8001) — 4 contextual triage tools

| Tool | Description |
|---|---|
| `build_contextual_questions` | Generates contextual questions based on FHIR history |
| `parse_symptoms` | Extracts symptoms, duration, severity from patient text |
| `check_red_flags` | Cross-references symptoms with existing conditions for warning signs |
| `build_questionnaire_response_data` | Assembles FHIR QuestionnaireResponse |

### clinical_reasoning_server.py (port 8002) — 4 clinical reasoning tools

| Tool | Description |
|---|---|
| `assess_clinical_risk` | Risk score with justification |
| `suggest_priority` | Care priority (routine/urgent/emergency) |
| `generate_clinical_summary` | Summary for the physician |
| `identify_follow_up_tasks` | Follow-up tasks based on risk and care gaps |

## Ports

| Host | Container | Service |
|---|---|---|
| 8000 | 8000 | FHIR MCP Server |
| 8001 | 8001 | Triage MCP Server |
| 8002 | 8002 | Clinical Reasoning MCP Server |
| 7860 | 7860 | Gradio Web UI |
| 32783 | 52773 | FHIR API (IRIS for Health) |

## Tech Stack

| Component | Technology |
|---|---|
| FHIR Server | InterSystems IRIS for Health Community Edition |
| MCP Servers | FastMCP with streamable-http transport |
| Agent | LangChain + langchain-mcp-adapters + OpenAI gpt-4o-mini |
| UI | Gradio ChatInterface |
| Language | Python 3 |
| Deploy | Docker (auto-startup MCP servers + seed data) |

## Troubleshooting

### Check if MCP servers are running

```bash
docker compose exec iris bash -c 'cat /tmp/fhir_server.log'
docker compose exec iris bash -c 'cat /tmp/triage_server.log'
docker compose exec iris bash -c 'cat /tmp/cr_server.log'
```

### Restart MCP servers manually

```bash
docker compose exec iris bash -c 'pkill -f fhir_server.py; pkill -f triage_server.py; pkill -f clinical_reasoning_server.py'
docker compose exec iris bash /home/irisowner/irisdev/start_mcp_servers.sh
```

### Reload test data

```bash
docker compose exec iris bash -c 'cd /home/irisowner/irisdev/python/triage && FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py clean && FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py load'
```

### "OPENAI_API_KEY not set" error

Verify that `python/triage/.env` exists and contains a valid `OPENAI_API_KEY`.

### Port 7860 not accessible

1. Check if the container is running: `docker compose ps`
2. Verify the port mapping in `docker-compose.yml` (`7860:7860`)
3. Check the startup log: `docker compose exec iris bash -c 'cat /tmp/mcp_startup.log'`

### Pip installs are lost on container restart

Dependencies are installed in the Dockerfile (`pip3 install ...`). If you manually installed extra packages inside the container, they will be lost on restart. Add new dependencies to both `Dockerfile` and `requirements.txt`, then rebuild.
