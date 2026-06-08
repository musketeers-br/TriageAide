# Build Test Plan — Clean Slate Verification

Goal: Remove all traces of the project from Docker, then follow the README instructions exactly to verify both the instructions and the build process work from scratch.

> **Note:** Phases 1 (Clone) and 2 (Set OpenAI API key) are skipped — the repo is already
> cloned and `.env` is already configured.

**Last executed:** 2026-06-08 — all phases PASS with findings noted below.

---

## Phase 0 — Clean Slate

| # | Action | Command | Verify | Pass/Fail |
|---|---------------------------------|--------------------------------------------------------------|-----------------------------------------------------|-----------|
| 0.1 | Stop and remove containers | `docker compose down` | `docker compose ps` shows nothing | PASS |
| 0.2 | Remove project images | `docker rmi triageaide-iris triageaide-triage` | `docker images \| grep triageaide` shows nothing | PASS |
| 0.3 | Remove project network | `docker network rm triageaide_fhir-net` (if exists) | `docker network ls \| grep fhir` shows nothing | PASS |
| 0.4 | Remove project volumes (if any)| `docker volume prune -f` or targeted `docker volume rm` | `docker volume ls \| grep -E "triage\|fhir"` shows nothing | PASS |
| 0.5 | Verify clean state | `docker ps -a`, `docker images`, `docker network ls` | No TriageAide artifacts | PASS |

## Phase 3 — Build and Start (README "### 3 — Build and start")

The README Quick Start uses a single `docker compose up -d` command that builds (if needed) and starts containers in one step. We add `--progress plain` for readable build logs.

> **Note:** The "Setup — Step by Step" section in the README still shows separate
> `docker compose build` + `docker compose up -d` steps. This plan follows the
> Quick Start instructions. Any discrepancy should be flagged as a finding.

| # | Action | Command | Expected Result | Actual Result | Pass/Fail |
|---|-----------------------|-------------------------------------------------|-------------------------------------------------------|-------------------------------------------------------|-----------|
| 3.1 | Build and start | `docker compose --progress plain up -d` | Two images built + both containers start | Images `triageaide-iris:latest` (1.87GB) + `triageaide-triage:latest` (329MB) built; both containers Up | PASS |
| 3.2 | Triage waits for IRIS | Check triage logs | "Waiting for FHIR server..." then "FHIR server ready." | "Waiting for FHIR server at http://iris:52773/fhir/r4 ..." → "FHIR server ready." | PASS |
| 3.3 | Seed data auto-loads | Check triage logs | "Loading seed data..." then 4 patients loaded | "Loading seed data (if not already loaded)..." → 4 bundles loaded (Ana Costa → Patient/2605, Joao Santos → Patient/2610, Maria Silva → Patient/2627, Roberto Lima → Patient/2642) + all dependent resources (Conditions, Observations, MedicationRequests, AllergyIntolerances, Encounters) → "Seed data loaded." | PASS |
| 3.4 | MCP servers start | Check triage logs | "Port 8000 ready", "Port 8001 ready", "Port 8002 ready" | All 3 ports report ready via entrypoint.sh wait loop | PASS |
| 3.5 | Voice bridge starts | Check triage logs | "Starting Voice Bridge on port 8003..." | "Starting Voice Bridge on port 8003..." → "Agent ready — listening on port 8003." | PASS |
| 3.6 | Gradio starts | Check triage logs | "Starting Gradio UI on port 7860..." + "Running on local URL: http://0.0.0.0:7860" | "Starting Gradio UI on port 7860..." present. **"Running on local URL" NOT in logs** — Gradio doesn't emit this line when started via `exec` in Docker. Endpoint returns HTTP 200. | PASS (with finding) |

## Phase 4 — Test it (README "### 4 — Test it")

