## Pre-Consultation Triage Agent

**Goal:** prepare the consultation *before* the patient speaks with the physician.

### How it works

1. **FHIR Query First** — The agent queries the patient's history on the FHIR Server (InterSystems IRIS for Health) BEFORE starting the conversation
2. **Contextual Triage** — With history in hand, generates intelligent and personalized questions (not generic)
3. **Conversation with the Patient** — Collects symptoms, recent history, and warning signs via chat
4. **Clinical Reasoning** — Crosses FHIR history + new symptoms to assess risk and priority
5. **Bidirectional FHIR Update** — Creates new FHIR resources on the server (Observation, Encounter, Flag, Task, QuestionnaireResponse)

### Key Phrase

> "The agent first retrieves patient history from a FHIR server, builds contextual clinical understanding, and performs an adaptive pre-consultation triage that enriches and updates the longitudinal patient record."

### Tech Stack

| Component | Technology |
|---|---|
| FHIR Server | InterSystems IRIS for Health Community Edition |
| MCP Servers | FastMCP (streamable-http) — 3 servers, 21 tools |
| Agent | LangChain + langchain-mcp-adapters + OpenAI gpt-4o-mini |
| Observability | LangSmith tracing (optional) |
| UI | Gradio ChatInterface with trace panel |
| Deploy | Docker Compose (2 services: iris + triage) |

### Architecture

```
FHIR Server (IRIS for Health)               ← iris container
|
+-- fhir_server.py (MCP :8000) — 12 FHIR CRUD tools
|   search_patients, get_patient, get_patient_conditions, get_patient_medications,
|   get_patient_observations, get_patient_allergies, get_patient_encounters,
|   create_observation, create_condition, create_questionnaire_response,
|   create_encounter, create_flag_and_task
|
+-- triage_server.py (MCP :8001) — 5 contextual triage tools
|   build_contextual_questions, get_next_triage_question,
|   get_all_triage_topics, parse_symptoms,
|   check_red_flags, build_questionnaire_response_data
|
+-- clinical_reasoning_server.py (MCP :8002) — 4 clinical reasoning tools
|   assess_clinical_risk, suggest_priority,
|   generate_clinical_summary, identify_follow_up_tasks
|
+-- LangChain Agent (agent.py / cli.py / app.py)
    system_prompt with 5 mandatory steps
    responds in English
```

### FHIR Resources Used

**Read (patient history):**
- Patient — demographics
- Condition — diagnoses
- MedicationRequest — current medications
- Observation — lab results and vital signs
- AllergyIntolerance — allergies
- Encounter — previous encounters

**Write (pre-consultation triage):**
- Observation — reported new symptoms
- QuestionnaireResponse — structured triage
- Encounter — prepared pre-consultation encounter
- Flag — clinical alerts (red flags)
- Task — follow-up tasks for the physician
- Condition — new conditions identified (if applicable)

### Test Patients

| Patient | Age | Scenario | Expected Priority |
|---|---|---|---|
| Maria Silva | 58, F | DM2 + uncontrolled Hypertension | Urgent |
| Joao Santos | 72, M | Polypharmacy + HF + AF | Urgent/Emergency |
| Ana Costa | 28, F | No active conditions | Routine |
| Roberto Lima | 65, M | COPD + SpO2 93% + red flags | Emergency |

### Result

The physician receives:

- automatic clinical summary with history + new symptoms
- suggested care priority (routine/urgent/emergency)
- red flag alerts (Flag resource)
- follow-up tasks (Task resource)
- QuestionnaireResponse with all structured triage

All recorded as FHIR resources in the patient record — FHIR becomes a **living clinical memory**.

### Differentiator for the Contest

The agent is NOT a generic chatbot that creates FHIR from scratch. It is an **interoperable AI Agent that reasons over existing clinical data**:

1. **FHIR-First**: queries history BEFORE interacting with the patient
2. **Contextual Triage**: intelligent questions based on real clinical history
3. **Bidirectional**: reads from AND writes to the FHIR Server
4. **MCP Architecture**: 3 specialized servers with 21 tools
5. **Longitudinal**: understands care continuity (e.g., "last visit 8 months ago")
6. **Observable**: LangSmith tracing + Gradio trace panel for agent inspection

### Interaction

- **Web UI**: Gradio ChatInterface at http://localhost:7860 (with trace panel)
- **CLI**: Interactive loop via `python cli.py`
- **Language**: English
- **Future**: Voice interaction (planned)
