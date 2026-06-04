# AGENTS.md - iris-fhir-template

This file provides guidance for agentic coding agents working in this repository.

## Project Overview

InterSystems IRIS for Health Community Edition FHIR Server template with a **FHIR-First Pre-Consultation Triage AI Agent**. The project has two layers:

1. **Base**: FHIR R4 server setup, test patient data import, demo web UI (original template)
2. **Triage App** (`python/triage/`): AI agent that queries FHIR patient history, conducts contextual pre-consultation triage, and writes back FHIR resources

The triage app is the main application. See `python/triage/README.md` and `python/triage/PROGRESS.md` for full details.

## Build / Run / Test Commands

### Docker (primary development method)
```bash
# Build containers (no cache)
docker compose build --no-cache --progress=plain

# Start containers
docker compose up -d

# Stop containers
docker compose down

# Clean up docker (if disk space issues)
docker system prune -f
```

### IRIS Terminal Access
```bash
# Open IRIS terminal in FHIRSERVER namespace
docker compose exec iris iris session iris -U FHIRServer

# Open IRIS terminal in USER namespace
docker compose exec iris iris session iris -U USER
```

### Triage Container Access
```bash
# Open shell in triage container
docker compose exec triage bash

# Run CLI agent
docker compose exec triage bash -c 'cd /app && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 cli.py'

# Check MCP server logs
docker compose exec triage bash -c 'cat /tmp/fhir_server.log'
docker compose exec triage bash -c 'cat /tmp/triage_server.log'
docker compose exec triage bash -c 'cat /tmp/cr_server.log'

# Check triage container logs
docker compose logs triage
```

### Load Patient Data
```bash
# Generate synthetic patients via Synthea (e.g., 10 patients)
./synthea-loader.sh 10

# Load FHIR data from directory into server (from IRIS terminal)
d ##class(fhirtemplate.Setup).LoadPatientData("/data/fhir","FHIRSERVER","/fhir/r4")

# Or use FHIR.utils.load (from IRIS terminal)
d ##class(FHIR.utils).load("/data/fhir/")
```

### FHIR Server Setup (from IRIS terminal)
```bash
# FHIR namespace setup
Do ##class(HS.Util.Installer.Foundation).Install(namespace)

# FHIR server interactive configuration
do ##class(HS.FHIRServer.ConsoleSetup).Setup()

# Install additional FHIR server instances
do ##class(FHIR.utils).install("PID") # Creates /pid/fhir/r4 endpoint
do ##class(FHIR.utils).install("CLINIC") # Creates /clinic/fhir/r4 endpoint

# Uninstall a FHIR server instance
do ##class(FHIR.utils).uninstall("PID")
```

