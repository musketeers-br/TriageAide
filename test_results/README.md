# Dialogue Quality Test Results

## Test Description

Automated multi-turn dialogue quality tests for the FHIR-First Pre-Consultation Triage AI Agent. Each test simulates a patient conversation and validates:

1. **One question per turn** — Agent must ask at most 1 question per response (turn 1 excluded as greeting)
2. **No repeated questions** — Agent must not ask the same question twice
3. **FHIR context usage** — Agent must reference patient data from the FHIR server in responses
4. **Natural Portuguese conversation** — Responses in Brazilian Portuguese

## Test Configuration

| Parameter | Value |
|---|---|
| **Date** | 2026-05-22 |
| **LLM Model** | OpenAI gpt-4o-mini |
| **Agent Framework** | LangChain `create_agent` with system_prompt |
| **MCP Transport** | streamable-http (FastMCP) |
| **MCP Servers** | fhir_server (:8000), triage_server (:8001), clinical_reasoning_server (:8002) |
| **FHIR Server** | InterSystems IRIS for Health (JsonAdvSql strategy) |
| **Session State** | Full message history including ToolMessages preserved across turns |
| **Language** | Brazilian Portuguese |

## Patients Tested

| Patient | File | Complexity | Active Conditions | Turns |
|---|---|---|---|---|
| Maria Silva | `test_dialogue_maria_silva.py` | Moderate | DM2, hypertension, heart failure | 6 |
| Joao Santos | `test_dialogue_joao_santos.py` | High | Heart failure, atrial fibrillation, DM2, hypertension, CKD3 | 10 |
| Ana Costa | `test_dialogue_ana_costa.py` | Low | None (resolved tonsillitis) | 9 |
| Roberto Lima | `test_dialogue_roberto_lima.py` | Moderate-High | COPD, hypertension, knee OA, major depression | 11 |

## How to Run

```bash
# Inside the Docker container
docker compose exec iris bash
cd /home/irisowner/irisdev/python/triage
export FHIR_BASE_URL=http://localhost:52773/fhir/r4

# Run individual tests
python3 test_dialogue_maria_silva.py
python3 test_dialogue_joao_santos.py
python3 test_dialogue_ana_costa.py
python3 test_dialogue_roberto_lima.py

# Results are saved to /home/irisowner/irisdev/test_results/ (mounted as test_results/ on host)
```

## Result Files

| File | Patient |
|---|---|
| `test_dialogue_maria_silva_results.json` | Maria Silva |
| `test_dialogue_joao_santos_results.json` | Joao Santos |
| `test_dialogue_ana_costa_results.json` | Ana Costa |
| `test_dialogue_roberto_lima_results.json` | Roberto Lima |

Each JSON result file contains:

- `patient`: Patient name
- `violations`: List of rule violations (empty = pass)
- `turns`: Per-turn details (user message, agent response, question count)
- `total_questions`: Total questions asked by agent
- `unique_questions`: Number of unique questions
- `has_fhir_context`: Boolean — whether agent referenced FHIR data

## Validation Criteria

| Rule | Threshold |
|---|---|
| Questions per turn (turn >= 2) | <= 1 |
| Repeated questions | 0 |
| FHIR context usage | Must be true |
| Unique question ratio | 1.0 (no duplicates) |

## Test Results — 2026-05-22

| Patient | Violations | 1-Q/Turn | FHIR Context | Unique Q | Status |
|---|---|---|---|---|---|
| Maria Silva | 0 | 6/6 | ✅ | 6/6 | **PASS** |
| Joao Santos | 0 | 10/10 | ✅ | 10/10 | **PASS** |
| Ana Costa | 0 | 8/8 | ✅ | 4/4 | **PASS** |
| Roberto Lima | 1 (2Q turn 4) | 10/11 | ✅ | 11/11 | **FAIL** |

### Summary

- **3/4 tests PASS** with zero violations
- **1/4 tests FAIL** — Roberto Lima: agent asked 2 questions in turn 4 (LLM split one question across two sentences ending with "?")
- All tests show FHIR context usage ✅
- No repeated questions across any test ✅
- Ana Costa test: agent sometimes jumps to clinical summary too early and had a `create_questionnaire_response` 400 error, but no dialogue quality violations

### Bugs Found During Testing

1. **`assess_clinical_risk` type validation error** (FIXED): `medications` parameter was `str` but LLM passed `[]` (list). Pydantic/FastMCP rejected it. Fixed by changing parameter types to `list` for all clinical reasoning tools (`conditions`, `new_symptoms`, `observations`, `medications`, `risk_assessment`, `patient_data`, `triage_data`, `risk_data`, `gaps_in_care`).
2. **`check_red_flags` and `build_questionnaire_response_data` same issue** (FIXED): Changed `str` params to `list`/`dict` types in triage_server.py.
3. **`create_questionnaire_response` 400 error** (NOT FIXED): The FHIR server rejects some QuestionnaireResponse payloads. Needs investigation of the payload structure.
4. **Ana Costa: agent confuses BMI 22 as "obesity"** (LLM reasoning issue): The agent misread normal BMI as obesity in the clinical summary.
