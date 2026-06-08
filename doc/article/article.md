_An AI agent reads the FHIR patient record before the consultation, asks the right questions based on what it already knows, detects critical red flags, and writes its findings back — so the physician arrives prepared._

---

## Healthcare Pain Points Addressed

Before a patient walks into a consultation room, a critical failure has already occurred: **nobody read their medical history.** The physician has 15 minutes. The patient repeats their conditions, medications, and allergies for the third time that year. Red flags — like bleeding on warfarin, chest pain with heart failure, suicidal ideation with depression etc — go unasked until it's too late, or not at all.

This isn't a technology gap. The data exists. It lives in repositories spread across different systems, holding longitudinal patient records with conditions, medications, lab results, allergies, and encounter history. The gap is **intelligence at the point of care** — an agent that reads the record _before_ the visit, asks the right questions based on what it already knows, and writes its findings back so the physician arrives prepared.

In the technological example app **TriageAide** we use scenario as motivation to explorer how to use InterSystems IRIS FHIR Server, Model Context Protocol (MCP), and Generative AI together. The app is an AI agent designed to streamline patient intake and clinical handoffs. 

It delivers:

* **Context-Aware Triage:** Conducts structured patient interviews driven by valuable existing health history (leveraging `Encounter`, `Condition`, and `Observation` FHIR resources).
* **Seamless Storage:** Saves patient responses directly as `QuestionnaireResponse` resources within the InterSystems IRIS FHIR Server.
* **Clinical Handoff:** Generates a structured summary for clinicians featuring coded observations, priority flags, and actionable follow-up tasks.

## FHIR as Living Clinical Memory

If you are using InterSystems IRIS for Health, you are already one step ahead in solving this technology gap, thanks to its native support for the FHIR (Fast Healthcare Interoperability Resources) standard. This enables you to seamlessly normalize healthcare data from disparate sources into a centralized repository, leveraging a robust data model and a powerful query engine.

InterSystems IRIS for Health serves as the FHIR R4 server at the heart of TriageAide. Every patient's clinical history — `Condition`, `MedicationRequest`, `Observation`, `AllergyIntolerance`, `Encounter` — lives there as standard FHIR resources. This isn't a data lake the agent parses and forgets. It's the **longitudinal record**, and the agent's job is to reason over it, then enrich it.

What makes this different from a chatbot that generates FHIR resources from scratch? The agent **reads first**. It pulls chronic conditions, active medications etc — then _uses that context_ to drive intelligent triage. The FHIR server doesn't just store data. It becomes the context engine for clinical AI.

## Architecture

TriageAide separates concerns into three MCP (Model Context Protocol) servers, each running as an independent FastMCP service over streamable-http:

| MCP Server                  | Port  | Tools | Role                                                                      |
| --------------------------- | ----- | ----- | ------------------------------------------------------------------------- |
| **FHIRServer**              | :8000 | 12    | CRUD operations against IRIS FHIR R4                                      |
| **TriageServer**            | :8001 | 5     | Contextual question generation, symptom extraction, red flag detection    |
| **ClinicalReasoningServer** | :8002 | 1     | Comprehensive clinical assessment (risk + priority + summary + follow-up) |

A **LangChain agent** orchestrates these servers through 18 tools, following a five-step mandatory workflow: **FHIR Query → Contextual Triage → Red Flags Check → Clinical Reasoning → FHIR Update.** Under the hood, `langchain.agents.create_agent` builds a compiled LangGraph state graph with two nodes — `model` (LLM reasoning) and `tools` (all 18 MCP tools in a single ToolNode) — connected in a ReAct loop:

