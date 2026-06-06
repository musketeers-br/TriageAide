# Plan: Pre-Consultation Triage Agent — FHIR-First Agentic AI

## Objective

Build a Python application that implements the scenario described in `doc/scenario1.md` — a **Pre-Consultation Triage Agent** that first queries the FHIR Server (InterSystems IRIS for Health), understands the patient's history, and then conducts personalized intelligent triage, updating the FHIR record back.

## Architecture

```
FHIR Server (IRIS for Health :32783)         ← iris container
|
fhir_server.py (MCP :8000) — 12 FHIR CRUD tools
|
triage_server.py (MCP :8001) — 5 contextual triage tools
|
clinical_reasoning_server.py (MCP :8002) — 4 clinical reasoning tools
|
agent.py (LangChain + OpenAI gpt-4o-mini) — agent core (factory, system prompt)
|
cli.py — interactive CLI interface (imports from agent.py)
app.py (Gradio) — web chat UI with trace panel (:7860)
|
entrypoint.sh — container entrypoint (waits for FHIR, loads seed, starts MCP + Gradio)
```

Two independent Docker services on a shared `fhir-net` bridge network:
- **iris** — IRIS for Health FHIR server
- **triage** — Python app (MCP servers + agent + Gradio UI)

## Agent Flow (5 steps from scenario1.md)

1. **FHIR Query** — Agent queries Patient, Condition, MedicationRequest, Observation, AllergyIntolerance, Encounter
2. **Contextual Triage** — With history in hand, generates intelligent questions (not generic)
3. **Interactive Conversation** — Chat loop where the patient answers, agent deepens
4. **Clinical Reasoning** — Crosses FHIR history + new symptoms → assesses risk, suggests priority
5. **FHIR Update** — Creates Observation, QuestionnaireResponse, Flag, Task, Encounter back on the server

## Test Data (4 FHIR patients)

### Patient 1: Maria Silva (main scenario)
- Female, 58 years | Type 2 Diabetes + Hypertension | HbA1c 8.2% | Metformin + Losartan
- Penicillin Allergy | Last consultation 8 months ago
- **Expected:** agent identifies uncontrolled diabetes, asks contextual questions, elevated cardiovascular risk

### Patient 2: Joao Santos (complex cardiovascular)
- Male, 72 years | HF + AF + DM2 + HTN + CKD stage 3
- Warfarin + Metformin + Enalapril + Furosemide | ASA Allergy
- **Expected:** polypharmacy, drug interactions, high risk

### Patient 3: Ana Costa (young, low risk)
- Female, 28 years | No active conditions | No medications
- **Expected:** generic questions, no red flags, routine priority

### Patient 4: Roberto Lima (multiple conditions + warning signs)
- Male, 65 years | COPD + HTN + Osteoarthritis + Depression
- SpO2 93% | Dipyrone allergy (anaphylaxis)
- **Expected:** respiratory red flags + severe allergy, urgent/emergency priority

## File Structure

```
python/triage/
.env # FHIR_BASE_URL, OPENAI_API_KEY, LANGSMITH_*, LOG_LEVEL — NOT tracked in git
.env.example # Template without credentials (LOG_LEVEL defaults to DEBUG)
requirements.txt            # Python dependencies
Dockerfile                  # Python 3.12-slim image for the triage service
entrypoint.sh               # Container entrypoint (waits for FHIR, loads seed, starts MCP + Gradio)
seed_data.py                # Script to load/clean/list test patients
seed_data/                  # FHIR JSON bundles for loading
    patient_maria_silva.json
    patient_joao_santos.json
    patient_ana_costa.json
    patient_roberto_lima.json
fhir_server.py # MCP Server 1 — FHIR CRUD (port 8000)
triage_server.py # MCP Server 2 — contextual triage (port 8001)
clinical_reasoning_server.py # MCP Server 3 — clinical reasoning (port 8002)
logging_config.py # Centralized logging config (LOG_LEVEL env var, stderr + file handlers)
agent.py # Agent core (SYSTEM_PROMPT, create_triage_agent, extract_ai_response)
cli.py                      # Interactive CLI interface
app.py # Gradio chat UI with trace panel — Web (:7860)
voice_bridge.py # Voice Bridge — OpenAI-compatible API for ElevenLabs (port 8003) *(roadmap)*
voice_session.py # Voice session store (language detection, auto-eviction) *(roadmap)*
start_servers.sh # Script to start the 3 MCP servers + Gradio (manual)
PLAN.md                     # This file — architecture plan
PROGRESS.md                 # Progress history, discoveries and decisions
README.md                   # Usage instructions
```

