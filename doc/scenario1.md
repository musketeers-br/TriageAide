# Refined Scenario — Pre-Consultation Triage Agent (FHIR-First)

## Core Idea

The agent does NOT start by asking everything from scratch.

It first:

- queries the **FHIR Server**
- understands the patient's history
- then conducts personalized intelligent triage

This demonstrates:

- real interoperability
- correct FHIR usage
- contextual intelligence of the agent

---

# New Scenario Flow

## Patient

Maria Silva — 58 years old
Appointment scheduled for tomorrow.

---

## Step 1 — AI Agent queries FHIR (BEFORE the conversation)

The agent accesses the **InterSystems IRIS for Health FHIR Server**.

Automatically retrieves:

### FHIR Resources Retrieved

- `Patient`
- `Condition`
- `MedicationRequest`
- `Observation`
- `AllergyIntolerance`
- `Encounter` (previous)

Example found:

- Type 2 Diabetes
- Hypertension
- Elevated HbA1c
- Metformin use
- Last visit 8 months ago

---

## The Important Insight

Now the agent **already knows the patient**.

It doesn't ask generic questions.

It asks intelligent clinical questions.

---

## Step 2 — Contextual Intelligent Triage

Instead of:

> "Do you have any diseases?"

The agent asks:

- "Maria, I noticed you have diabetes. Is your sugar under control?"
- "Have you had shortness of breath recently?"
- "Have you changed any medication?"

This demonstrates:

> **AI Agent operating ON FHIR**, not just using AI.

---

## Step 3 — FHIR Update (Bidirectional)

After the conversation:

The agent **doesn't create everything from scratch**.

It:

- complements existing history
- adds new observations

### Updated Resources

- `Observation` → recent fatigue
- `QuestionnaireResponse` → triage
- `Encounter` → prepared for consultation
- `Flag` → clinical alert
- `Task` → follow-up task

FHIR becomes a **living clinical memory**.

---

## Step 4 — Clinical Risk Reasoning

The agent crosses:

FHIR history + new symptoms

```
Diabetes + recent dyspnea + lack of follow-up
→ elevated cardiovascular risk
```

Creates:

- `Flag`
- `Task`
- high care priority

---

## Step 5 — Physician opens the patient record

The physician sees:

- already consolidated history
- new symptoms highlighted
- automatic clinical summary
- suggested priority

---

# Correct Architecture for the Contest

```
FHIR Server (IRIS for Health)               ← iris container
|
+-- fhir_server.py (MCP :8000) — 12 FHIR CRUD tools
+-- triage_server.py (MCP :8001) — 5 contextual triage tools
+-- clinical_reasoning_server.py (MCP :8002) — 4 clinical reasoning tools
|
+-- LangChain Agent (agent.py / cli.py / app.py)
    system_prompt with 5 mandatory steps
    responds in English
|
+-- entrypoint.sh — container entrypoint (waits for FHIR, loads seed, starts MCP + Gradio)
```

Two independent Docker services on a shared `fhir-net` bridge network:
- **iris** — IRIS for Health FHIR server
- **triage** — Python app (MCP servers + agent + Gradio UI with trace panel)

---

# Why This Version is Much Better

You go from:

- chatbot that generates FHIR

to:

- **Interoperable AI Agent that reasons over existing clinical data**

This is exactly the future that InterSystems promotes.

---

# Perfect Submission Phrase

Use something like:

> "The agent first retrieves patient history from a FHIR server, builds contextual clinical understanding, and performs an adaptive pre-consultation triage that enriches and updates the longitudinal patient record."

A judge reads this → immediately understands technical maturity.

---

# Upgrade That Almost Nobody Will Make (But You Should)

Add:

## Longitudinal Patient Understanding

The agent shows:

> "Last visit 8 months ago — follow-up overdue."

This demonstrates:

- care continuity
- real clinical value
- advanced FHIR timeline usage