![LangGraph agent](https://raw.githubusercontent.com/musketeers-br/TriageAide/refs/heads/master/doc/article/mermaid_diagram_langgraph1.png)

The `model` node decides at each step: respond to the patient, or invoke a tool. When it chooses a tool, the `tools` node executes it and feeds the result back to `model`, which reasons again. This loop continues until the model produces a final response — the ReAct (Reason + Act) pattern that powers every step of the triage workflow.

The clinical workflow maps five domain steps onto this ReAct loop:

![Agent - full workflow](https://raw.githubusercontent.com/musketeers-br/TriageAide/refs/heads/master/doc/article/mermaid_diagram_langgraph2.png)

**InterSystems IRIS for Health** is the foundation — a transactional, SQL-accessible FHIR R4 repository using the `JsonAdvSql` interactions strategy. The agent queries via standard FHIR REST API (`GET /Condition?patient=2196`) and writes back clinical alerts (`POST /Flag`, `POST /Task`) to the same canonical record. No ETL, no sync — the AI reads from and writes to the same server, transforming FHIR from a data archive into a living clinical memory.

**MCP** decouples tool provision from consumption. Each server is independently deployable and replaceable — the FHIR server can serve any future agent (risk stratification, medication reconciliation, care gap detection) without re-implementing FHIR CRUD. The LangChain agent discovers all 18 tools at startup via `MultiServerMCPClient`. **MCP makes healthcare AI composable.**

**Generative AI** provides contextual reasoning over the full clinical picture — conditions, medications, labs, allergies. Unlike rules engines, the LLM handles synonym mapping ("bruising easily" → "easy bruising"), negation ("no chest pain" ≠ "chest pain"), and cross-reference logic (warfarin + bleeding = critical) that would require hundreds of hand-coded rules. A tool like `check_red_flags` adaptively flags critical risks — such as for a patient on warfarin — while returning zero alerts for patients without active medications.

**Python** glues the stack together: FastMCP for MCP servers, LangChain for agent orchestration, Gradio for the UI with trace panel, `requests` for FHIR API calls, OpenAI for LLM inference. Docker Compose packages IRIS and the triage app as two independent services, deployable with a single `docker compose up -d`.

**LangSmith** provides developer observability — persistent, searchable traces across sessions with token counts, latencies, and cost tracking. When `LANGSMITH_TRACING=true` is set, every LLM call and tool invocation is automatically captured. Optional, but essential for production audit trails.

![LangSmith trace — Joao Santos triage showing tool calls and LLM reasoning](https://raw.githubusercontent.com/musketeers-br/TriageAide/271a5edd32f2c7f5cc5ff0d761a610c99482273f/doc/article/screenshot_langsmith_Joao_trace.png)

![LangSmith project dashboard — run history and cost tracking](https://raw.githubusercontent.com/musketeers-br/TriageAide/271a5edd32f2c7f5cc5ff0d761a610c99482273f/doc/article/screenshot_langsmith_dashboard.png)

The MCP architecture matters. Each server is independently deployable, testable, and replaceable. The FHIR server can serve any agent, not just this triage agent. The clinical reasoning server could power a different workflow — risk stratification, care gap detection—without touching the FHIR layer. **MCP decouples tool access from agent logic.**

The Gradio web UI features a developer-friendly chat interface and a real-time trace panel. By mapping LLM reasoning calls and tool execution details (arguments and results) directly to the workflow, it visualizes exactly how the agent behaves. We will use this tool for our upcoming walkthrough.

![TriageAide Gradio UI — chat on the left, agent trace on the right](https://raw.githubusercontent.com/musketeers-br/TriageAide/271a5edd32f2c7f5cc5ff0d761a610c99482273f/doc/article/screenshot_blank_ui.png)

### FHIRServer: The Agentic AI Foundation

The FHIRServer MCP is where InterSystems IRIS for Health meets the new age of Agentic AI. It exposes 12 tools — 7 for querying the FHIR record, 5 for writing back — giving any AI agent full bidirectional access to the patient's clinical data through standard FHIR R4 REST API calls:

| MCP Tool                        | FHIR Interaction | REST Endpoint                 | Key Parameters                             |
| ------------------------------- | ---------------- | ----------------------------- | ------------------------------------------ |
| `search_patients`               | search-type      | `GET /Patient`                | `name`, `family`, `given`, `_count`        |
| `get_patient`                   | read             | `GET /Patient/{id}`           | —                                          |
| `get_patient_conditions`        | search-type      | `GET /Condition`              | `patient`, `_count`                        |
| `get_patient_medications`       | search-type      | `GET /MedicationRequest`      | `patient`, `_count`                        |
| `get_patient_observations`      | search-type      | `GET /Observation`            | `patient`, `_sort=-date`, `_count`, `code` |
| `get_patient_allergies`         | search-type      | `GET /AllergyIntolerance`     | `patient`, `_count`                        |
| `get_patient_encounters`        | search-type      | `GET /Encounter`              | `patient`, `_sort=-date`, `_count`         |
| `create_flag_and_task`          | create (×2)      | `POST /Flag` + `POST /Task`   | —                                          |
| `create_questionnaire_response` | create           | `POST /QuestionnaireResponse` | —                                          |
| `create_encounter`              | create           | `POST /Encounter`             | —                                          |
| `create_observation`            | create           | `POST /Observation`           | —                                          |
| `create_condition`              | create           | `POST /Condition`             | —                                          |

This allows a read-then-write pattern ehich makes FHIR a **living clinical memory** for AI agents — the agent reads conditions, medications, and labs to build context; reasons over them with LLM-powered triage tools; then writes Flag, Task, Observation, QuestionnaireResponse, and Encounter resources back to the same canonical record. No ETL, no sync — the AI reads from and writes to the same InterSystems IRIS FHIR Server, and every resource it creates is immediately available to any FHIR-compliant system.

## Walkthrough: João Santos, 72 Years Old

_Reproducibility note: All walkthrough traces below use LLM cache (_`LLM_CACHE=sqlite`_). Pre-populated cache files ship at&#x20;_`python/triage/cache/`_, so running the same inputs produces identical results — zero API cost, zero variance._

Joao Santos is a test patient with a complex cardiovascular profile:

* **5 active conditions:** Chronic Heart Failure (I50), Atrial Fibrillation (I48), Type 2 Diabetes (E11), Hypertension (I10), CKD Stage 3 (N18.3)
* **4 active medications:** Warfarin 5mg, Metformin 1000mg, Enalapril 20mg, Furosemide 40mg
* **Key labs:** HbA1c 7.1%, INR 2.8, Creatinine 2.1 mg/dL (HIGH), BNP 450 pg/mL (HIGH), Ejection Fraction 35% (LOW)
* **Allergy:** Aspirin (severe asthma exacerbation)
* **Last visit:** Cardiology follow-up, January 2026

Joao opens the Gradio chat and types:

> **"Hi, I'm Joao Santos, I've been having trouble breathing at night and my legs are swollen"**

### STEP 1 — FHIR Query (FHIRServer)

Before responding, the agent queries the FHIR server. You can check out it on the trace panel, like this:

```objectscript
🧠 LLM #1 → search_patients

→ search_patients(name="Joao Santos")
← search_patients · 1 patient(s) found (0.1s)
Result: {"total": 1, "patients": [{"id": "2196", "name": "Joao Santos",
"gender": "male", "birthDate": "1954-11-20"}]}

🧠 LLM #2 → get_patient, get_patient_conditions, get_patient_medications,
get_patient_observations, get_patient_allergies, get_patient_encounters

→ get_patient_conditions(patient_id=2196)
← get_patient_conditions · 5 conditions retrieved (0.4s)
Result: [{"display": "Chronic heart failure", "icd10": "I50", "status": "active"},
{"display": "Atrial fibrillation", "icd10": "I48", "status": "active"},
{"display": "Type 2 diabetes", "icd10": "E11", "status": "active"},
{"display": "Hypertension", "icd10": "I10", "status": "active"},
{"display": "CKD stage 3", "icd10": "N18.3", "status": "active"}]

→ get_patient_medications(patient_id=2196)
← get_patient_medications · 4 medications retrieved (0.3s)
Result: [{"medication": "Warfarin 5mg", "status": "active"},
{"medication": "Metformin 1000mg", "status": "active"},
{"medication": "Enalapril 20mg", "status": "active"},
{"medication": "Furosemide 40mg", "status": "active"}]

→ get_patient_observations(patient_id=2196)
← get_patient_observations · 5 observations retrieved (0.4s)
Result: [{"display": "HbA1c", "value": 7.1},
{"display": "INR", "value": 2.8},
{"display": "Creatinine", "value": 2.1, "interpretation": "H"},
{"display": "BNP", "value": 450, "interpretation": "H"},
{"display": "Ejection fraction", "value": 35, "interpretation": "L"}]

→ get_patient_allergies(patient_id=2196)
← get_patient_allergies · 1 allergies retrieved (0.4s)
Result: [{"substance": "Aspirin", "criticality": "high",
"reactions": [{"manifestation": "Asthma exacerbation", "severity": "severe"}]}]
```

Seven FHIR calls, all against the InterSystems IRIS FHIR server. The agent now knows Joao's full clinical picture — **before saying a single word to the patient**. This is the FHIR-First principle in action.

![Joao Santos — STEP 1 (FHIR Query) and STEP 2 (Triage Question) in the trace panel](https://raw.githubusercontent.com/musketeers-br/TriageAide/271a5edd32f2c7f5cc5ff0d761a610c99482273f/doc/article/screenshot_joao_step1_2.png)

### STEP 2 — Contextual Triage

Now the agent uses the **TriageServer MCP** to generate a context-aware question — not a generic opener:

```objectscript
🧠 LLM #3 → get_next_triage_question

→ get_next_triage_question(
patient_context={full FHIR history},
covered_topics=[],
patient_initial_message="Hi, I'm Joao Santos, I've been having trouble
breathing at night and my legs are swollen")
← get_next_triage_question · 1 question (3 remaining) (1.3s)
Result: "I'm sorry to hear that you're having trouble breathing at night.
Have you noticed any chest pain or tightness along with that?"
```

Notice what happened: the `patient_initial_message` parameter passes Joao's own words. The LLM-powered triage tool sees "trouble breathing at night and swollen legs" and **skips the generic opener**. It doesn't ask "How are you feeling today?" It goes straight to red-flag screening for a heart failure patient: chest pain.

The agent asks Joao:

> **"I'm sorry to hear that you're having trouble breathing at night. Have you noticed any chest pain or tightness along with that?"**

Joao responds:

> **"Yes, I've been noticing some bruising easily and my gums bleed when I brush my teeth"**

The agent processes this through two tools in sequence:

```objectscript
→ analyze_patient_response(
patient_response="Yes, I've been noticing some bruising easily and
my gums bleed when I brush my teeth",
patient_context={full FHIR history})
← analyze_patient_response · 2 symptom(s), severity=moderate (2.7s)
Result: {"identified_symptoms": [
{"symptom": "easy bruising", "category": "general", "severity": "moderate"},
{"symptom": "gum bleeding", "category": "general", "severity": "moderate"}],
"overall_severity": "moderate"}
```

The symptom extractor—also LLM-powered—correctly identifies "easy bruising" and "gum bleeding" as distinct symptoms with moderate severity. It handles synonyms ("bruising easily" → "easy bruising") and negation (if Joao had said "no chest pain," it would be marked absent).

### STEP 3 — Red Flags Check

Then comes the critical moment. The agent runs `check_red_flags` on the **ClinicalReasoningServer**, cross-referencing the new symptoms with the FHIR-retrieved conditions and medications:

```objectscript
→ check_red_flags(
symptoms=[{"symptom":"easy bruising"}, {"symptom":"gum bleeding"}],
conditions=[Chronic heart failure, Atrial fibrillation, Diabetes, Hypertension, CKD],
medications=[Warfarin 5mg, Metformin 1000mg, Enalapril 20mg, Furosemide 40mg])
← check_red_flags · 2 alert(s) ⚠️ CRITICAL (2.9s)
Result: {
"alerts": [
{"red_flag": "Bleeding symptoms with warfarin use",
  "symptom": "gum bleeding",
  "related_condition_or_medication": "Warfarin 5mg",
  "risk": "critical",
  "explanation": "The patient is experiencing gum bleeding while on warfarin,
  which significantly increases the risk of serious bleeding complications
  and requires immediate attention."},
  {"red_flag": "Bleeding symptoms with warfarin use",
  "symptom": "easy bruising",
  "related_condition_or_medication": "Warfarin 5mg",
  "risk": "elevated",
  "explanation": "Easy bruising in a patient taking warfarin indicates a
  potential issue with anticoagulation control and warrants
  urgent follow-up."}
],
"has_critical_red_flag": true,
"alert_count": 2
}
```

**The agent detected a critical red flag:** bleeding symptoms in a patient on warfarin. This is one of the most dangerous drug-symptom combinations in medicine — uncontrolled anticoagulation can lead to intracranial hemorrhage, GI bleeding, or death. The LLM-powered red flag checker caught it because it was given the full medication list from FHIR, not just the patient's stated symptoms.

The agent immediately warns Joao:

> **"I need to inform you that the symptoms you mentioned, like gum bleeding and easy bruising, are critical. You're currently taking warfarin, which can cause serious bleeding complications. It's very important that you seek immediate medical attention for this."**

![Red flag detected — warfarin + bleeding = CRITICAL, visible in the trace panel](https://raw.githubusercontent.com/musketeers-br/TriageAide/271a5edd32f2c7f5cc5ff0d761a610c99482273f/doc/article/screenshot_Joao_red_flags.png)

### STEP 3 Continued — More Symptoms

Joao continues:

> **"I've also been feeling dizzy when I stand up, and I'm more tired than usual"**

The same loop runs: `analyze_patient_response` extracts dizziness (neurological) and fatigue (general), then `check_red_flags` cross-references with his atrial fibrillation and heart failure:

```objectscript
← check_red_flags · 3 alert(s) (5.1s)
Result: {
"alerts": [
{"red_flag": "Dizziness with atrial fibrillation and hypertension",
"risk": "elevated",
"explanation": "Dizziness in the context of atrial fibrillation and
hypertension may indicate inadequate blood flow or potential
arrhythmia, necessitating urgent evaluation."},
{"red_flag": "Fatigue with heart failure and diabetes",
"risk": "elevated",
"explanation": "Fatigue in a patient with heart failure and diabetes
may suggest worsening heart function or poor glycemic control,
requiring prompt assessment."},
{"red_flag": "Dizziness with warfarin use",
"risk": "elevated",
"explanation": "Dizziness in a patient on warfarin may indicate
bleeding or anemia, warranting further investigation."}
],
"has_critical_red_flag": false
}
```

Three elevated-risk alerts. Dizziness + atrial fibrillation = possible cerebral hypoperfusion. Fatigue + heart failure = possible decompensation. Dizziness + warfarin = possible bleeding/anemia. The agent warns Joao about these in context.

### STEP 4 — Clinical Reasoning

Once triage questions are exhausted, the agent calls a single LLM-powered tool that produces a comprehensive clinical assessment:

```objectscript
→ clinical_assessment(
patient_context={full FHIR history},
triage_data={all extracted symptoms, red flags, Q&A})
```

This one call produces: **risk assessment** (score, level, factors with justification), **priority suggestion** (routine/urgent/emergency), **clinical summary** for the physician, and **follow-up tasks**. For Joao, the result is high/critical risk with urgent/emergency priority.

### STEP 5 — FHIR Update (Bidirectional)

The agent doesn't just produce a report. It writes back to the same FHIR server it read from:

* `QuestionnaireResponse` — structured triage Q\&A, preserved in the patient record
* `Encounter` — pre-consultation encounter with the assigned priority
* `Observation` — new symptoms recorded as clinical observations
* `Flag` — clinical alert for the warfarin-bleeding red flag, visible in the patient chart
* `Task` — follow-up task for the physician (e.g., "Check INR urgently")

The physician opening Joao's chart sees: a new `Flag` resource warning about warfarin + bleeding, a `Task` requesting urgent INR review, a `QuestionnaireResponse` with the full triage conversation, and an `Encounter` marked urgent. **FHIR becomes a living clinical memory**, enriched by AI, readable by any FHIR-compliant system.

![Full triage completed — all five steps visible in the trace panel](https://raw.githubusercontent.com/musketeers-br/TriageAide/271a5edd32f2c7f5cc5ff0d761a610c99482273f/doc/article/screenshot_Joao_full_triage.png)

### What Was Written Back — FHIR Resources

Querying the FHIR server after the triage session confirms all five resource types were created for Joao Santos. You can reproduce these queries against a running instance:

**Flag — Warfarin + Bleeding Alert (critical)**

```bash
curl -s -u '_SYSTEM:SYS' -H 'Accept: application/fhir+json' \
  'http://localhost:32783/fhir/r4/Flag?patient=2196'
```

```json
{
  "resourceType": "Flag",
  "id": "2242",
  "status": "active",
  "code": {
    "coding": [{
      "system": "http://terminology.hl7.org/CodeSystem/flag-category",
      "code": "clinical",
      "display": "Clinical"
    }],
    "text": "CRITICAL: Bleeding symptoms in patient on Warfarin 5mg — gum bleeding and easy bruising indicate potential anticoagulation complication requiring immediate attention"
  },
  "subject": { "reference": "Patient/2196", "display": "Joao Santos" }
}
```

**Task — Urgent INR Review**

```bash
curl -s -u '_SYSTEM:SYS' -H 'Accept: application/fhir+json' \
  'http://localhost:32783/fhir/r4/Task?patient=2196'
```

```json
{
  "resourceType": "Task",
  "id": "2243",
  "status": "requested",
  "intent": "order",
  "priority": "urgent",
  "description": "Check INR urgently — patient on warfarin reporting gum bleeding and easy bruising, indicating potential anticoagulation complication",
  "for": { "reference": "Patient/2196", "display": "Joao Santos" }
}
```

**QuestionnaireResponse — Structured Triage Q\&A**

```bash
curl -s -u '_SYSTEM:SYS' -H 'Accept: application/fhir+json' \
  'http://localhost:32783/fhir/r4/QuestionnaireResponse?patient=2196'
```

```json
{
  "resourceType": "QuestionnaireResponse",
  "id": "2244",
  "status": "completed",
  "subject": { "reference": "Patient/2196", "display": "Joao Santos" },
  "authored": "2026-06-07T23:10:00+00:00",
  "item": [
    {
      "linkId": "q1",
      "text": "Have you noticed any chest pain or tightness along with your breathing difficulties?",
      "answer": [{ "valueString": "The breathing gets worse when I lie down, and I have been using more pillows to sleep" }]
    },
    {
      "linkId": "q2",
      "text": "Have you noticed any unusual bleeding or bruising?",
      "answer": [{ "valueString": "I have noticed some easy bruising and my gums bleed when I brush my teeth" }]
    },
    {
      "linkId": "q3",
      "text": "Have you been feeling dizzy or more tired than usual?",
      "answer": [{ "valueString": "I have been feeling dizzy when I stand up quickly, and more tired than usual" }]
    }
  ]
}
```

**Observation — New Symptom: Gum Bleeding**

```bash
curl -s -u '_SYSTEM:SYS' -H 'Accept: application/fhir+json' \
  'http://localhost:32783/fhir/r4/Observation?patient=2196'
```

```json
{
  "resourceType": "Observation",
  "id": "2245",
  "status": "final",
  "category": [{ "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "exam" }] }],
  "code": {
    "coding": [{ "system": "http://snomed.info/sct", "code": "131148009", "display": "Bleeding gum" }],
    "text": "Gum bleeding"
  },
  "subject": { "reference": "Patient/2196", "display": "Joao Santos" },
  "effectiveDateTime": "2026-06-07T23:10:00+00:00",
  "valueString": "Patient reports gum bleeding when brushing teeth, consistent with warfarin anticoagulation complication"
}
```

**Encounter — Pre-Consultation Triage (Emergency Priority)**

```bash
curl -s -u '_SYSTEM:SYS' -H 'Accept: application/fhir+json' \
  'http://localhost:32783/fhir/r4/Encounter?patient=2196'
```

```json
{
  "resourceType": "Encounter",
  "id": "2247",
  "status": "planned",
  "class": { "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory" },
  "priority": { "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority", "code": "EM" }] },
  "type": [{ "text": "AI Pre-Consultation Triage — cardiovascular symptoms with anticoagulation concern" }],
  "subject": { "reference": "Patient/2196", "display": "Joao Santos" }
}
```

Every resource references `Patient/2196`. The `Flag` is visible in the patient chart. The `Task` appears in the physician's task list. The `QuestionnaireResponse` preserves the full triage conversation. The `Observation` records the new symptom with a SNOMED CT code. The `Encounter` is tagged with emergency priority. All standard FHIR R4 — any compliant system can read them.

---

## The Contrast: Ana Costa, 28 Years Old

The same architecture, the same workflow—but a completely different patient.

Ana Costa has no active conditions (a resolved tonsillitis from 2024), no medications, no allergies, normal vitals (BMI 22, BP 110/70). She reports a sore throat and mild fever.

The trace panel shows the same STEP 1 FHIR queries — 0 medications, 0 allergies, 1 resolved condition. `check_red_flags` returns **0 alerts**. The clinical assessment produces low risk, routine priority. No `Flag` or `Task` resources are created. The system adapts entirely to the patient's clinical context.

![Ana Costa — routine triage, no red flags, low risk](https://raw.githubusercontent.com/musketeers-br/TriageAide/271a5edd32f2c7f5cc5ff0d761a610c99482273f/doc/article/screenshot_ana_costa_full.png)

This is the power of FHIR-First reasoning: the same agent asks different questions, checks different red flags, and produces different outputs — because the FHIR server provides different history for each patient.

---

## Conclusion

TriageAide demonstrates that FHIR-first AI agents can transform pre-consultation care — not by replacing clinical judgment, but by ensuring the right information reaches the right person at the right time. The agent reads the patient's longitudinal FHIR record, asks contextually relevant questions, detects red flags by cross-referencing symptoms with medications and conditions, and writes structured findings back as standard FHIR resources.

The architecture is composable by design. MCP separates tool access from agent logic, so the FHIR server can serve any future agent, and the clinical reasoning server can power any workflow. The bidirectional FHIR integration means the AI doesn't just consume data — it enriches the clinical record, making every subsequent interaction smarter.

The gap between available data and intelligent action at the point of care is real. With InterSystems IRIS for Health as the FHIR foundation and generative AI as the reasoning layer, that gap is closable — today.

---

### Footnote

_This article was developed with the assistance of Artificial Intelligence tools for drafting and language refinement. All technical validation and final review were performed by the author._