| # | Action | Command / Steps | Expected Result | Actual Result | Pass/Fail |
|---|-------------------------|---------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------|--------------------------------------------------------------|-----------|
| 4.1 | Gradio UI responds | `curl -s -o /dev/null -w "%{http_code}" http://localhost:7860` | HTTP 200 | 200 | PASS |
| 4.2 | FHIR MCP responds | `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/mcp` | HTTP 405 or 406 | 406 | PASS |
| 4.3 | Triage MCP responds | `curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/mcp` | HTTP 405 or 406 | 406 | PASS |
| 4.4 | CR MCP responds | `curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/mcp` | HTTP 405 or 406 | 406 | PASS |
| 4.5 | IRIS FHIR API responds| `curl -s -o /dev/null -w "%{http_code}" -u _SYSTEM:SYS -H "Accept: application/fhir+json" http://localhost:32783/fhir/r4/metadata` | HTTP 200 | 200 (CapabilityStatement returned) | PASS |
| 4.6 | Voice Bridge health | `curl -s http://localhost:8003/health` | `{"status":"ok","service":"triageaide-voice-bridge"}` | `{"status":"ok","service":"triageaide-voice-bridge"}` | PASS |
| 4.7 | 4 test patients exist | `curl -s -u _SYSTEM:SYS -H "Accept: application/fhir+json" "http://localhost:32783/fhir/r4/Patient?_tag=triage-seed&_count=10"` | Bundle with `total: 4` | total: 4 (Ana Costa/2605, Joao Santos/2610, Maria Silva/2627, Roberto Lima/2642) | PASS |
| 4.8 | Verify Joao Santos | FHIR query for Joao's conditions, medications, observations | 5 conditions, 4 medications, elevated creatinine | 5 conditions (CHF, AFib, DM2, HTN, CKD stage 3), 4 meds (Warfarina 5mg, Metformina 1000mg, Enalapril 20mg, Furosemida 40mg), 5 observations (HbA1c 7.1%, INR 2.8, Creatinina 2.1 mg/dL, BNP 450 pg/mL, EF 35%) | PASS |
| 4.9 | Verify Ana Costa | FHIR query for Ana's conditions | Acute tonsillitis condition present | 1 condition (Amigdalite aguda = Acute tonsillitis), 2 observations | PASS |
| 4.10 | Verify Maria Silva | FHIR query for Maria's conditions | DM2 + HTN + Pneumonia, HbA1c 8.2% | 3 conditions (DM2, HTN, Pneumonia), 5 observations including HbA1c 8.2% | PASS |
| 4.11 | Verify Roberto Lima | FHIR query for Roberto's conditions | COPD + HTN + Gonarthrosis + Depression, SpO2 93% | 4 conditions (DPOC/COPD, HTN, Osteoartrite do joelho/Gonarthrosis, Depressao maior/Major depression), 3 observations including SpO2 93% | PASS |

## Phase 5 — Verify README "### Step 5 — Verify services are running" commands

Cross-check each curl command from the README's Step 5 section against actual behavior:

| # | README Claim | Test | Actual | Pass/Fail |
|---|-------------------------------------------------------------------|-----------------------|-----------------|-----------|
| 5.1 | `docker compose ps` shows both `Up` | Run and check | Both containers Up (fhir-template healthy, triage-app running) | PASS |
| 5.2 | Gradio returns 200 | Already tested in 4.1 | 200 | PASS |
| 5.3 | FHIR MCP returns 405 or 406 | Already tested in 4.2 | 406 | PASS |
| 5.4 | IRIS metadata returns 200 | Already tested in 4.5 | 200 | PASS |
| 5.5 | Voice Bridge health returns `{"status":"ok","service":"triageaide-voice-bridge"}` | Already tested in 4.6 | Exact match | PASS |
| 5.6 | Log lines match expected output (Port 8000/8001/8002 ready, Voice Bridge, Gradio) | Already verified in 3.4–3.6 | All present except "Running on local URL: http://0.0.0.0:7860" | PASS (with finding) |

## Phase 6 — Functional smoke test (optional, requires OpenAI key)

| # | Action | Expected Result | Actual Result | Pass/Fail |
|---|---------------------------------------------------------------|--------------------------------------|--------------------------------------|-----------|
| 6.1 | Open http://localhost:7860, type "Hi, I'm Joao Santos..." | Agent responds with clinical context from FHIR | Gradio serves HTML correctly; agent interaction requires browser (manual test) | N/A (manual) |
| 6.2 | Trace panel shows 5-step workflow | Steps appear in real time | Requires browser (manual test) | N/A (manual) |

---

## Findings (README discrepancies)

| # | Location | Issue | Severity | Suggested Fix |
|---|----------|-------|----------|---------------|
| F1 | README line 202 | Image names are wrong: says `fhir-template` (IRIS) and `triage-app` (Python) — those are **container** names. Actual **image** names are `triageaide-iris` and `triageaide-triage` | Low | Change to: "two images built — `triageaide-iris` (IRIS) and `triageaide-triage` (Python)" |
| F2 | README lines 196–208 | Step-by-Step section still has separate "Step 3 — Build" (`docker compose build --no-cache`) and "Step 4 — Start" (`docker compose up -d`), but Quick Start "### 3" uses a single `docker compose up -d` that builds+starts | Low | Consider merging Steps 3+4 to match Quick Start, or keep as-is and note that `docker compose up -d` also works (builds if needed) |
| F3 | README line 262 | Log sample says "Running on local URL: http://0.0.0.0:7860" but Gradio does not emit this line when started via `exec` in the Docker entrypoint | Low | Remove "Running on local URL: http://0.0.0.0:7860" from the expected log output, or note it's optional |
| F4 | README line 62 | Ana Costa described as "Healthy patient, 0 red flags, routine priority" — she actually has 1 condition (acute tonsillitis) | Medium | Change to "Mild condition, 0 red flags, routine priority" or similar |

## Key risk areas

- `.env` must have a **real** `OPENAI_API_KEY` — containers start fine without it but Gradio/agent will fail at runtime
- Port conflicts on 32783, 7860, 8000–8003
- IRIS first boot can take 60–120s; triage container must wait successfully
- First build is slow (~3–8 min for IRIS image) due to large base image download
- FHIR data endpoints require Basic Auth (`-u _SYSTEM:SYS`) — the `/metadata` endpoint works without auth but `/Patient`, `/Observation`, etc. return 401 without credentials
