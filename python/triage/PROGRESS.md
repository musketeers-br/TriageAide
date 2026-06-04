# Progress — Pre-Consultation Triage Agent

## Progress History

### Phase 1: Concept and Planning

- Defined the FHIR-First scenario: agent queries history BEFORE talking to the patient
- Documented in `doc/scenario1.md` (5-step flow) and `doc/app-description.md` (concept)
- Architectural decision: 3 MCP servers (FHIR, Triage, Clinical Reasoning) + LangChain agent + Gradio UI
- Stack decision: FastMCP (streamable-http), langchain-mcp-adapters, OpenAI gpt-4o-mini, Gradio
- Language decision: agent responds in English
- Deployment decision: MCP servers run inside the Docker container (not externally)
- Created `python/triage/PLAN.md` with complete tool specifications and test scenarios

### Phase 2: MCP Servers Implementation

- **fhir_server.py** (port 8000): 12 FHIR CRUD tools implemented
- 7 read tools: search_patients, get_patient, get_patient_conditions, get_patient_medications, get_patient_observations, get_patient_allergies, get_patient_encounters
- 5 write tools: create_observation, create_condition, create_questionnaire_response, create_encounter, create_flag_and_task
- Critical discovery: IRIS FHIR Server returns HTTP 201 with empty body on POSTs. The created resource ID is in the header `Location` in the format `http://host/fhir/r4/ResourceType/ID/_history/1`. Fix implemented in `_fhir_post()`.
- **triage_server.py** (port 8001): 5 tools implemented
- `build_contextual_questions`: generates questions based on FHIR history (not generic)
- `get_next_triage_question`: returns the next triage question (one at a time) based on history and covered topics
- `get_all_triage_topics`: lists all triage topics for a patient context
- `parse_symptoms`: extracts symptoms, duration, severity from patient text
- `check_red_flags`: cross-references symptoms with existing conditions to identify warning signs
- `build_questionnaire_response_data`: builds structured FHIR QuestionnaireResponse
- **clinical_reasoning_server.py** (port 8002): 4 tools implemented
- `assess_clinical_risk`: scoring with weights by chronic condition, symptom and abnormal observation
- `suggest_priority`: maps score to routine/urgent/emergency
- `generate_clinical_summary`: clinical summary for the physician
- `identify_follow_up_tasks`: follow-up tasks based on risk and care gaps

### Phase 3: Orchestrator Agent

- **agent.py**: Agent core (SYSTEM_PROMPT, create_triage_agent(), extract_ai_response())
- **cli.py**: Interactive CLI interface (imports from agent.py)
- **app.py**: Gradio ChatInterface web (imports from agent.py)
- Discovery: Gradio 6.x removed the parameter `type="messages"`. History passed as `list[dict]` with `role`/`content`.
- Discovery: `asyncio.run()` cannot be called inside existing async loop (Gradio). Used `asyncio.get_event_loop().run_until_complete()` or equivalent approach.
- Detailed system prompt with 5 mandatory steps, language and output format rules

### Phase 4: Test Data (seed_data.py)

- Created 4 complete FHIR JSON bundles in `seed_data/`:
- **Maria Silva**: DM2 + HAS + HbA1c 8.2% + Metformin + Losartan + Penicillin Allergy
- **Joao Santos**: IC + FA + DM2 + HAS + CKD stage 3 + Warfarin + ASA Allergy
- **Ana Costa**: No active conditions, no medications
- **Roberto Lima**: COPD + HAS + Osteoarthritis + Depression + SpO2 93% + Dipyrone Allergy (anaphylaxis)
- **Critical discovery**: FHIR Bundles with `urn:uuid:` references don't work with individual POSTs in IRIS FHIR Server. Rewrite of seed_data.py to: (1) create Patient first, (2) resolve all `urn:uuid:` references to `Patient/{actual_id}`, (3) create dependent resources.
- Features: `load` (loads patients), `clean` (removes patients with tag `triage-seed`), `list` (lists loaded patients)
- Patients tagged with `triage-seed` to facilitate identification and cleanup

### Phase 5: Docker Infrastructure (Single Container)

- **Dockerfile**: added line `pip3 install requests python-dotenv fastmcp langchain langchain-mcp-adapters langchain-openai gradio`
- **docker-compose.yml**: ports added 8000, 8001, 8002, 7860; custom entrypoint
- **custom-entrypoint.sh**: wrapper that started MCP servers in background before IRIS entrypoint
- **start_mcp_servers.sh**: script that (1) read OPENAI_API_KEY from .env, (2) started 3 MCP servers, (3) waited for readiness, (4) loaded seed data automatically if not present
- **start_servers.sh** (inside python/triage): manual version for debugging, start MCP servers + Gradio in foreground

### Phase 6: End-to-End Test

- Complete test with Maria Silva: agent queried FHIR, generated contextual questions, analyzed symptoms, assessed risk (moderate), created Encounter resource back in FHIR

### Phase 7: Critical Bugfixes