## MCP Servers — Tools

### fhir_server.py (port 8000) — 12 tools

| Tool | FHIR Method | Description |
|---|---|---|
| `search_patients(name)` | GET /Patient?name={name} | Search patients by name (partial) |
| `get_patient(patient_id)` | GET /Patient/{id} | Demographics |
| `get_patient_conditions(patient_id)` | GET /Condition?patient={id} | Conditions |
| `get_patient_medications(patient_id)` | GET /MedicationRequest?patient={id} | Medications |
| `get_patient_observations(patient_id, code, _count)` | GET /Observation?patient={id} | Observations |
| `get_patient_allergies(patient_id)` | GET /AllergyIntolerance?patient={id} | Allergies |
| `get_patient_encounters(patient_id, _count)` | GET /Encounter?patient={id} | Encounters |
| `create_observation(patient_id, code, display, value, unit, effective_date)` | POST /Observation | New observation |
| `create_condition(patient_id, code, display, clinical_status)` | POST /Condition | New condition |
| `create_questionnaire_response(patient_id, questions_responses)` | POST /QuestionnaireResponse | Structured triage |
| `create_encounter(patient_id, reason, priority)` | POST /Encounter | Pre-consultation encounter |
| `create_flag_and_task(patient_id, flag_detail, task_detail, priority)` | POST /Flag + POST /Task | Alert + follow-up |

### triage_server.py (port 8001) — 5 tools

| Tool | Description |
|---|---|
| `build_contextual_questions(patient_context)` | Generates contextual questions based on FHIR history |
| `get_next_triage_question(patient_context, covered_topics)` | Returns the next triage question (one at a time) |
| `get_all_triage_topics(patient_context)` | Lists all triage topics for a patient context |
| `parse_symptoms(patient_response)` | Extracts symptoms, duration, severity |
| `check_red_flags(symptoms, conditions)` | Checks warning signs |
| `build_questionnaire_response_data(patient_id, questions, answers)` | Builds QuestionnaireResponse FHIR |

### clinical_reasoning_server.py (port 8002) — 4 tools

| Tool | Description |
|---|---|
| `assess_clinical_risk(conditions, new_symptoms, observations, medications)` | Risk score with justification |
| `suggest_priority(risk_assessment)` | Care priority |
| `generate_clinical_summary(patient_data, triage_data, risk_data)` | Summary for the physician |
| `identify_follow_up_tasks(risk, conditions, gaps_in_care)` | Follow-up tasks |

## Techniques

- **FHIR Client**: requests with Basic Auth (_SYSTEM:SYS) against http://localhost:32783/fhir/r4 (host) or http://iris:52773/fhir/r4 (triage container)
- **LLM**: OpenAI gpt-4o-mini via langchain-openai
- **MCP**: fastmcp with transport="streamable-http"
- **Agent**: langchain-mcp-adapters + MultiServerMCPClient + load_mcp_tools + create_agent (with `system_prompt`)
- **UI**: Gradio gr.ChatInterface (6.x, without `type="messages"`) with trace panel
- **Observability**: LangSmith tracing (optional, enabled when LANGSMITH_API_KEY is set) + structured logging (LOG_LEVEL env var, default DEBUG)
- **Deploy**: Docker Compose with 2 services (iris + triage) on fhir-net bridge network

## Discoveries & Challenges

