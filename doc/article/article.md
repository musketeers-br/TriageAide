# FHIR-First AI Triage: How InterSystems IRIS, MCP, and Generative AI Transform Pre-Consultation Care

## The Problem Nobody Sees

Before a patient walks into a consultation room, a critical failure has already occurred: **nobody read their medical history.** The physician has 15 minutes. The patient repeats their conditions, medications, and allergies for the third time that year. Red flags—bleeding on warfarin, chest pain with heart failure, suicidal ideation with depression—go unasked until it's too late, or not at all.

This isn't a technology gap. The data exists. It lives in FHIR repositories like InterSystems IRIS for Health, holding longitudinal patient records with conditions, medications, lab results, allergies, and encounter history. The gap is **intelligence at the point of care**—an agent that reads the record *before* the visit, asks the right questions based on what it already knows, and writes its findings back so the physician arrives prepared.

That's what TriageAide does.

## FHIR as Living Clinical Memory

InterSystems IRIS for Health serves as the FHIR R4 server at the heart of TriageAide. Every patient's clinical history—`Condition`, `MedicationRequest`, `Observation`, `AllergyIntolerance`, `Encounter`—lives there as standard FHIR resources. This isn't a data lake the agent parses and forgets. It's the **longitudinal record**, and the agent's job is to reason over it, then enrich it.

What makes this different from a chatbot that generates FHIR resources from scratch? The agent **reads first**. It pulls five chronic conditions, four active medications, an elevated creatinine, a low ejection fraction—then *uses that context* to drive intelligent triage. The FHIR server doesn't just store data. It becomes the context engine for clinical AI.

## Architecture: Three MCP Servers, One Agent

TriageAide separates concerns into three MCP (Model Context Protocol) servers, each running as an independent FastMCP service over streamable-http:

| MCP Server | Port | Tools | Role |
|---|---|---|---|
| **FHIRServer** | :8000 | 12 | CRUD operations against IRIS FHIR R4 |
| **TriageServer** | :8001 | 4 | Contextual question generation, symptom extraction, red flag detection |
| **ClinicalReasoningServer** | :8002 | 1 | Comprehensive clinical assessment (risk + priority + summary + follow-up) |

A LangChain agent (powered by OpenAI gpt-4o-mini) orchestrates these servers through 17 tools, following a four-step mandatory workflow: **FHIR Query → Contextual Triage → Clinical Assessment → FHIR Update.**

The MCP architecture matters. Each server is independently deployable, testable, and replaceable. The FHIR server can serve any agent, not just this triage agent. The clinical reasoning server could power a different workflow—risk stratification, care gap detection—without touching the FHIR layer. **MCP decouples tool access from agent logic.**

A Gradio web UI provides the patient-facing chat interface alongside a real-time **trace panel** that reveals every step the agent takes—every LLM reasoning call, every tool invocation with arguments and results, mapped to the workflow steps. This is what we'll walk through.

---

## Walkthrough: Joao Santos, 72 Years Old

Joao Santos is a test patient with a complex cardiovascular profile:

- **5 active conditions:** Chronic Heart Failure (I50), Atrial Fibrillation (I48), Type 2 Diabetes (E11), Hypertension (I10), CKD Stage 3 (N18.3)
- **4 active medications:** Warfarin 5mg, Metformin 1000mg, Enalapril 20mg, Furosemide 40mg
- **Key labs:** HbA1c 7.1%, INR 2.8, Creatinine 2.1 mg/dL (HIGH), BNP 450 pg/mL (HIGH), Ejection Fraction 35% (LOW)
- **Allergy:** Aspirin (severe asthma exacerbation)
- **Last visit:** Cardiology follow-up, January 2026

Joao opens the Gradio chat and types:

> **"Hi, I'm Joao Santos, I've been having trouble breathing at night and my legs are swollen"**

### STEP 1 — FHIR Query

The trace panel immediately lights up. The agent doesn't ask "How can I help you?"—it already knows why Joao is here. Before responding, it queries the FHIR server:

```
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

Seven FHIR calls, all against the InterSystems IRIS FHIR server, in under 2 seconds. The agent now knows Joao's full clinical picture—**before saying a single word to the patient**. This is the FHIR-First principle in action.

### STEP 2 — Contextual Triage

Now the agent uses the **TriageServer MCP** to generate a context-aware question—not a generic opener:

```
🧠 LLM #3 → get_next_triage_question

    → get_next_triage_question(
        patient_context={full FHIR history},
        covered_topics=[],
        patient_initial_message="Hi, I'm Joao Santos, I've been having trouble
                                 breathing at night and my legs are swollen")
    ← get_next_triage_question · 1 question (0 remaining) (1.3s)
      Result: "Have you noticed any chest pain or discomfort along
               with your breathing issues?"
```

Notice what happened: the `patient_initial_message` parameter passes Joao's own words. The LLM-powered triage tool sees "trouble breathing at night and swollen legs" and **skips the generic opener**. It doesn't ask "How are you feeling today?" It goes straight to red-flag screening for a heart failure patient: chest pain.

The agent asks Joao:

> **"I'm sorry to hear you're having trouble breathing at night. Have you noticed any chest pain or discomfort along with your breathing issues?"**

Joao responds:

> **"Yes, I've been noticing some bruising easily and my gums bleed when I brush my teeth"**

The agent processes this through two tools in sequence:

```
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

```
    → check_red_flags(
        symptoms=[{"symptom":"easy bruising"}, {"symptom":"gum bleeding"}],
        conditions=[Chronic heart failure, Atrial fibrillation, Diabetes, Hypertension, CKD],
        medications=[Warfarin 5mg, Metformin 1000mg, Enalapril 20mg, Furosemide 40mg])
    ← check_red_flags · 2 alert(s) ⚠️ CRITICAL (2.9s)
      Result: {
        "alerts": [
          {"red_flag": "Bleeding symptoms with anticoagulant use",
           "symptom": "gum bleeding",
           "related_condition_or_medication": "Warfarin 5mg",
           "risk": "critical",
           "explanation": "The patient is experiencing gum bleeding while on warfarin,
                          which poses a significant risk of serious bleeding complications
                          requiring immediate attention."},
          {"red_flag": "Bleeding symptoms with anticoagulant use",
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

**The agent detected a critical red flag:** bleeding symptoms in a patient on warfarin. This is one of the most dangerous drug-symptom combinations in medicine—uncontrolled anticoagulation can lead to intracranial hemorrhage, GI bleeding, or death. The LLM-powered red flag checker caught it because it was given the full medication list from FHIR, not just the patient's stated symptoms.

The agent immediately warns Joao:

> **"It's important I tell you about some serious concerns. You're experiencing gum bleeding and easy bruising while taking Warfarin. This represents a critical risk of serious complications that require immediate attention. Please seek urgent medical assistance to discuss these symptoms."**

### STEP 3 Continued — More Symptoms

Joao continues:

> **"I've also been feeling dizzy when I stand up, and I'm more tired than usual"**

The same loop runs: `analyze_patient_response` extracts dizziness (neurological) and fatigue (general), then `check_red_flags` cross-references with his atrial fibrillation and heart failure:

```
    ← check_red_flags · 2 alert(s) (4.7s)
      Result: {
        "alerts": [
          {"red_flag": "Dizziness with atrial fibrillation and hypertension",
           "risk": "elevated",
           "explanation": "Dizziness may indicate inadequate cerebral perfusion
                          or potential arrhythmia, warranting urgent follow-up."},
          {"red_flag": "Fatigue with heart failure and diabetes",
           "risk": "elevated",
           "explanation": "Fatigue could suggest worsening heart function
                          or poor glycemic control, necessitating further evaluation."}
        ],
        "has_critical_red_flag": false
      }
```

Two elevated-risk alerts. Dizziness + atrial fibrillation = possible cerebral hypoperfusion. Fatigue + heart failure = possible decompensation. The agent warns Joao about these in context.

### STEP 4 — Clinical Assessment

Once triage questions are exhausted, the agent calls a single LLM-powered tool that produces a comprehensive clinical assessment:

```
    → clinical_assessment(
        patient_context={full FHIR history},
        triage_data={all extracted symptoms, red flags, Q&A})
```

This one call produces: **risk assessment** (score, level, factors with justification), **priority suggestion** (routine/urgent/emergency), **clinical summary** for the physician, and **follow-up tasks**. For Joao, the result is high/critical risk with urgent/emergency priority.

### STEP 5 — FHIR Update (Bidirectional)

The agent doesn't just produce a report. It writes back to the same FHIR server it read from:

- **`QuestionnaireResponse`** — structured triage Q&A, preserved in the patient record
- **`Encounter`** — pre-consultation encounter with the assigned priority
- **`Observation`** — new symptoms recorded as clinical observations
- **`Flag`** — clinical alert for the warfarin-bleeding red flag, visible in the patient chart
- **`Task`** — follow-up task for the physician (e.g., "Check INR urgently")

The physician opening Joao's chart sees: a new `Flag` resource warning about warfarin + bleeding, a `Task` requesting urgent INR review, a `QuestionnaireResponse` with the full triage conversation, and an `Encounter` marked urgent. **FHIR becomes a living clinical memory**, enriched by AI, readable by any FHIR-compliant system.

---

## The Contrast: Ana Costa, 28 Years Old

The same architecture, the same workflow—but a completely different patient.

Ana Costa has no active conditions (a resolved tonsillitis from 2024), no medications, no allergies, normal vitals (BMI 22, BP 110/70). She reports a sore throat and mild fever.

The trace panel shows the same STEP 1 FHIR queries—0 medications, 0 allergies, 1 resolved condition. `check_red_flags` returns **0 alerts**. The clinical assessment produces low risk, routine priority. No `Flag` or `Task` resources are created. The system adapts entirely to the patient's clinical context.

This is the power of FHIR-First reasoning: the same agent asks different questions, checks different red flags, and produces different outputs—because the FHIR server provides different history for each patient.

---

## Why These Technologies Matter

### InterSystems IRIS for Health — The Foundation

IRIS isn't just a FHIR data store. It's a **transactional, SQL-accessible, standards-compliant FHIR repository** that supports the `JsonAdvSql` interactions strategy for performant queries. The agent queries it via standard FHIR REST API (`GET /Condition?patient=2196`), and the server returns structured, validated FHIR R4 resources. The same server accepts `POST /Flag` and `POST /Task` to write back clinical alerts. No ETL. No sync. The AI reads from and writes to the same canonical record.

This bidirectionality is what transforms FHIR from a **data archive** into a **living clinical memory**—one that gets richer with every agent interaction.

### MCP — Decoupled Tool Access

The Model Context Protocol (MCP) separates tool *provision* from tool *consumption*. The FHIR server runs on port 8000, the triage server on 8001, the clinical reasoning server on 8002. Each is an independent FastMCP service with streamable-http transport. The LangChain agent discovers all 17 tools at startup via `MultiServerMCPClient` and calls them as needed.

This matters because: any future agent—risk stratification, medication reconciliation, care gap detection—can consume the same FHIR MCP server without re-implementing FHIR CRUD. The triage logic is independent of the data layer. The clinical reasoning is independent of both. **MCP makes healthcare AI composable.**

### Generative AI — Contextual Reasoning Over Data

The agent isn't scripted. It doesn't follow a decision tree. When Joao Santos says "my gums bleed," the LLM-powered `check_red_flags` tool cross-references that with his warfarin prescription (retrieved from FHIR), identifies the drug-symptom interaction, and classifies it as critical. When Ana Costa says "sore throat," the same tool sees no active medications and returns 0 alerts.

This is generative AI doing what rules engines can't: **reasoning over the full clinical context**—conditions, medications, labs, allergies—to produce individualized assessments. The LLM handles synonym mapping ("bruising easily" → "easy bruising"), negation ("no chest pain" ≠ "chest pain"), and cross-reference logic (warfarin + bleeding = critical) that would require hundreds of hand-coded rules.

### Python — The Glue

The entire triage application runs on Python: FastMCP for MCP servers, LangChain for agent orchestration, Gradio for the UI with trace panel, `requests` for FHIR API calls, OpenAI for LLM inference. Python's ecosystem—particularly `langchain-mcp-adapters` for MCP tool integration—made it possible to build a production-grade multi-MCP agent in weeks, not months. Docker Compose packages IRIS and the triage app as two independent services, deployable with a single `docker compose up -d`.

---

## Reproducibility: Cache-Enabled Demos

TriageAide runs with `LLM_CACHE=sqlite`, meaning LLM calls and tool invocations are cached in SQLite databases. Once a scenario is executed (like the Joao Santos walkthrough above), subsequent runs with identical inputs produce **identical traces**—served from cache, no API calls, no cost, no variance.

This means the demo is **reproducible**: deploy the cache files alongside the Docker containers, and readers can follow the exact same trace panel flow described in this article. Same FHIR data, same questions, same red flags, same clinical assessment.

---

## What the Physician Sees

When the physician opens the patient record after the AI triage, they find:

- **A clinical summary** — conditions, medications, new symptoms, risk level, priority
- **Red flag alerts** — as `Flag` resources in the FHIR chart (warfarin + bleeding: critical)
- **Follow-up tasks** — as `Task` resources (e.g., "Check INR urgently," "Assess cardiac decompensation")
- **Structured triage** — as `QuestionnaireResponse`, the full Q&A preserved
- **Priority-tagged encounter** — the pre-consultation encounter marked urgent/emergency

The physician doesn't need to read the AI's reasoning. They need what FHIR already gives them: structured, interoperable, standards-compliant clinical resources. The AI just made sure they were there *before* the consultation started.

---

## Try It

```bash
git clone https://github.com/jrpereirajr/TriageAide.git
cd TriageAide
docker compose build --no-cache && docker compose up -d
# Open http://localhost:7860
# Type: "Hi, I'm Joao Santos, I've been having trouble breathing at night"
# Watch the trace panel
```

The FHIR server (InterSystems IRIS for Health) loads 4 test patients automatically. The Gradio UI shows the chat on the left and the agent trace on the right. Every tool call, every LLM decision, every FHIR resource created—visible in real time.
