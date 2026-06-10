> This project was inspired in the [**suggested task #10 (Conversational FHIR Triage Assistant)**](https://community.intersystems.com/post/intersystems-programming-contest-ai-agents-fhir) for the InterSystems Programming Contest: AI Agents for FHIR:

# TriageAide — FHIR-First Pre-Consultation Triage

TriageAide is an AI agent that retrieves a patient's FHIR clinical history, conducts a personalized pre-consultation triage via **chat**, and writes structured triage results back to the FHIR server — so the physician receives a ready-made clinical summary before the appointment.

> "TriageAide first retrieves patient history from a FHIR server, builds contextual clinical understanding, and performs an adaptive pre-consultation triage that enriches and updates the longitudinal patient record."

TriageAide is an autonomous AI agent that operates **on top of FHIR data** — it queries the patient's clinical history from a FHIR server (InterSystems IRIS for Health), conducts an intelligent contextual pre-consultation triage, and writes new FHIR resources back to the patient record.

This is **not** a generic chatbot that generates FHIR from scratch. It is an interoperable AI agent that reasons over existing clinical data:

1. **FHIR-First** — consults patient history BEFORE interacting with the patient
2. **Contextual Triage** — asks intelligent questions based on real clinical history, not generic checklists
3. **Bidirectional** — reads from AND writes back to the FHIR server
4. **Longitudinal** — understands care continuity (e.g., "last visit 8 months ago — follow-up overdue")
5. **Multilingual** — the agent naturally responds in the language the patient uses

---

## Quick Start

Get TriageAide running in a few steps. **Only Docker and an OpenAI API key are required.**

### 1 — Clone

```bash
git clone https://github.com/jrpereirajr/TriageAide.git
cd TriageAide
```

### 2 — Set your OpenAI API key

```bash
cp python/triage/.env.example python/triage/.env
```

Edit `python/triage/.env` and add your key:

```
OPENAI_API_KEY=sk-...your-key-here...
```

### 3 — Build and start

```bash
docker compose up -d
```

The build takes some minutes on first run (IRIS image). The triage container waits up to 120 seconds for IRIS to initialize, then loads 4 test patients and starts all services automatically.

### 4 — Test it

Open **http://localhost:7860** in your browser and type:

> **Hi, I'm Joao Santos, I've been having trouble breathing at night and my legs are swollen**

The agent will ask you several follow-up questions to assess your symptoms before producing a final triage assessment. After the full conversation, it queries Joao's FHIR record (5 conditions, 4 medications, elevated creatinine), detects a critical warfarin-bleeding interaction, and writes findings back to the FHIR server — all visible in real time on the trace panel.

**Other test patients to try:**

| Patient | Opening message | Final triage result |
|---|---|---|
| **Ana Costa** | *"Hi, I'm Ana Costa, I've had a sore throat for a couple of days and a mild fever"* | Healthy patient, 0 red flags, routine priority |
| **Maria Silva** | *"Start triage for patient Maria Silva"* | Uncontrolled diabetes, elevated cardiovascular risk |
| **Roberto Lima** | *"Triage for patient Roberto Lima"* | COPD, respiratory red flags, severe allergy, urgent priority |

> **Note:** The agent conducts a multi-turn conversation — it asks one question at a time and deepens its assessment before delivering the final result shown in the table. You won't see the final assessment after just one message.

> For optional configuration (LangSmith tracing, Voice UI, log levels), see [Setup — Step by Step](#setup--step-by-step).

Note: the app uses a LLM cache by default, so you will notice a dramatic speed up when you repeat a prompt. Furthermore, the project loads a cache with pre-recorded full conversations for the first two tests — for patients Joao and Ana Costa — so you will see the final result immediately due to the cache hit. For Maria and Roberto, the agent will go through the full multi-turn conversation in real time.

---

## 5-Step Workflow

1. **FHIR Query** — Agent retrieves Patient, Condition, MedicationRequest, Observation, AllergyIntolerance, Encounter
2. **Contextual Triage** — With history in hand, generates intelligent, personalized questions
3. **Interactive Conversation** — Chat loop: agent asks one question at a time, patient responds, agent deepens
4. **Clinical Reasoning** — Cross-references FHIR history + new symptoms → risk assessment, priority suggestion
5. **FHIR Update** — Creates Observation, QuestionnaireResponse, Flag, Task, Encounter back on the server

---

## Architecture

```
FHIR Server (InterSystems IRIS for Health)      ← iris container
|
+-- fhir_server.py (MCP :8000) — 12 FHIR CRUD tools
+-- triage_server.py (MCP :8001) — 6 contextual triage tools
+-- clinical_reasoning_server.py (MCP :8002) — 4 clinical reasoning tools
|
+-- agent.py (LangChain + OpenAI gpt-4o-mini) — core agent
+-- cli.py — interactive CLI interface
+-- app.py (Gradio :7860) — web UI: Chat tab (+ Voice tab when ENABLE_VOICE_UI=true)
|
+-- entrypoint.sh — container entrypoint (waits for FHIR, loads seed, starts all services)
```
---

## Testing the Application

### Chat Interface (Text)

1. Open **http://localhost:7860** in your browser
2. Click the **💬 Chat** tab (active by default)
3. Type one of the example prompts or click an example chip:

```
Start triage for patient Maria Silva
Triage for patient Joao Santos
Patient Ana Costa history
Triage for patient Roberto Lima
```

The agent responds in the language you use — type in Portuguese, it answers in Portuguese; type in English, it answers in English.

4. Watch the **Agent Trace** panel on the right — it shows each of the 5 workflow steps in real time as the agent queries FHIR, asks questions, reasons, and writes back to IRIS.

5. Respond to the agent's questions. After all triage questions are answered, the agent will:
   - Assess clinical risk
   - Suggest care priority (routine / urgent / emergency)
   - Generate a clinical summary for the physician
   - Write back FHIR resources (Encounter, Observation, Flag, Task, QuestionnaireResponse)

**View modes:**
- **Side-by-side** — chat on the left, trace panel on the right
- **Compact** — trace events inline within the chat

### Voice Interface (ElevenLabs) *(Roadmap)*

Voice interaction is implemented in the backend but the UI tab is hidden by default for the MVP. To enable it, set `ENABLE_VOICE_UI=true` in `.env` and restart the container. See [ElevenLabs Voice Integration](#elevenlabs-voice-integration-roadmap) for full setup instructions.

### Running Automated Dialogue Tests

The repository includes dialogue test scripts for each of the 4 test patients:

```bash
# Run inside the triage container
docker compose exec triage bash

cd /app

# Test Maria Silva — diabetes + hypertension scenario
python3 test_dialogue_maria_silva.py

# Test Joao Santos — polypharmacy + high risk scenario
python3 test_dialogue_joao_santos.py

# Test Ana Costa — healthy, routine triage
python3 test_dialogue_ana_costa.py

# Test Roberto Lima — COPD + respiratory red flags
python3 test_dialogue_roberto_lima.py
```

### CLI Interface

For terminal-based interactive testing:

```bash
docker compose exec triage bash -c "cd /app && python3 cli.py"
```

---

## Test Patients

4 patients with distinct clinical scenarios are loaded via `seed_data.py`:

| Patient | Age | Conditions | Expected Scenario |
|---|---|---|---|
| **Maria Silva** | 58, F | DM2 + Hypertension + HbA1c 8.2% | Uncontrolled diabetes, elevated cardiovascular risk |
| **Joao Santos** | 72, M | HF + AFib + DM2 + HTN + CKD stage 3 | Polypharmacy, drug interactions, high risk |
| **Ana Costa** | 28, F | Acute tonsillitis (mild) | No red flags, routine priority |
| **Roberto Lima** | 65, M | COPD + HTN + Osteoarthritis + Depression + SpO2 93% | Respiratory red flags, severe allergy (anaphylaxis), urgent priority |

### Managing Test Data

```bash
# List loaded patients and their FHIR IDs
docker compose exec triage bash -c \
  'cd /app && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py list'

# Reload all test data (clean + load)
docker compose exec triage bash -c \
  'cd /app && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py clean \
   && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py load'
```

> **Note:** Patient IDs change on each reload. Always refer to patients by name when talking to the agent — it uses `search_patients` to resolve the ID automatically.

---

## Running Manually (inside the container)

For debugging individual components:

```bash
docker compose exec triage bash
cd /app
```

Start each service separately:

```bash
# Terminal 1: FHIR MCP Server
FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 fhir_server.py

# Terminal 2: Triage MCP Server
python3 triage_server.py

# Terminal 3: Clinical Reasoning MCP Server
python3 clinical_reasoning_server.py

# Terminal 4: Voice Bridge *(roadmap)*
VOICE_BRIDGE_SECRET=changeme uvicorn voice_bridge:app --host 0.0.0.0 --port 8003

# Terminal 5: Gradio UI
FHIR_BASE_URL=http://iris:52773/fhir/r4 OPENAI_API_KEY=sk-... python3 app.py
```

Or use the convenience script:

```bash
bash start_servers.sh
```
---

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

### triage_server.py (port 8001) — 6 contextual triage tools

| Tool | Description |
|---|---|
| `build_contextual_questions` | Generates contextual questions based on FHIR history |
| `get_next_triage_question` | Returns the next triage question (one at a time) based on history and covered topics |
| `get_all_triage_topics` | Lists all triage topics for a patient context |
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

---

## Observability

### Gradio Trace Panel

The Gradio UI includes a **trace panel** that shows agent step progress in real-time. Each tool call is mapped to one of the 5 workflow steps with visual indicators:

| Step | Icon | Tools |
|---|---|---|
| FHIR Query | 📋 | search_patients, get_patient, get_patient_* |
| Triage Questions | 💬 | get_next_triage_question, parse_symptoms |
| Red Flags Check | 🚩 | check_red_flags |
| Clinical Reasoning | ⚕️ | assess_clinical_risk, suggest_priority |
| FHIR Update | 📝 | create_*, generate_clinical_summary |

### LangSmith Tracing

To enable [LangSmith](https://smith.langchain.com/) tracing for detailed agent inspection:

1. Add `LANGSMITH_API_KEY` to `python/triage/.env`
2. Set `LANGSMITH_TRACING=true` (enabled by default when the key is present)
3. Set `LANGSMITH_PROJECT=triage-aide` (or your preferred project name)

Traces are automatically sent to LangSmith when the key is configured.

### Service Logs

All modules use `logging_config.py` with the `LOG_LEVEL` env var (default: `DEBUG`). Logs go to both stderr (`docker compose logs`) and per-module files in `/tmp/`.

| Log level | What you see |
|---|---|
| `DEBUG` | Full FHIR request/response payloads, LLM prompts/responses, MCP URLs, tool names, cache HIT/MISS |
| `INFO` | Tool calls, agent creation, cache status, resource creation, errors |

```bash
# All services (follow)
docker compose logs -f triage

# DEBUG lines only
docker compose logs -f triage | grep DEBUG

# Individual service logs (inside container)
docker compose exec triage bash -c 'tail -f /tmp/fhir_server.log'
docker compose exec triage bash -c 'tail -f /tmp/triage_server.log'
docker compose exec triage bash -c 'tail -f /tmp/cr_server.log'
docker compose exec triage bash -c 'tail -f /tmp/voice_bridge.log'
docker compose exec triage bash -c 'tail -f /tmp/app.log'
```

Change log level: set `LOG_LEVEL` in `.env` (e.g., `LOG_LEVEL=INFO` for quieter output).

---

## Ports

| Host Port | Container Port | Service |
|---|---|---|
| 7860 | 7860 | Gradio Web UI (Chat tab + Voice tab when ENABLE_VOICE_UI=true) |
| 8000 | 8000 | FHIR MCP Server |
| 8001 | 8001 | Triage MCP Server |
| 8002 | 8002 | Clinical Reasoning MCP Server |
| 8003 | 8003 | Voice Bridge *(roadmap — always runs for testing)* |
| 32783 | 52773 | FHIR API — IRIS for Health (direct access) |

---

## Tech Stack

| Component | Technology |
|---|---|
| FHIR Server | InterSystems IRIS for Health Community Edition |
| MCP Servers | FastMCP with streamable-http transport |
| Agent | LangChain + langchain-mcp-adapters + OpenAI gpt-4o-mini |
| Voice Bridge | FastAPI + uvicorn — OpenAI-compatible endpoint *(roadmap)* |
| Voice I/O | ElevenLabs Conversational AI (STT + TTS + WebSocket) *(roadmap)* |
| Chat UI | Gradio with Chat tab (+ Voice tab via ENABLE_VOICE_UI) and real-time trace panel |
| Observability | LangSmith tracing (optional) |
| Language | Python 3.12 |
| Deploy | Docker Compose (2 services: iris + triage) |

---

## Troubleshooting

### Containers won't start

```bash
# Check status
docker compose ps

# View full startup logs
docker compose logs triage
docker compose logs iris
```

Common causes:
- **IRIS takes too long to start** — IRIS for Health can take 60–120 seconds on first boot. The triage container waits up to 120 seconds. If it times out, run `docker compose restart triage`.
- **Port conflict** — If ports 7860, 8000–8003, or 32783 are in use, stop the conflicting process or change the port mapping in `docker-compose.yml`.

### "OPENAI_API_KEY not set" error

Verify that `python/triage/.env` exists and contains a valid key:
```bash
grep OPENAI_API_KEY python/triage/.env
```

### Check if MCP servers are running

```bash
docker compose exec triage bash -c 'cat /tmp/fhir_server.log'
docker compose exec triage bash -c 'cat /tmp/triage_server.log'
docker compose exec triage bash -c 'cat /tmp/cr_server.log'
```

### Restart MCP servers manually

```bash
docker compose exec triage bash -c \
  'pkill -f fhir_server.py; pkill -f triage_server.py; pkill -f clinical_reasoning_server.py'
docker compose exec triage bash -c 'cd /app && bash start_servers.sh'
```

### Reload test data

```bash
docker compose exec triage bash -c \
  'cd /app \
   && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py clean \
   && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py load'
```

### Port 7860 not accessible

1. `docker compose ps` — confirm `triage-app` is running
2. Check the triage log: `docker compose logs triage`
3. Verify port mapping: `docker inspect triage-app | grep -A5 Ports`

### Voice Bridge not responding *(Roadmap)*

```bash
# Check if it started
docker compose exec triage bash -c 'cat /tmp/voice_bridge.log'

# Test directly
curl http://localhost:8003/health

# Check it's listening
docker compose exec triage bash -c 'ss -tlnp | grep 8003'
```

If the log shows an error, the bridge may have failed to initialize the agent (MCP servers must be running first). Restart with:
```bash
docker compose exec triage bash -c \
  'pkill -f "uvicorn voice_bridge"; cd /app \
   && uvicorn voice_bridge:app --host 0.0.0.0 --port 8003 >> /tmp/voice_bridge.log 2>&1 &'
```

### Dependency changes are lost on container restart

Dependencies are installed in `python/triage/Dockerfile`. If you manually install packages inside the container, they will be lost on restart. Always add new packages to both `requirements.txt` and `Dockerfile`, then rebuild:

```bash
docker compose build --no-cache triage
docker compose up -d triage
```