> Full details in [PROGRESS.md](./PROGRESS.md#technical-discoveries-lessons-learned)

| # | Discovery | Impact | Solution |
|---|---|---|---|
| 1 | IRIS FHIR POST returns empty body (HTTP 201) | `resp.json()` fails with JSONDecodeError | Extract ID from `Location` header via regex |
| 2 | `urn:uuid:` references don't resolve with individual POSTs | Bundles with cross-resource references fail | Create Patient first, resolve refs to `Patient/{id}`, then create dependents |
| 3 | `load_dotenv()` does not override existing env vars | `FHIR_BASE_URL` wrong when running via script | Scripts export the correct URL (port 52773) before running |
| 4 | Pip installs in running container are lost on restart | Dependencies disappear | Add to Dockerfile + requirements.txt |
| 5 | Gradio 6.x removed `type="messages"` | ChatInterface fails with obsolete parameter | Remove parameter, use `list[dict]` format with `role`/`content` |
| 6 | `create_agent()` supports `system_prompt` | Manual SystemMessage is fragile | Use framework's native parameter |
| 7 | MCP sessions via `async with` close after context manager | Agent loses access to MCP tools | Use `_client.get_tools()` (per-call session) instead of `load_mcp_tools(session)` |
| 8 | IRIS FHIR `name` param does not support full name | `?name=Maria Silva` returns 0 | `search_patients` tries family, given, and partial name |
| 9 | Container-internal vs host URLs for FHIR | Wrong URL used from triage container | Use `http://iris:52773/fhir/r4` inside Docker, `http://localhost:32783/fhir/r4` on host |

## Status

### Completed

- [x] 3 MCP servers implemented and running
- [x] Agent core (`agent.py`), CLI (`cli.py`) and Web UI (`app.py`) functional
- [x] 4 test patients with complete FHIR bundles
- [x] Seed data with load/clean/list + `triage-seed` tag
- [x] Complete Docker infrastructure (2 services: iris + triage, auto-startup MCP + seed data)
- [x] End-to-end test with Maria Silva
- [x] Patient search by name (`search_patients`)
- [x] Test Gradio UI externally (host port 7860)
- [x] Test with all 4 patients (Joao, Ana, Roberto)
- [x] LangSmith observability (optional)
- [x] Gradio trace panel for real-time agent step progress
- [x] Translation to English (code + docs)
- [x] Structured logging of all modules (logging_config.py, LOG_LEVEL env var)

### Pending

- [ ] Adjust prompt for consistent creation of Flag/Task/QuestionnaireResponse
- [ ] Container restart test

### Future Work

- [x] Voice interaction — backend implemented, UI tab hidden in MVP (enable via `ENABLE_VOICE_UI=true`)
- [ ] Voice UI polish — stabilize ElevenLabs widget integration for production use
- [ ] Automated tests
- [ ] Contest submission preparation
- [ ] Health check endpoints on MCP servers

## Validation

### Via Docker (recommended)

```bash
# Build and start
docker compose build --no-cache --progress=plain
docker compose up -d

# Check MCP servers (triage container)
docker compose exec triage bash -c 'cat /tmp/fhir_server.log'
docker compose exec triage bash -c 'cat /tmp/triage_server.log'
docker compose exec triage bash -c 'cat /tmp/cr_server.log'

# Live logs (all modules, DEBUG level)
docker compose logs triage -f

# Check seed data
docker compose exec triage bash -c 'cd /app && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py list'

# Access Gradio UI
# http://localhost:7860

# Access FHIR API (verify patients)
# http://localhost:32783/fhir/r4/Patient
```

### Manual (inside triage container)

```bash
docker compose exec triage bash
cd /app

# 1. Load patients
FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py load

# 2. Start MCP servers + Gradio
bash start_servers.sh

# 3. Test each patient and validate expected behavior
```

### Test Scenarios by Patient

| Patient | Action | Expected Result |
|---|---|---|
| Maria Silva | Provide name, answer questions about diabetes | Moderate/high cardiovascular risk, Flag + Task created |
| Joao Santos | Provide name, report bleeding | Red flag due to warfarin, high risk, urgent priority |
| Ana Costa | Provide name, report mild symptoms | Low risk, routine priority, generic questions |
| Roberto Lima | Provide name, report shortness of breath | Respiratory red flag (COPD + SpO2 93%), urgent/emergency priority |
