# Pre-Consultation Triage Agent — FHIR-First Agentic AI

Autonomous clinical triage agent that operates ON FHIR data. First queries the patient's history on InterSystems IRIS for Health, then conducts personalized intelligent triage, and finally updates the FHIR medical record with resources created during the consultation.

## Architecture

```
FHIR Server (IRIS for Health :52773/:32783)   ← iris container
|
fhir_server.py (MCP :8000) — 12 FHIR CRUD tools
|
triage_server.py (MCP :8001) — 5 contextual triage tools
|
clinical_reasoning_server.py (MCP :8002) — 4 clinical reasoning tools
|
agent.py (LangChain + OpenAI gpt-4o-mini) — agent core (factory, system prompt)
cli.py — interactive CLI interface (imports from agent.py)
app.py (Gradio :7860) — web chat UI with trace panel
|
entrypoint.sh — container entrypoint (waits for FHIR, loads seed, starts MCP + Gradio)
```

Three Docker services on a shared `fhir-net` bridge network:
- **iris** — IRIS for Health FHIR server
- **triage** — Python app (MCP servers + agent + Gradio UI)
- **ollama** — Local LLM server (gemma3:1b) for patient simulation in automated tests

## Agent Flow (5 mandatory steps)

1. **FHIR Query** — Query Patient, Condition, MedicationRequest, Observation, AllergyIntolerance, Encounter
2. **Contextual Triage** — With history in hand, generates intelligent questions (not generic)
3. **Interactive Conversation** — Chat loop where the patient responds, agent digs deeper
4. **Clinical Reasoning** — Cross-references FHIR history + new symptoms → assesses risk, suggests priority
5. **FHIR Update** — Creates Observation, QuestionnaireResponse, Flag, Task, Encounter back on the server

## Prerequisites

- Docker + Docker Compose
- OpenAI API Key (gpt-4o-mini model)
- (Optional) LangSmith API key for agent tracing
- (Optional, for automated patient simulation) Ollama container with gemma3:1b

## How to Run via Docker

1. Copy `.env.example` to `.env` and fill in your `OPENAI_API_KEY`:

```bash
cd python/triage
cp .env.example .env
# edit .env and add your real key
# optionally set LANGSMITH_API_KEY for tracing
```

2. Build and start the containers:

```bash
docker compose build --no-cache --progress=plain
docker compose up -d
```

3. Access the Gradio UI: **http://localhost:7860**

MCP servers start automatically with the triage container via `entrypoint.sh`. Test data (4 patients) is loaded automatically the first time the container starts.

## How to Run Manually (inside the container)

If you need to run the servers manually for debugging:

```bash
# Enter the triage container
docker compose exec triage bash

# Go to the app directory
cd /app

# Start the 3 MCP servers + Gradio
bash start_servers.sh
```

Or run each component separately:

```bash
# Terminal 1: FHIR MCP Server
FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 fhir_server.py

# Terminal 2: Triage MCP Server
python3 triage_server.py

# Terminal 3: Clinical Reasoning MCP Server
python3 clinical_reasoning_server.py

# Terminal 4: Gradio UI (or cli.py for CLI)
FHIR_BASE_URL=http://iris:52773/fhir/r4 OPENAI_API_KEY=sk-... python3 app.py
```

## Ports

| Port (host) | Port (container) | Service |
|---|---|---|
| 32782 | 1972 | IRIS SuperServer |
| 32783 | 52773 | IRIS Web/REST (FHIR API) |
| 32784 | 53773 | IRIS additional |
| 8000 | 8000 | FHIR MCP Server |
| 8001 | 8001 | Triage MCP Server |
| 8002 | 8002 | Clinical Reasoning MCP Server |
| 7860 | 7860 | Gradio Web UI |
| 8003 | 8003 | Voice Bridge *(roadmap — always runs for testing)* |
| 11434 | 11434 | Ollama LLM server (patient simulation) |

## Test Patients

The `seed_data.py` script loads 4 FHIR patients with distinct clinical scenarios:

| Patient | Age, Sex | Conditions | Expected Scenario |
|---|---|---|---|
| **Maria Silva** | 58, F | DM2 + Hypertension | Uncontrolled diabetes, elevated cardiovascular risk |
| **Joao Santos** | 72, M | HF + AF + DM2 + Hypertension + CKD | Polypharmacy, drug interactions, high risk |
| **Ana Costa** | 28, F | No active conditions | Generic questions, no red flags, routine priority |
| **Roberto Lima** | 65, M | COPD + Hypertension + Osteoarthritis + Depression | Respiratory red flags, severe allergy, urgent priority |

To reload test data (inside the triage container):

```bash
FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py clean
FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py load
```

To list loaded patients:

```bash
FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py list
```

**Note:** Patient IDs change on each reload. Use the patient's name when talking to the agent.

## Vector Search RAG (Clinical Reasoning)

The Clinical Reasoning server can ground its risk/priority decision in similar past triage cases retrieved from InterSystems IRIS via native vector search (`VECTOR_COSINE` over a `%Vector` column). The knowledge base is the synthetic, ESI-labeled emergency-department dataset [olaflaitinen/fedmml-ed-triage](https://huggingface.co/datasets/olaflaitinen/fedmml-ed-triage).

How it works:

1. `ingest_knowledge.py` downloads the dataset, builds one canonical text document per case (`Patient / Chief complaint / Vitals / Notes`), embeds documents in batches, and upserts them into `TriageAide.TriageKnowledge` (idempotent, keyed by dataset row id).
2. At assessment time, `clinical_assessment` builds a query document for the current patient **using the same template and the same embedding model**, retrieves the top-K cases above a cosine-similarity threshold, and injects them into the prompt as `Reference triage cases`.
3. The system prompt instructs the LLM that ESI is an inverted 1–5 scale (1 = most critical; ESI 1–2 ≈ emergency, 3 ≈ urgent, 4–5 ≈ routine), that the cases are synthetic reference signal (not ground truth), and to cite the cases that influenced the decision. Retrieved cases are attached to the tool output (`reference_cases`) for traceability in the Gradio trace panel and LangSmith.

If IRIS is unreachable, the table is missing, or the embedding provider fails, retrieval silently degrades and the assessment runs exactly as before (no RAG).

### Ingesting the knowledge base

```bash
# inside the triage container
docker compose exec triage python3 ingest_knowledge.py --inspect      # check dataset schema/mapping first
docker compose exec triage python3 ingest_knowledge.py --limit 1000   # ingest a sample
docker compose exec triage python3 ingest_knowledge.py --limit 0      # ingest everything
```

Use `--recreate` to drop and rebuild the table — required when switching to an embedding model with a different dimension (the bundled class `src/TriageAide/TriageKnowledge.cls` defaults to 1536 = OpenAI `text-embedding-3-small`; Ollama `nomic-embed-text` is 768).

### Configuration

See the `Vector Search RAG` block in `.env.example`. Key points:

- `EMBEDDINGS_PROVIDER=openai|ollama` — the **same model must be used for ingestion and querying**; the model id is stored with each row and validated at query time (mismatch disables RAG with a warning).
- `RAG_MIN_SIMILARITY` — cases below the threshold are discarded; an empty RAG section is better than irrelevant cases anchoring the LLM.
- `RAG_ENABLED=false` — disables retrieval entirely, which makes A/B comparison trivial: run `test_priority.py` once with RAG on and once with it off and compare priorities/justifications.
- Language note: the dataset is in English while triage conversations may be in Portuguese. OpenAI `text-embedding-3-*` handles cross-lingual similarity reasonably; if you use a monolingual local model, expect lower recall.

## Patient Simulator (Ollama)

The `patient_sim.py` module uses a local LLM (Ollama with `gemma3:1b`) to role-play as each test patient, enabling fully automated triage conversations. Each patient has a detailed persona with medical history, current symptoms, personality traits, and behavioral rules.

### Start the Ollama Container

```bash
docker compose up -d ollama
```

The container automatically pulls the `gemma3:1b` model on first startup. Model data is persisted in the `ollama-data` named volume.

### Patient Simulator CLI

```bash
# List available patient personas
docker compose exec triage bash -c 'cd /app && OLLAMA_BASE_URL=http://ollama:11434 python3 patient_sim.py list'

# Check if Ollama is running and the model is available
docker compose exec triage bash -c 'cd /app && OLLAMA_BASE_URL=http://ollama:11434 python3 patient_sim.py check'

# Get a patient's opening message
docker compose exec triage bash -c 'cd /app && OLLAMA_BASE_URL=http://ollama:11434 python3 patient_sim.py "Ana Costa"'

# Simulate a patient response to an agent question
docker compose exec triage bash -c 'cd /app && OLLAMA_BASE_URL=http://ollama:11434 python3 patient_sim.py "Ana Costa" "Can you describe your symptoms?"'
```

> **Note:** Always set `OLLAMA_BASE_URL=http://ollama:11434` when running inside the triage container (Docker network hostname). From the host, use `http://localhost:11434`.

### Automated Triage Tests

The `test_priority.py` harness supports automated end-to-end triage conversations using the patient simulator. The agent chats with a simulated patient until it assigns a priority, then compares the result against expected values.

```bash
# Ensure Ollama is running
docker compose up -d ollama

# Run automated triage for a single patient
docker compose exec triage bash -c 'cd /app && OLLAMA_BASE_URL=http://ollama:11434 python3 test_priority.py auto "Ana Costa"'

# Run automated triage for all 4 patients sequentially
docker compose exec triage bash -c 'cd /app && OLLAMA_BASE_URL=http://ollama:11434 python3 test_priority.py auto-all'
```

The `auto` command:
1. Resets any existing session
2. Starts the triage agent with the patient's opening message
3. Loops (up to 15 turns): feeds the agent's response to the patient simulator, sends the simulated reply back
4. Stops when the agent assigns a priority — prints pass/fail against expected values
5. Resets the session after completion

### Patient Simulator Configuration

| Env Var | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama API URL (use `http://localhost:11434` from host) |
| `OLLAMA_MODEL` | `gemma3:1b` | Ollama model to use for patient simulation |

## Usage

### Gradio UI (http://localhost:7860)

1. Open your browser at `http://localhost:7860`
2. Enter the patient's name (e.g., "Maria Silva") to start triage
3. The agent queries FHIR, asks contextual questions, analyzes risk, and updates the medical record
4. The trace panel shows real-time agent step progress

### CLI (cli.py)

```bash
# Inside the triage container
docker compose exec triage bash
cd /app
FHIR_BASE_URL=http://iris:52773/fhir/r4 OPENAI_API_KEY=sk-... python3 cli.py
```

Text-based interaction in the terminal. Type `exit` to quit.

## File Structure

```
python/triage/
.env # Configuration (FHIR_BASE_URL, OPENAI_API_KEY, LANGSMITH_*, LOG_LEVEL, LLM_CACHE) — NOT tracked in git
.env.example # Template without credentials
requirements.txt            # Python dependencies
Dockerfile                  # Python 3.12-slim image for the triage service
entrypoint.sh               # Container entrypoint (waits for FHIR, loads seed, starts MCP + Gradio)
seed_data.py # Script to load/clean/list test patients
seed_data/ # FHIR JSON bundles for loading
patient_sim.py # Patient simulator (Ollama-based) for automated triage testing
    patient_maria_silva.json
    patient_joao_santos.json
    patient_ana_costa.json
    patient_roberto_lima.json
fhir_server.py # MCP Server 1 — FHIR CRUD (port 8000)
triage_server.py # MCP Server 2 — contextual triage (port 8001)
clinical_reasoning_server.py # MCP Server 3 — clinical reasoning (port 8002)
knowledge_base.py # Shared vector-search RAG helpers (embeddings, IRIS DB-API, canonical template)
ingest_knowledge.py # Ingestion of the fedmml-ed-triage dataset into IRIS (vector knowledge base)
logging_config.py # Centralized logging config (LOG_LEVEL env var, stderr + file handlers)
agent.py # Agent core (SYSTEM_PROMPT, create_triage_agent, extract_ai_response)
cli.py                      # Interactive CLI interface
app.py # Gradio chat UI with trace panel — Web
test_priority.py # Priority test harness (manual + automated with patient simulation)
voice_bridge.py # Voice Bridge — OpenAI-compatible API for ElevenLabs (port 8003) *(roadmap)*
voice_session.py # Voice session store (language detection, auto-eviction) *(roadmap)*
tunnel.sh # SSH tunnel script (localhost.run) for public Voice Bridge access
start_servers.sh # Script to start the 3 MCP servers + Gradio (manual)
PLAN.md                     # Architecture plan and tools
PROGRESS.md                 # Progress history, discoveries, and decisions
README.md                   # This file
```

## MCP Servers — Tools

### fhir_server.py (port 8000) — 12 tools

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
| `create_flag_and_task` | POST /Flag + POST /Task | Alert + follow-up |

### triage_server.py (port 8001) — 5 tools

| Tool | Description |
|---|---|
| `build_contextual_questions` | Generates contextual questions based on FHIR history |
| `get_next_triage_question` | Returns the next triage question (one at a time) |
| `get_all_triage_topics` | Lists all triage topics for a patient context |
| `parse_symptoms` | Extracts symptoms, duration, severity |
| `check_red_flags` | Checks for warning signs |
| `build_questionnaire_response_data` | Builds FHIR QuestionnaireResponse |

### clinical_reasoning_server.py (port 8002) — 1 tool

| Tool | Description |
|---|---|
| `clinical_assessment` | Comprehensive assessment (risk score + priority + summary + follow-up tasks), grounded in similar ESI-labeled cases retrieved via IRIS vector search (RAG) when available |

## Observability

### Structured Logging

All modules use `logging_config.py` for centralized logging with the `LOG_LEVEL` env var (default: `DEBUG`). Logs go to both stderr (visible via `docker compose logs`) and per-module files in `/tmp/`.

| Log level | What you see |
|---|---|
| `DEBUG` | Full FHIR request/response payloads, LLM prompts/responses, MCP URLs, tool names, cache HIT/MISS |
| `INFO` | Tool calls, agent creation, cache status, resource creation, errors |

**View logs:**

```bash
# Live stderr (all modules mixed)
docker compose logs triage -f

# Live stderr — DEBUG lines only
docker compose logs triage -f | grep DEBUG

# Per-module log files (inside container)
docker compose exec triage tail -f /tmp/fhir_server.log
docker compose exec triage tail -f /tmp/triage_server.log
docker compose exec triage tail -f /tmp/cr_server.log
docker compose exec triage tail -f /tmp/voice_bridge.log
docker compose exec triage tail -f /tmp/app.log
```

**Change log level:** Set `LOG_LEVEL` in `.env` (e.g., `LOG_LEVEL=INFO` for quieter output, `LOG_LEVEL=DEBUG` for full detail).

### Gradio Trace Panel

The Gradio UI includes a **trace panel** that shows agent step progress in real-time. Each tool call is mapped to one of the 5 workflow steps with visual indicators.

### LangSmith Tracing

To enable [LangSmith](https://smith.langchain.com/) tracing for detailed agent inspection:

1. Add `LANGSMITH_API_KEY` to `.env`
2. Set `LANGSMITH_TRACING=true` (enabled by default when the key is present)
3. Set `LANGSMITH_PROJECT=triage-aide` (or your preferred project name)

## LLM Cache

The agent supports optional caching of LLM responses and tool results to reduce API costs and latency during development. Controlled by the `LLM_CACHE` env var in `.env`:

| Value | Behavior |
|---|---|
| `off` | No caching (default) |
| `memory` | In-memory cache (resets on restart) |
| `sqlite` | SQLite-backed persistent cache (survives restarts) |

```bash
# Enable persistent SQLite cache (recommended for development)
LLM_CACHE=sqlite

# Enable in-memory cache (lost on restart)
LLM_CACHE=memory

# Disable caching
LLM_CACHE=off
```

When `LLM_CACHE=sqlite`, two caches are active:
- **LLM cache** — stores LLM completions keyed by normalized prompt + tool history (same patient input + same tool flow = cache hit)
- **Tool cache** — stores MCP tool results keyed by tool name + arguments

Cache files are stored at `~/.cache/langchain_cache.db` and `~/.cache/tool_cache.db` by default. Customize paths with `LLM_CACHE_DB_PATH` and `TOOL_CACHE_DB_PATH`. Each cache namespace (e.g., `gradio`, `voice`) gets its own SQLite file.

Cache hit/miss events are logged at `DEBUG` level (set `LOG_LEVEL=DEBUG` to see them).

## Voice Integration (ElevenLabs) *(Roadmap — next step)*

> **Status:** Backend implemented, UI tab hidden by default in the MVP. Enable with `ENABLE_VOICE_UI=true` in `.env`. The Voice Bridge runs on port 8003 regardless for testing. For the full design specification, see [`doc/elevenlabs-integration.md`](../../doc/elevenlabs-integration.md).

The triage agent supports voice interaction via [ElevenLabs Conversational AI](https://elevenlabs.io/conversational-ai). The **Voice Bridge** (`voice_bridge.py`) exposes an OpenAI-compatible `/v1/chat/completions` endpoint that ElevenLabs calls as a **Custom LLM**.

### Architecture

```
Browser (mic) → ElevenLabs (STT) → Voice Bridge (:8003) → Triage Agent → SSE chunks → ElevenLabs (TTS) → Browser (speaker)
```

### Voice Bridge Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat completions (SSE streaming) |
| `/health` | GET | Health check |
| `/widget` | GET | Standalone HTML page with ElevenLabs widget (for iframe embed) |

### Quick Test (no ElevenLabs account needed)

Replace `<VOICE_BRIDGE_SECRET>` with the value from your `.env` file:

```bash
# Streaming response
curl -X POST http://localhost:8003/v1/chat/completions \
-H "Content-Type: application/json" \
-H "Authorization: Bearer <VOICE_BRIDGE_SECRET>" \
-d '{"messages":[{"role":"user","content":"Iniciar triagem para Maria Silva"}],"stream":true}'
```

<details>
<summary>Click to expand full setup guide</summary>

### Configuration

Add these variables to your `.env`:

```bash
# Voice Bridge secret — generate with: openssl rand -hex 32
VOICE_BRIDGE_SECRET=your-secret-here

# ElevenLabs agent ID (from Conversational AI dashboard)
ELEVENLABS_AGENT_ID=agent_xxxxxxxxxx

# ElevenLabs widget embed ID (optional, defaults to ELEVENLABS_AGENT_ID)
ELEVENLABS_WIDGET_ID=agent_xxxxxxxxxx

# Public URL of the Voice Bridge (update after opening tunnel)
VOICE_BRIDGE_URL=http://localhost:8003

# Show the Voice tab in Gradio UI
ENABLE_VOICE_UI=true
```

> **Important:** `VOICE_BRIDGE_SECRET` must be set **only** in `.env`. Do NOT set it in the `docker-compose.yml` `environment:` section — `environment:` takes precedence over `env_file:` and silently overrides the `.env` value, which causes 401 errors if the values differ.

### ElevenLabs Dashboard Setup

1. Go to **Conversational AI → Create Agent** in the ElevenLabs dashboard
2. Under **Configure → Agent**, set **LLM** to **Custom LLM**
3. Set **LLM URL**: `https://<your-tunnel-url>/v1/chat/completions`
4. Set **Authorization**: `Bearer <your VOICE_BRIDGE_SECRET>`
5. Select a Brazilian Portuguese or English voice and enable **language auto-detection**
6. Copy the **Agent ID** from the URL and set it as `ELEVENLABS_AGENT_ID` in `.env`

### Gradio Voice Tab

When `ENABLE_VOICE_UI=true`, the Gradio UI includes a **Voice** tab with the ElevenLabs conversational widget. Enter your Agent ID and click **Load Widget** to start a voice session.

The agent automatically detects Portuguese (`pt-BR`) or English (`en`) from the user's first message and responds in the same language.

### Session Management

- Each conversation is tracked by a session ID (from ElevenLabs `X-EL-Conversation-Id` header)
- Sessions auto-expire after 30 minutes of inactivity
- Markdown is stripped from agent responses for clean TTS output
- Voice mode uses shorter, conversational responses (max 3 sentences, no markdown)

## Public Tunnel (localtunnel) *(Roadmap)*

ElevenLabs needs a publicly accessible HTTPS URL to reach the Voice Bridge.

```bash
# From the project root (host machine, not inside the container)
./start_tunnel.sh
```

Or manually:

```bash
npx localtunnel --port 8003 --subdomain dark-ways-itch
```

After starting the tunnel:

1. Update your `.env`: `VOICE_BRIDGE_URL=https://dark-ways-itch.loca.lt`
2. In the ElevenLabs dashboard, set the Custom LLM URL to `https://dark-ways-itch.loca.lt/v1/chat/completions`
3. Verify: `curl https://dark-ways-itch.loca.lt/health`

### Alternative tunnel methods

- **ngrok**: `ngrok http 8003`
- **localhost.run**: `ssh -R 80:localhost:8003 localhost.run`
- **Cloudflare Tunnel**: For production, use [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)

## ElevenLabs Agent Configuration (`11labs/myagent.json`) *(Roadmap)*

The `11labs/myagent.json` file is an exported configuration of the ElevenLabs Conversational AI agent. It contains the full agent setup for reference and re-import.

### Key fields in the JSON

| Field | Value | Description |
|---|---|---|
| `agent_id` | `agent_7001kt5n1cv6fj687wvbaxy81r0y` | Matches `ELEVENLABS_AGENT_ID` in `.env` |
| `agent.first_message` | `"Olá! Como posso ajudar?"` | Initial greeting |
| `prompt.llm` | `"custom-llm"` | Tells ElevenLabs to call the Voice Bridge |
| `custom_llm.url` | `"https://dark-ways-itch.loca.lt/v1"` | Base URL (update if tunnel URL changes) |
| `tts.model_id` | `"eleven_flash_v2_5"` | TTS model — low latency |

</details>

## Troubleshooting

### Check if MCP servers are running

```bash
docker compose exec triage bash -c 'cat /tmp/fhir_server.log'
docker compose exec triage bash -c 'cat /tmp/triage_server.log'
docker compose exec triage bash -c 'cat /tmp/cr_server.log'
docker compose exec triage bash -c 'cat /tmp/voice_bridge.log'
```

For live logging with structured output:
```bash
docker compose exec triage bash -c 'tail -f /tmp/voice_bridge.log'
```

If logs lack detail, verify `LOG_LEVEL=DEBUG` in `.env` and restart the triage container.

### Restart MCP servers manually

```bash
docker compose exec triage bash -c 'pkill -f fhir_server.py; pkill -f triage_server.py; pkill -f clinical_reasoning_server.py'
docker compose exec triage bash -c 'cd /app && bash start_servers.sh'
```

### Reload test data

```bash
docker compose exec triage bash -c 'cd /app && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py clean && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py load'
```

### Error "OPENAI_API_KEY not set"

Verify that the `python/triage/.env` file exists and contains the `OPENAI_API_KEY` variable with a valid key.

### Port 7860 not accessible

1. Check if the containers are running: `docker compose ps`
2. Check if the port is mapped in `docker-compose.yml` (`7860:7860` on the triage service)
3. Check the triage container log: `docker compose logs triage`

### Pip installs are lost on container restart

Triage dependencies are installed in `python/triage/Dockerfile` (`pip3 install ...`). If you installed something extra manually with pip inside the container, it will be lost on restart. Add new dependencies to `Dockerfile` and `requirements.txt` for persistence.

### Voice Bridge not responding *(Roadmap)*

1. Check if the Voice Bridge process is running: `docker compose exec triage bash -c 'cat /tmp/voice_bridge.log'`
2. Verify the bridge health endpoint: `curl http://localhost:8003/health`
3. Ensure `VOICE_BRIDGE_SECRET` matches between `.env` and the ElevenLabs dashboard Authorization header
4. If using a tunnel, verify the tunnel is active and the URL is correct in the ElevenLabs dashboard
5. If you get 401 errors, verify the container is using the correct secret (not a default or overridden value):

```bash
# Check what the container actually sees
docker compose exec triage bash -c 'echo $VOICE_BRIDGE_SECRET | wc -c'
# Should be 65 (64 hex chars + newline) if using openssl rand -hex 32
# If it shows 8, it's using the default "changeme"
```

### Tunnel URL not working *(Roadmap)*

1. Make sure the Voice Bridge is running on port 8003 before starting the tunnel
2. Restart the tunnel — `localhost.run` URLs change each session
3. Update `VOICE_BRIDGE_URL` in `.env` and the ElevenLabs dashboard with the new URL

## Tech Stack

- **FHIR Server**: InterSystems IRIS for Health Community Edition
- **MCP**: FastMCP with streamable-http transport
- **Agent**: LangChain + langchain-mcp-adapters + OpenAI gpt-4o-mini
- **UI**: Gradio ChatInterface with trace panel
- **Observability**: LangSmith tracing (optional) + structured logging (LOG_LEVEL)
- **Language**: Python 3
- **Deploy**: Docker Compose (3 services: iris + triage + ollama)