- **Bug: Gradio didn't start on container boot** — `start_mcp_servers.sh` only started the 3 MCP servers, not `app.py`. Added lines to start Gradio in background.
- **Bug: MCP sessions closed after `_get_agent()`** — The `async with _client.session(...)` pattern loaded tools inside a context manager which closed MCP sessions on return. When the agent tried to call a tool, the session was already closed. Solution: use `_client.get_tools()` which creates sessions per call, instead of `load_mcp_tools(session)` inside context manager.
- **Bug: Agent called `get_patient("Maria Silva")` instead of ID** — The LLM didn't know it needed the numeric ID. Solution: added `search_patients(name)` tool to fhir_server.py with multi-strategy search (family, given, name).
- **Bug: IRIS FHIR `name` param doesn't support full name** — `?name=Maria Silva` returns 0 results. `?family=Silva` or `?given=Maria` works. Solution: `search_patients` tries multiple strategies (family, given, partial name).
- Added `get_next_triage_question` and `get_all_triage_topics` tools to triage_server.py (5 tools total, up from 4)
- Validation of the complete 5-step flow

### Phase 8: Translation to English

- All code comments, docstrings, variable names, and documentation translated from Portuguese to English
- Updated `PLAN.md`, `PROGRESS.md`, `README.md`
- Agent system prompt updated to respond in English (was Portuguese)
- Note: `doc/app-description.md` and `doc/scenario1.md` were initially left in Portuguese, later translated

### Phase 9: Separate Docker Services

- Split IRIS FHIR server and triage app into **two independent Docker services** on a shared `fhir-net` bridge network
- **iris service**: IRIS for Health only (ports 32782-32784)
- **triage service**: Python 3.12-slim with MCP servers + agent + Gradio (ports 8000-8002, 7860)
- Created `python/triage/Dockerfile` for the triage service
- Created `python/triage/entrypoint.sh` — container entrypoint that: waits for FHIR server, loads seed data, starts MCP servers, starts Gradio
- Deleted obsolete `custom-entrypoint.sh` and `start_mcp_servers.sh` (were iris-container scripts)
- Updated `docker-compose.yml` with two services, `env_file`, and `fhir-net` network
- Updated `.env.example` with `FHIR_USER`, `FHIR_PASS`, `LANGSMITH_*` variables
- Triage container uses `http://iris:52773/fhir/r4` (container-internal URL via Docker DNS)

### Phase 10: LangSmith Observability

- Added LangSmith tracing support for agent inspection
- Added `langsmith` to `requirements.txt`
- Updated `.env.example` with `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_TRACING`
- Updated `entrypoint.sh` to conditionally enable LangSmith when `LANGSMITH_API_KEY` is set
- Added LLM caching via SQLite (`LLM_CACHE=sqlite`) to reduce costs during development
- Updated `agent.py` with cache prompt normalization for consistent cache hits

### Phase 11: Gradio Trace Panel

- Added agent observability to the Gradio UI with a real-time trace panel
- Each tool call is mapped to one of the 5 workflow steps with visual indicators (step labels and icons)
- Tool results are summarized for concise display (e.g., "3 condition(s) retrieved", "HIGH (score 7)")
- Expanded `app.py` significantly (~660 lines) with step mapping, tool icons, result summarization, and trace rendering
- Uses `gr.ChatMessage` with metadata for structured tool call display

---

## Technical Discoveries (Lessons Learned)

### 1. IRIS FHIR Server: POST returns empty body (HTTP 201)

The InterSystems IRIS for Health FHIR Server returns HTTP 201 Created with an **empty body** when creating resources via POST. The created resource ID is in the `Location` header:

```
Location: http://host/fhir/r4/Patient/123/_history/1
```

**Impact**: Any code that does `resp.json()` after a POST will fail with JSONDecodeError.

**Solution**: `_fhir_post()` extracts the ID from the Location header via regex and returns `{"id": extracted_id}` instead of `resp.json()`.

### 2. `urn:uuid:` references don't work with individual POSTs

Transactional FHIR Bundles with `urn:uuid:` references assume that the server resolves references in the bundle context. The IRIS FHIR Server (via individual POSTs outside of transaction) doesn't resolve these references.

**Solution**: Rewrite of `seed_data.py` to create the Patient first, extract the real ID, and replace all occurrences of `urn:uuid:` with `Patient/{actual_id}` before creating dependent resources.

### 3. `load_dotenv()` does NOT override existing environment variables

If an environment variable is already defined in the shell (via `export`), `load_dotenv()` does not override it. This causes confusion when `start_servers.sh` does `export FHIR_BASE_URL=http://localhost:52773/fhir/r4` (container internal port) but the `.env` has `http://localhost:32783/fhir/r4` (host port).

**Solution**: `start_servers.sh` and `entrypoint.sh` export `FHIR_BASE_URL` with the internal port (52773) explicitly before running the servers. The `.env` has the host port (32783) for use when running outside the container.

### 4. Pip installs in a running container are lost on restart

Any `pip install` done manually inside the container is lost when the container is recreated.

**Solution**: All triage dependencies are added to `python/triage/Dockerfile`. For new dependencies, update Dockerfile + requirements.txt and rebuild.

### 5. Gradio 6.x: API changes

