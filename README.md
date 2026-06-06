# TriageAide — FHIR-First Pre-Consultation Triage

TriageAide is an AI agent that retrieves a patient's FHIR clinical history, conducts a personalized pre-consultation triage via **chat**, and writes structured triage results back to the FHIR server — so the physician receives a ready-made clinical summary before the appointment.

> "TriageAide first retrieves patient history from a FHIR server, builds contextual clinical understanding, and performs an adaptive pre-consultation triage that enriches and updates the longitudinal patient record."

TriageAide is an autonomous AI agent that operates **on top of FHIR data** — it queries the patient's clinical history from a FHIR server (InterSystems IRIS for Health), conducts an intelligent contextual pre-consultation triage, and writes new FHIR resources back to the patient record.

This is **not** a generic chatbot that generates FHIR from scratch. It is an interoperable AI agent that reasons over existing clinical data:

1. **FHIR-First** — consults patient history BEFORE interacting with the patient
2. **Contextual Triage** — asks intelligent questions based on real clinical history, not generic checklists
3. **Bidirectional** — reads from AND writes back to the FHIR server
4. **Longitudinal** — understands care continuity (e.g., "last visit 8 months ago — follow-up overdue")
5. **Bilingual** — supports Brazilian Portuguese (pt-BR) and English (en-US) in chat

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
+-- agent.py (LangChain + OpenAI gpt-4o-mini) — core agent, bilingual system prompt
+-- voice_bridge.py (FastAPI :8003) — OpenAI-compatible endpoint for ElevenLabs *(roadmap)*
+-- voice_session.py — per-session state and language detection *(roadmap)*
+-- cli.py — interactive CLI interface
+-- app.py (Gradio :7860) — web UI: Chat tab (+ Voice tab when ENABLE_VOICE_UI=true)
|
+-- entrypoint.sh — container entrypoint (waits for FHIR, loads seed, starts all services)
```

### Voice Architecture *(Roadmap — next step)*

Voice interaction via ElevenLabs Conversational AI is implemented in the backend (`voice_bridge.py` on port 8003) but the UI tab is hidden by default in the MVP. To enable it, set `ENABLE_VOICE_UI=true` in `.env`. See [ElevenLabs Voice Integration](#elevenlabs-voice-integration-roadmap) for full setup instructions.
[Patient browser / phone]
        |
        | WebSocket (ElevenLabs Conversational AI)
        v
[ElevenLabs Cloud]
  - STT: speech-to-text (pt-BR / en-US, auto-detect)
  - TTS: voice synthesis (Brazilian Portuguese voice)
        |
        | POST /v1/chat/completions  (OpenAI-compatible, Bearer auth)
        v
[voice_bridge.py — FastAPI :8003]
  - Session management per conversation
  - Language detection (heuristic + ElevenLabs header)
  - Markdown stripping for clean TTS output
  - SSE streaming
        |
        v
[agent.py — LangChain + gpt-4o-mini]  (bilingual: auto-detect mode)
        |
   ┌────┴───────────────┬─────────────────────┐
   v                    v                     v
fhir_server.py      triage_server.py    clinical_reasoning_server.py
(MCP :8000)         (MCP :8001)         (MCP :8002)
        |
        v
[InterSystems IRIS for Health — http://iris:52773/fhir/r4]
```

Two independent Docker services share a `fhir-net` bridge network:
- **iris** — IRIS for Health FHIR server
- **triage** — Python app (MCP servers + Voice Bridge *(roadmap)* + Gradio UI)

---

## Prerequisites