### Lint / Quality
- **ObjectScript Quality**: automated via GitHub Actions on push (`.github/workflows/objectscript-quality.yml`)
- Uses `objectscriptquality` service — no local lint command; quality checks run in CI only
- Badge: [Quality Gate](https://community.objectscriptquality.com/dashboard?id=intersystems_iris_community%2Firis-fhir-template)

### Testing
- No automated unit test framework is configured in this repository
- Manual testing via FHIR API calls (curl/Postman) and the demo UI
- FHIR API endpoint: `http://localhost:32783/fhir/r4`
- Swagger UI: `http://localhost:32783/swagger-ui/index.html`
- Demo UI: `http://localhost:32783/fhirUI/FHIRAppDemo.html`
- Patient Portal: `http://localhost:32783/fhir/portal/patientlist.html`

### IPM (InterSystems Package Manager)
```bash
# Install via ZPM (from IRIS terminal)
zpm "install fhir-server"

# Install programmatically
set sc=$zpm("install fhir-server")

# Load local module (from IRIS terminal)
zpm "load /home/irisowner/irisdev/ -v"
```

## Code Style Guidelines

### ObjectScript (.cls files)

- **File encoding**: All `.cls`, `.mac`, `.int`, `.sh` files use LF line endings (enforced via `.gitattributes`)
- **Class naming**: `PackageName.ClassName` — packages use PascalCase (e.g., `fhirtemplate.Setup`, `FHIR.utils`, `User.SQLvar`)
- **Method naming**: PascalCase for ClassMethods and instance methods (e.g., `SetupFHIRServer`, `LoadPatientData`, `GetJSON`)
- **ClassMethod keyword**: Use `ClassMethod` (not `Classmethod` or `CLASSMETHOD`)
- **Return types**: Always declare return type `As %Status` for methods that can fail; use `As %String` for simple returns
- **Status handling**: Use `set sc = $$$OK` at start; check with `'st` or `if 'sc`; use `$System.Status.GetErrorText(sc)` for error details
- **Try/Catch**: Use `Try { ... } Catch ex { set sc=ex.AsStatus() }` pattern for error handling (see `FHIR.utils` methods)
- **Comments**: Use `//` for inline comments, `///` for method doc comments (description before method signature)
- **Commented-out code**: Use `#;` prefix for disabled/commented-out ObjectScript lines (convention in this repo)
- **Variable naming**: lowercase/camelCase for local variables (e.g., `sc`, `st`, `namespace`, `appKey`, `interactionsStrategy`)
- **Class references**: Use `##class(Package.Class).Method()` syntax for class method calls
- **Namespace switching**: Use `zn "NAMESPACE"` to change namespace within code
- **VALUELIST parameter**: Use `As %String(VALUELIST=",option1,option2")` for enum-like parameters

### Parameter defaults (from module.xml)
- Default namespace: `FHIRSERVER`
- Default webapp: `/fhir/r4`
- Default interactions strategy: `JsonAdvSql` (more performant; alternative: `Json`)
- Default test data load: enabled (`AddTestData=1`)

### Docker / Infrastructure

Two separate Docker services on a shared `fhir-net` bridge network:

- **iris service**:
  - Base image: `intersystemsdc/irishealth-community:latest`
  - Ports: 32782→1972 (IRIS SuperServer), 32783→52773 (Web/REST), 32784→53773
  - Container name: `fhir-template`
  - Multi-stage build: builder stage compiles/loads; final stage copies data only
- **triage service**:
  - Base image: `python:3.12-slim`
  - Ports: 8000→8000 (FHIR MCP), 8001→8001 (Triage MCP), 8002→8002 (Clinical Reasoning MCP), 7860→7860 (Gradio UI)
  - Container name: `triage-app`
  - Depends on `iris` service
  - Volume-mounted `./python/triage:/app` for live editing
  - **Internal networking**: Triage container reaches FHIR at `http://iris:52773/fhir/r4`
- **Default credentials**: `_SYSTEM` / `SYS` (dev only; configured in `.vscode/settings.json`)

### Frontend (fhirUI/)

- Plain HTML + jQuery + Plotly.js + fhir.js library
- FHIR API calls use `application/fhir+json` content type
- jQuery-based AJAX adapter for fhir.js client

### SQL (misc/sql/)

- Uses `HSFHIR_X0001_S` schema for structured FHIR data and `HSFHIR_X0001_R` for raw resources
- Custom SQL functions: `GetJSON()`, `GetProp()`, `GetAtJSON()`, `GetFHIRPath()`, `GetFHIRPathOne()` (defined in `User.SQLvar`)

## Key FHIR API Endpoints (when container is running)

| Endpoint | Description |
|---|---|
| `GET /fhir/r4/metadata` | FHIR server capability statement |
| `GET /fhir/r4/Patient` | List all patients |
| `GET /fhir/r4/Patient/{id}` | Get a specific patient |
| `GET /fhir/r4/Observation?patient={id}` | Observations for a patient |
| `POST /fhir/r4/Patient` | Create a patient |

### Triage App Endpoints

| Endpoint | Description |
|---|---|
| `http://localhost:7860` | Gradio Web UI (pre-consultation triage chat with trace panel) |
| `http://localhost:8000/mcp` | FHIR MCP Server (streamable-http) |
| `http://localhost:8001/mcp` | Triage MCP Server (streamable-http) |
| `http://localhost:8002/mcp` | Clinical Reasoning MCP Server (streamable-http) |

## Triage App (`python/triage/`)

### Architecture

3 MCP servers (FastMCP, streamable-http) + LangChain agent + Gradio UI with trace panel:

- `fhir_server.py` (:8000) — 12 FHIR CRUD tools
- `triage_server.py` (:8001) — 5 contextual triage tools
- `clinical_reasoning_server.py` (:8002) — 4 clinical risk reasoning tools
- `agent.py` — Core agent factory (LangChain + OpenAI gpt-4o-mini) — system prompt, create_triage_agent(), extract_ai_response()
- `cli.py` — CLI interactive interface (imports from agent.py)
- `app.py` — Gradio web chat interface with trace panel (imports from agent.py)

### Key Files

- `python/triage/.env` — Config (OPENAI_API_KEY, LANGSMITH_*) — NOT tracked in git
- `python/triage/.env.example` — Template without credentials
- `python/triage/seed_data.py` — Load/clean/list test patients
- `python/triage/seed_data/` — FHIR Bundle JSON files for 4 test patients
- `python/triage/Dockerfile` — Python 3.12-slim image for the triage service
- `python/triage/entrypoint.sh` — Container entrypoint (waits for FHIR, loads seed data, starts MCP servers + Gradio)
- `python/triage/start_servers.sh` — Manual start script for MCP servers + Gradio

### Running

MCP servers and Gradio start automatically with `docker compose up -d` via `python/triage/entrypoint.sh`. The triage container waits for the FHIR server to be ready, loads seed data on first boot, then starts MCP servers and Gradio.

To run manually inside the triage container:
```bash
docker compose exec triage bash
cd /app
bash start_servers.sh
```

### IRIS FHIR Server Quirks (Important)

1. **POST returns empty body (HTTP 201)**: The created resource ID is in the `Location` header, not in the response body. Code must parse `Location: http://host/fhir/r4/ResourceType/ID/_history/1`.
2. **`urn:uuid:` references don't resolve with individual POSTs**: Must create Patient first, resolve all `urn:uuid:` to `Patient/{actual_id}`, then create dependent resources.
3. **Container-internal vs host URLs**: From the triage container, use `http://iris:52773/fhir/r4`. From the host, use `http://localhost:32783/fhir/r4`.
4. **`load_dotenv()` does NOT override existing env vars**: Scripts must `export` the correct FHIR_BASE_URL before running Python.

### Documentation

- `python/triage/README.md` — Full usage instructions, troubleshooting, architecture
- `python/triage/PROGRESS.md` — Progress history, technical discoveries, architectural decisions
- `python/triage/PLAN.md` — Architecture plan, tool specs, test scenarios, status tracking

## Repository Structure

```
src/                                    # ObjectScript source code
  fhirtemplate/Setup.cls                # FHIR server installer & data loader
  FHIR/utils.cls                        # FHIR server install/uninstall/purge/load utilities
  User/SQLvar.cls                        # SQL helper functions for JSON/FHIRPath queries
data/fhir/                              # Pre-loaded Synthea patient JSON bundles
fhirUI/                                 # Demo frontend (HTML + JS)
misc/sql/                               # Example SQL queries
misc/postman/                           # Postman collection for FHIR API
python/triage/                          # Triage App (main application)
  fhir_server.py                        # MCP Server 1 — FHIR CRUD (port 8000)
  triage_server.py                      # MCP Server 2 — Triage contextual (port 8001)
  clinical_reasoning_server.py          # MCP Server 3 — Clinical reasoning (port 8002)
  agent.py                              # Core agent factory (SYSTEM_PROMPT, create_triage_agent, extract_ai_response)
  cli.py                                # CLI interactive interface
  app.py                                # Gradio web UI chat with trace panel
  seed_data.py                          # Test patient load/clean/list script
  seed_data/                            # FHIR Bundle JSON for 4 test patients
  .env.example                          # Config template (no real credentials)
  requirements.txt                      # Python dependencies
  Dockerfile                            # Python 3.12-slim image for triage service
  entrypoint.sh                         # Container entrypoint (waits for FHIR, loads seed, starts MCP + Gradio)
  start_servers.sh                      # Manual start script (MCP servers + Gradio)
  PLAN.md                               # Architecture plan & tool specs
  PROGRESS.md                           # Progress history & technical discoveries
  README.md                             # Usage instructions & troubleshooting
python/example/                         # Earlier MCP example (reference, not the triage app)
doc/                                    # Documentation
  app-description.md                    # App concept & architecture description
  scenario1.md                          # Detailed triage scenario (5-step workflow)
iris.script                             # IRIS initialization script (runs on docker build)
merge.cpf                               # CPF merge actions (namespaces, databases)
module.xml                              # IPM package definition
Dockerfile                              # Multi-stage Docker build (IRIS for Health only)
docker-compose.yml                      # Docker Compose configuration (iris + triage services)
```

## Important Notes

- The `data/` and `fhirUI/` directories are volume-mounted in docker-compose for live editing
- Always rebuild with `--no-cache` after significant changes to ObjectScript code
- The FHIR server uses the `JsonAdvSql` interactions strategy by default for better performance and OAuth support
- Debug mode is set to `4` in the service config during setup (logs FHIR requests/responses)
- The `python/triage/` directory is volume-mounted in docker-compose for live editing of the triage app
- The `python/triage/.env` file contains real credentials (OPENAI_API_KEY) — it is NOT tracked in git
- Pip installs done manually inside a running container are lost on restart — add new dependencies to `python/triage/Dockerfile` and `requirements.txt`
- MCP servers auto-start on container boot via `python/triage/entrypoint.sh` — check container logs with `docker compose logs triage`