- `gr.ChatInterface` no longer accepts the parameter `type="messages"`
- History is passed as `list[dict]` with keys `role` and `content`
- Cannot call `asyncio.run()` inside an existing event loop (Gradio runs async internally)

**Solution**: Removed `type="messages"`, adjusted history format, used proper async event loop management.

### 6. `create_agent()` supports `system_prompt`

The `create_agent()` function from `langchain.agents` accepts the parameter `system_prompt`. This is better than manually pre-pending `SystemMessage` to the message list, since the framework manages the system prompt more robustly.

### 7. MCP sessions via `async with` close after the context manager

Using `async with _client.session("server")` to load tools is dangerous: MCP sessions are closed when the `async with` block ends. The agent then cannot call the tools because the sessions are dead.

**Solution**: Use `_client.get_tools()` which loads tools creating sessions per call (each tool call opens and closes its own session). Do not use `load_mcp_tools(session)` inside context manager to create the agent.

### 8. IRIS FHIR `name` search param doesn't support full name

The parameter `?name=Maria Silva` returns 0 results in the IRIS FHIR Server. Search works only with name parts: `?family=Silva` or `?given=Mary`.

**Solution**: `search_patients()` tries multiple strategies: (1) `family` + `given` separately, (2) `name` with each part individually. Stops at the first one that returns results.

### 9. Container-internal vs host URLs for FHIR

From the triage container, use `http://iris:52773/fhir/r4` (Docker DNS resolves `iris` to the FHIR container). From the host, use `http://localhost:32783/fhir/r4`.

**Solution**: `entrypoint.sh` defaults to `http://iris:52773/fhir/r4`. `docker-compose.yml` sets `FHIR_BASE_URL=http://iris:52773/fhir/r4` as environment variable. `.env.example` documents both options.

---

## Architectural Decisions

| Decision | Alternative Considered | Justification |
|---|---|---|
| 3 separate MCP servers | 1 monolithic MCP server | Separation of responsibilities: FHIR (data), Triage (triage logic), Clinical Reasoning (reasoning). Facilitates maintenance and extension. |
| FastMCP streamable-http | stdio transport | Streamable-http allows services to run on separate ports and be accessible via HTTP, compatible with containerization. |
| gpt-4o-mini | gpt-4o, gpt-3.5-turbo | Cost-benefit: gpt-4o-mini is cheap and competent for triage. gpt-4o would be overkill for the scope. |
| Separate Docker services (iris + triage) | Single container (iris + triage) | Clean separation of concerns. Triage app is a Python service independent of IRIS. Simplifies rebuilds, scaling, and debugging. |
| LangSmith tracing (optional) | Custom logging | LangSmith provides rich agent trace visualization without custom code. Optional — no impact when key is absent. |
| LangChain + langchain-mcp-adapters | Custom MCP client | langchain-mcp-adapters already solves MCP → LangChain tools integration. Avoids reinventing the wheel. |
| Gradio | Streamlit, Flask | Gradio ChatInterface is the simplest for prototyping a chat. Streamlit would require more code for the same result. |
| seed_data.py with `triage-seed` tag | Manual resource removal | Tag allows automatic `clean`: removes all resources with the tag, without needing to track IDs. |
| System prompt embedded in code | External prompt in file | Simplifies deployment (1 fewer file). If it needs to be configurable, extract to file later. |
| LLM SQLite caching | No caching | Reduces OpenAI API costs during development. Cache keys are normalized to hit across identical invocations. |

---

## Current Status

### Completed

- [x] 3 MCP servers (FHIR, Triage, Clinical Reasoning) implemented and running
- [x] Agent core (`agent.py`), CLI (`cli.py`) and Web UI (`app.py`) functional
- [x] 4 test patients with complete FHIR bundles
- [x] Seed data with load/clean/list
- [x] Complete Docker infrastructure (2 services: iris + triage, Docker Compose)
- [x] Auto-startup of MCP servers + seed data via `entrypoint.sh`
- [x] End-to-end test with Maria Silva
- [x] Documentation (README, PROGRESS, updated PLAN)
- [x] Test Gradio UI externally (host port 7860)
- [x] Test with all 4 patients (Joao, Ana, Roberto)
- [x] Patient search by name (`search_patients` tool)
- [x] Separate Docker services (iris + triage)
- [x] LangSmith observability (optional)
- [x] Gradio trace panel for real-time agent step progress
- [x] Translation to English (code + docs)

### Pending / Needs Attention

- [ ] Agent doesn't always create all expected FHIR resources (Flag, Task, QuestionnaireResponse) — depends on the LLM's decision; may need prompt adjustment
- [ ] Container restart test to validate complete auto-startup pipeline

### Future Work / Nice-to-have

- [ ] Voice interaction (mentioned in `doc/app-description.md`, not implemented)
- [ ] Prompt refinement to ensure consistent creation of QuestionnaireResponse and Tasks
- [ ] Contest submission preparation
- [ ] Automated tests (currently only manual tests via curl/Gradio)
- [ ] Structured logging of MCP servers
- [ ] Health check endpoints in MCP servers