| Requirement | Details |
|---|---|
| [Docker](https://www.docker.com/products/docker-desktop) + Docker Compose | v2.20+ recommended |
| OpenAI API key | Used by gpt-4o-mini for clinical reasoning |
| (Optional) LangSmith API key | Agent tracing and debugging |
| (Roadmap) ElevenLabs API key | Required only for voice interface — not needed for MVP |
| (Roadmap) [ngrok](https://ngrok.com/) | Expose local voice bridge to ElevenLabs — not needed for MVP |

---

## Setup — Step by Step

### Step 1 — Clone the repository

```bash
git clone https://github.com/musketeers-br/TriageAide.git
cd TriageAide
```

### Step 2 — Configure environment variables

```bash
cd python/triage
cp .env.example .env
```

Open `.env` and fill in the required values:

```bash
# Required
OPENAI_API_KEY=sk-...your-openai-key-here...

# Optional — LangSmith tracing
LANGSMITH_API_KEY=ls-...your-langsmith-key...
LANGSMITH_PROJECT=triage-aide
LANGSMITH_TRACING=true

# Voice UI — show/hide the Voice tab (voice bridge runs regardless for testing)
ENABLE_VOICE_UI=false

# Roadmap — ElevenLabs voice interface (see "ElevenLabs Voice Integration" section)
# VOICE_BRIDGE_SECRET=your-strong-random-secret # generate: openssl rand -hex 32
# ELEVENLABS_AGENT_ID= # fill after creating the agent
# ELEVENLABS_WIDGET_ID= # fill after creating the agent
# VOICE_BRIDGE_URL=https://your-ngrok-url # fill after starting ngrok
```

> **Note:** `FHIR_BASE_URL`, `FHIR_USER`, and `FHIR_PASS` have correct defaults in `.env.example` and do not need to be changed for local development.

Go back to the root directory:

```bash
cd ../..
```

### Step 3 — Build the Docker images

```bash
docker compose build --no-cache --progress=plain
```

Expected output: two images built — `fhir-template` (IRIS) and `triage-app` (Python). The build may take **3–8 minutes** on first run due to IRIS image size.

### Step 4 — Start the services

```bash
docker compose up -d
```

This starts both services in the background. The `triage` container will:
1. Wait for IRIS to be ready (up to 120 seconds)
2. Load the 4 test patients via `seed_data.py` (first boot only)
3. Start FHIR MCP Server on port 8000
4. Start Triage MCP Server on port 8001
5. Start Clinical Reasoning MCP Server on port 8002
6. Start Voice Bridge on port 8003 *(roadmap — always runs, for testing)*
7. Start Gradio UI on port 7860

### Step 5 — Verify services are running

**Check container status:**
```bash
docker compose ps
```

Expected output: both `fhir-template` and `triage-app` with status `Up`.

**Check all services are healthy:**
```bash
# Gradio UI
curl -s -o /dev/null -w "%{http_code}" http://localhost:7860
# Expected: 200

# FHIR MCP Server
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/mcp
# Expected: 405 or 406 (server responds to GET, expects POST/SSE)

# IRIS FHIR API (direct)
curl -s -o /dev/null -w "%{http_code}" \
-u _SYSTEM:SYS \
-H "Accept: application/fhir+json" \
http://localhost:32783/fhir/r4/metadata
# Expected: 200

# Voice Bridge (roadmap — always runs for testing)
curl -s http://localhost:8003/health
# Expected: {"status":"ok","service":"triageaide-voice-bridge"}
```

**Follow startup logs:**
```bash
docker compose logs -f triage
```

Look for these lines indicating all services are up:
```
 Port 8000 ready
 Port 8001 ready
 Port 8001 ready
Port 8002 ready
Starting Voice Bridge on port 8003... *(roadmap)*
Starting Gradio UI on port 7860...
Running on local URL: http://0.0.0.0:7860
```

---

## Testing the Application

### Chat Interface (Text)

1. Open **http://localhost:7860** in your browser
2. Click the **💬 Chat** tab (active by default)
3. Type one of the example prompts or click an example chip:

**English:**
```
Start triage for patient Maria Silva
Triage for patient Joao Santos
Patient Ana Costa history
Triage for patient Roberto Lima
```

**Português:**
```
Iniciar triagem para Maria Silva
Triagem para paciente João Santos
Histórico do paciente Ana Costa
Triagem para Roberto Lima
```

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
| **Ana Costa** | 28, F | No active conditions | Generic questions, no red flags, routine priority |
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

## ElevenLabs Voice Integration *(Roadmap — next step)*

> **Status:** Backend implemented, UI hidden by default in the MVP. Enable with `ENABLE_VOICE_UI=true` in `.env`. For the full design specification, see [`doc/elevenlabs-integration.md`](doc/elevenlabs-integration.md).

The voice interface uses ElevenLabs Conversational AI with a **Custom LLM** configuration. ElevenLabs handles all audio (STT + TTS), and the `voice_bridge.py` service provides the clinical intelligence by wrapping the existing LangChain agent.

### How it Works

```
Patient speaks → ElevenLabs STT → POST /v1/chat/completions → voice_bridge.py
→ LangChain agent → MCP servers → IRIS → response text
→ voice_bridge.py strips markdown → SSE to ElevenLabs → TTS → patient hears response
```

### Quick Test (no ElevenLabs account needed)

The Voice Bridge runs on port 8003 regardless of `ENABLE_VOICE_UI`. Replace `<VOICE_BRIDGE_SECRET>` with the value from your `.env`:

```bash
# Streaming response (same format ElevenLabs uses)
curl -X POST http://localhost:8003/v1/chat/completions \
-H "Content-Type: application/json" \
-H "Authorization: Bearer <VOICE_BRIDGE_SECRET>" \
-d '{"messages":[{"role":"user","content":"Iniciar triagem para Maria Silva"}],"stream":true}'

# Non-streaming (full JSON response)
curl -X POST http://localhost:8003/v1/chat/completions \
-H "Content-Type: application/json" \
-H "Authorization: Bearer <VOICE_BRIDGE_SECRET>" \
-d '{"messages":[{"role":"user","content":"Iniciar triagem para Maria Silva"}],"stream":false}'
```

### Full Setup Instructions

<details>
<summary>Click to expand full ElevenLabs setup guide</summary>

#### Step 1 — Generate a voice bridge secret

```bash
openssl rand -hex 32
```

Add this to `python/triage/.env`:
```bash
VOICE_BRIDGE_SECRET=a3f7c2d1e8b4a9f6...
```

> **Important:** `VOICE_BRIDGE_SECRET` must be set **only** in `python/triage/.env`. Do NOT set it in the `docker-compose.yml` `environment:` section — that overrides the `.env` file value and causes 401 errors.

#### Step 2 — Expose the voice bridge publicly (local development)

ElevenLabs needs to reach your voice bridge over HTTPS. The project includes a `start_tunnel.sh` script at the repo root that creates a stable tunnel with a fixed subdomain.

**Using `start_tunnel.sh` (localtunnel with fixed subdomain):**

```bash
./start_tunnel.sh
```

**Alternative: ngrok**

```bash
ngrok http 8003
```

**After starting the tunnel:**

1. Update your `.env`: `VOICE_BRIDGE_URL=https://dark-ways-itch.loca.lt` (or your ngrok URL)
2. In the ElevenLabs dashboard, set the Custom LLM base URL to `https://dark-ways-itch.loca.lt/v1`
3. Verify the tunnel: `curl https://<tunnel-url>/health`

#### Step 3 — Create the ElevenLabs agent

1. Go to [elevenlabs.io/conversational-ai](https://elevenlabs.io/conversational-ai) and log in
2. Click **Create Agent**
3. Select **Custom LLM** as the model type
4. Configure the agent:

| Field | Value |
|---|---|
| **LLM URL** | `https://<your-ngrok-or-public-url>/v1/chat/completions` |
| **Authentication** | Bearer token → paste your `VOICE_BRIDGE_SECRET` |
| **System Prompt** | *(leave blank — the bridge sends the full prompt)* |
| **First Message** | `Olá! Sou o assistente de triagem do TriageAide. Por favor, me diga seu nome para começarmos.` |
| **Voice** | Choose a Brazilian Portuguese voice |
| **Language** | Enable auto-detection; add Portuguese (Brazil) and English (US) |

5. Click **Save** and note the **Agent ID**

> **Tip:** You can also import the pre-configured agent from `11labs/myagent.json`.

#### Step 4 — Configure the Agent ID in .env

```bash
ELEVENLABS_AGENT_ID=agent_xxxxxxxxxx
ELEVENLABS_WIDGET_ID=agent_xxxxxxxxxx
ENABLE_VOICE_UI=true
```

Restart: `docker compose restart triage`

#### Step 5 — Test the voice integration

1. Open the 🎙️ Voice tab in Gradio
2. Say: *"Olá, quero fazer triagem para Maria Silva"*
3. The agent should respond in Portuguese and begin asking triage questions

**Language switching test:**
- Start with *"Hi, triage for Roberto Lima"* → agent responds in English
- Start with *"Olá, triagem para João Santos"* → agent responds in Portuguese

### Bilingual Support

The agent automatically detects language from the patient's speech:
- **Portuguese detected** → all responses in pt-BR
- **English detected** → all responses in en-US
- Language is **sticky per session**

### ElevenLabs Agent Configuration Reference

The `11labs/myagent.json` file is an exported configuration of the ElevenLabs Conversational AI agent.

**Key fields:**

| Field | Value | Description |
|---|---|---|
| `agent_id` | `agent_7001kt5n1cv6fj687wvbaxy81r0y` | Matches `ELEVENLABS_AGENT_ID` in `.env` |
| `agent.first_message` | `"Olá! Como posso ajudar?"` | Initial greeting |
| `prompt.llm` | `"custom-llm"` | Tells ElevenLabs to call the Voice Bridge |
| `custom_llm.url` | `"https://dark-ways-itch.loca.lt/v1"` | Base URL — ElevenLabs appends `/chat/completions` |
| `tts.model_id` | `"eleven_flash_v2_5"` | TTS model — low latency |
| `turn.turn_timeout` | `7` | Seconds of silence before agent responds |

**Custom LLM URL format:**

| `custom_llm.url` (base) | Actual endpoint called by ElevenLabs |
|---|---|
| `https://dark-ways-itch.loca.lt/v1` | `https://dark-ways-itch.loca.lt/v1/chat/completions` |
| `https://abc123.ngrok-free.app/v1` | `https://abc123.ngrok-free.app/v1/chat/completions` |

> **Important:** When changing the tunnel URL, update `custom_llm.url` in the ElevenLabs dashboard **and** `VOICE_BRIDGE_URL` in `.env`.

</details>

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

## File Structure

```
TriageAide/
├── docker-compose.yml              # Two services: iris + triage
├── Dockerfile                      # IRIS for Health image
├── README.md
└── python/triage/
    ├── .env                        # Credentials (NOT tracked in git)
    ├── .env.example                # Template — copy to .env and fill
    ├── requirements.txt            # Python dependencies
    ├── Dockerfile                  # Python 3.12-slim image for triage service
    ├── entrypoint.sh               # Container boot: wait FHIR → seed → start all
├── start_servers.sh # Manual start script (MCP + Voice Bridge + Gradio)
│
├── agent.py # Core agent: get_system_prompt(), create_triage_agent()
├── voice_bridge.py # FastAPI Voice Bridge (port 8003) *(roadmap)*
├── voice_session.py # Per-session state, language detection, TTL eviction *(roadmap)*
    │
    ├── fhir_server.py              # MCP Server 1 — FHIR CRUD (port 8000)
    ├── triage_server.py            # MCP Server 2 — Contextual triage (port 8001)
    ├── clinical_reasoning_server.py # MCP Server 3 — Clinical reasoning (port 8002)
    │
├── app.py # Gradio web UI: Chat tab (+ Voice tab when ENABLE_VOICE_UI=true)
    ├── cli.py                      # Interactive CLI interface
    │
    ├── seed_data.py                # Load / clean / list test patients
    ├── seed_data/                  # FHIR Bundle JSON files
    │   ├── patient_maria_silva.json
    │   ├── patient_joao_santos.json
    │   ├── patient_ana_costa.json
    │   └── patient_roberto_lima.json
    │
    ├── test_dialogue_maria_silva.py
    ├── test_dialogue_joao_santos.py
    ├── test_dialogue_ana_costa.py
    └── test_dialogue_roberto_lima.py
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

```bash
# All services (follow)
docker compose logs -f triage

# Individual service logs (inside container)
docker compose exec triage bash -c 'tail -f /tmp/fhir_server.log'
docker compose exec triage bash -c 'tail -f /tmp/triage_server.log'
docker compose exec triage bash -c 'tail -f /tmp/cr_server.log'
docker compose exec triage bash -c 'tail -f /tmp/voice_bridge.log'
```

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

### ElevenLabs gets 401 Unauthorized *(Roadmap)*

The `VOICE_BRIDGE_SECRET` in your `.env` must match exactly what you configured as the Bearer token in the ElevenLabs agent settings. Re-check both values:

```bash
grep VOICE_BRIDGE_SECRET python/triage/.env
```

Also verify the value the container is actually using — if it shows `changeme` or a different value, the `docker-compose.yml` `environment:` section may be overriding `.env`:

```bash
docker compose exec triage bash -c 'echo $VOICE_BRIDGE_SECRET | wc -c'
# Should match the length of your secret (64 chars + newline for a hex-32 secret)
```

The `.env` file must be the **only** source of `VOICE_BRIDGE_SECRET`. Do not duplicate it in the `docker-compose.yml` `environment:` section, because `environment:` takes precedence over `env_file:` and silently overrides the value.

### ElevenLabs can't reach the voice bridge *(Roadmap)*

- Make sure the tunnel is running: `./start_tunnel.sh` (or `ngrok http 8003`)
- If using `start_tunnel.sh`, verify the fixed URL: `curl https://dark-ways-itch.loca.lt/health`
- The ngrok URL changes every restart (free plan). Update `VOICE_BRIDGE_URL` in `.env` and in the ElevenLabs agent configuration.
- For persistent URLs, use [ngrok's static domains](https://ngrok.com/blog-post/free-static-domains-ngrok-users) (free tier: 1 static domain).

### Agent responds in the wrong language *(Roadmap — voice only)*

Language detection is heuristic-based. If the agent responds in the wrong language, check `voice_bridge.log` for the detected language. You can override by adding an explicit instruction in your first message: *"Please respond in English"* or *"Por favor, responda em português"*.

### Dependency changes are lost on container restart

Dependencies are installed in `python/triage/Dockerfile`. If you manually install packages inside the container, they will be lost on restart. Always add new packages to both `requirements.txt` and `Dockerfile`, then rebuild:

```bash
docker compose build --no-cache triage
docker compose up -d triage
```
