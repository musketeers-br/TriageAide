# Priority Test Plan — Dynamic Agent Priority Sense Evaluation

**Goal:** Dynamically simulate 4 test patients interacting with the triage agent to evaluate whether it assigns correct care priorities.

**Method:** Turn-by-turn interaction — the tester (LLM or human) plays each patient, reads the agent's questions, and responds naturally as that patient would. No scripted/fixed responses.

**Last executed:** 2026-06-09

---

## Test Harness

A Python script `python/triage/test_priority.py` enables turn-by-turn agent interaction.

### Commands

```bash
# Start a new session with a patient
docker compose exec triage bash -c \
  'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py start "Ana Costa" "Hi, I am Ana Costa, I have been having a fever and feeling tired"'

# Reply to the agent's question (after reading its output)
docker compose exec triage bash -c \
  'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py reply "It started two days ago, just a low fever and body aches"'

# Check session status
docker compose exec triage bash -c \
  'cd /app && python3 test_priority.py status'

# Reset session (between patients)
docker compose exec triage bash -c \
  'cd /app && python3 test_priority.py reset'
```

### How the script works

- **`start <patient_name> <opening_message>`**
  Creates a new agent session, sends the opening message, prints the agent's response, saves state to `/tmp/triage_test_session.json`.

- **`reply <answer>`**
  Loads session, appends patient answer, invokes agent, prints response, saves updated state.

- **`status`**
  Shows current session info: patient name, turn count, priority/risk if determined.

- **`reset`**
  Clears session state (run between patients).

- Each invocation creates a fresh agent and replays the full message history from the session file.
- `LLM_CACHE=off` ensures fresh (non-cached) LLM responses every run.
- Auto-detects when the agent outputs the final clinical summary by parsing `**Priority:**` and `**Risk:**` lines.

---

## Patient Profiles & Personas

### Patient 1: Ana Costa (ID: 2605) — Expected: ROUTINE

| Field | Value |
|---|---|
| **Name** | Ana Costa |
| **Age** | 27F |
| **Conditions** | None active (resolved tonsillitis 2024) |
| **Medications** | None |
| **Allergies** | None |
| **Key vitals** | BMI 22, BP 110/70 (normal) |

**Opening message:**

> "Hi, I'm Ana Costa, I've been having a fever and feeling tired for a couple days"

**Persona:** Young healthy woman with a minor acute complaint. Slightly impatient, not worried. Answers are brief and casual. Symptoms are mild: low-grade fever, fatigue, maybe mild sore throat. No red flags, no chronic conditions to explore.

**Expected agent behavior:**

- Asks simple acute questions (duration, other symptoms, temperature)
- No deep chronic condition probing
- No red flag alerts
- Assigns **routine** priority

---

### Patient 2: Maria Silva (ID: 2627) — Expected: URGENT

| Field | Value |
|---|---|
| **Name** | Maria Silva |
| **Age** | 58F |
| **Conditions** | Type 2 Diabetes (2018), Essential Hypertension (2015) |
| **Medications** | Metformin 850mg 12/12h, Losartan 50mg daily |
| **Allergies** | Penicillin/Amoxicillin (skin rash) |
| **Key labs** | HbA1c 8.2% (HIGH), Fasting Glucose 180 (HIGH), Microalbuminuria 45 (HIGH) |
| **Key vitals** | BP 148/92 (elevated) |

**Opening message:**

> "Hi, I'm Maria Silva, I've been feeling really thirsty and having headaches"

**Persona:** 58-year-old woman with uncontrolled diabetes and hypertension. She's been feeling increasingly thirsty, urinating more than usual, occasional blurred vision. Sometimes forgets to take metformin on time. Headaches are likely related to elevated BP. She's somewhat aware her diabetes "isn't great" but doesn't realize how poorly controlled it is.

**Expected agent behavior:**

- Connects thirst to diabetes, asks about glucose control
- Asks about polyuria/polydipsia (diabetes-specific)
- Asks about medication adherence
- Asks about blood pressure control
- Flags elevated HbA1c + microalbuminuria risk (early nephropathy)
- Assigns **urgent** priority (moderate/high risk)

---

### Patient 3: Roberto Lima (ID: 2642) — Expected: URGENT/EMERGENCY

| Field | Value |
|---|---|
| **Name** | Roberto Lima |
| **Age** | 65M |
| **Conditions** | COPD (2016), Hypertension (2010), Knee Osteoarthritis (2018), Major Depressive Disorder (2023) |
| **Medications** | Losartan 50mg, Tiotropium 18mcg inhaled, Sertraline 50mg, Paracetamol 750mg PRN |
| **Allergies** | Dipyrone/Metamizole (anaphylaxis — severe) |
| **Key labs** | SpO2 93% (LOW), FEV1 45% predicted (LOW), PHQ-9 18 (severe depression) |

**Opening message:**

> "I'm Roberto Lima, my cough has been getting worse and I've been feeling really sad lately"

**Persona:** 65-year-old man with COPD and severe depression. His cough has been worsening over the past week, more short of breath than usual when walking. He's been feeling deeply sad, hopeless, trouble sleeping, loss of appetite. He may hint at dark thoughts (not overtly suicidal, but enough for the agent to detect risk). On sertraline for depression.

**Expected agent behavior:**

- Asks about COPD symptoms (worsening SOB, sputum changes)
- Asks about depression severity and suicidal ideation
- **Critical red flag**: depression + sertraline + "dark thoughts" → warns immediately
- Asks about SpO2 levels and respiratory status
- Flags PHQ-9 score of 18 (severe) + sertraline interaction risk
- Assigns **urgent** or **emergency** priority (high/critical risk)

---

### Patient 4: Joao Santos (ID: 2610) — Expected: EMERGENCY

| Field | Value |
|---|---|
| **Name** | Joao Santos |
| **Age** | 71M |
| **Conditions** | Chronic Heart Failure (2020), Atrial Fibrillation (2019), Type 2 Diabetes (2012), Hypertension (2008), CKD Stage 3 (2021) |
| **Medications** | Warfarin 5mg, Metformin 1000mg, Enalapril 20mg, Furosemide 40mg |
| **Allergies** | Aspirin/AAS (asthma exacerbation — severe) |
| **Key labs** | HbA1c 7.1%, INR 2.8, Creatinine 2.1 (HIGH), BNP 450 (HIGH), EF 35% (LOW) |

**Opening message:**

> "Hi, I'm Joao Santos, I've been having chest pain"

**Persona:** 71-year-old man with multiple serious cardiovascular conditions. He's been having substernal chest pressure for the past few hours, worse with exertion. Also short of breath when lying down (orthopnea), swollen ankles. On warfarin for AF. He's worried but trying to stay calm.

**Expected agent behavior:**

- **Immediate critical red flag warning**: chest pain + heart failure + atrial fibrillation + warfarin
- Asks about pain characteristics (location, radiation, severity)
- Asks about associated symptoms (SOB, swelling, dizziness)
- Asks about warfarin compliance and bleeding signs
- Warns patient to seek emergency care immediately
- Assigns **emergency** priority (critical risk)

---

## Evaluation Criteria

| Criterion | Description |
|---|---|
| **Contextual awareness** | Agent asks condition-relevant questions, not generic ones |
| **Red flag detection** | Flags critical combos (warfarin+bleeding, depression+suicidal ideation, chest pain+HF) |
| **Immediate warning** | For critical red flags, warns patient before continuing questions |
| **Anti-repetition** | No repeated questions across turns |
| **Empathy & naturalness** | Warm, conversational tone; not robotic |
| **Priority accuracy** | Final priority matches expected |
| **FHIR writes** | Creates Encounter, Flag (if high risk), QuestionnaireResponse |

---

## Execution Order

1. **Ana Costa** (routine) — lowest priority first
2. **Maria Silva** (urgent)
3. **Roberto Lima** (urgent/emergency)
4. **Joao Santos** (emergency) — highest priority last

This ascending order validates the priority gradient.

---

## Answer Style

Short, natural, patient-like:

- "Yeah, about two days now"
- "I've been peeing a lot more than usual"
- "Sometimes I feel like nothing matters anymore"
- "The pain is right here in my chest, like pressure"
- "No, I haven't noticed any bleeding"
- "Just a low fever, around 38 degrees"
- "I forget to take my pills sometimes"

---

## Results

**Test date:** 2026-06-09
**Agent model:** gpt-4o-mini
**LLM_CACHE:** off

### Patient 1: Ana Costa — Expected: ROUTINE

| Turn | Agent Question/Response | Patient Answer | Evaluation Notes |
|---|---|---|---|
| 0 | _(opening)_ | "Hi, I am Ana Costa, I have been having a fever and feeling tired for a couple days" | |
| 1 | Asked about duration and other symptoms | "It started two days ago, just a low fever and body aches" | Appropriate acute-care question |
| 2 | Asked about sore throat, nasal congestion | "A little sore throat, but nothing major" | Good follow-up |
| 3 | Asked about difficulty breathing, chest pain | "No, nothing like that" | Necessary red flag screen |
| 4 | Asked about temperature measurement | "Around 38 degrees, I think" | Reasonable |
| 5 | Asked about chronic conditions/medications | "No, I am pretty healthy" | Good check |
| 6 | Provided clinical summary | _(end)_ | Hallucinated "obesity" — BMI is 22 (normal) |

**Actual priority:** urgent
**Actual risk:** moderate
**Pass/Fail:** **FAIL** — Over-triaged. A healthy 27F with a 2-day low-grade fever and mild sore throat should be routine/low. Agent created an unnecessary Flag for what is essentially a common cold.

---

### Patient 2: Maria Silva — Expected: URGENT

| Turn | Agent Question/Response | Patient Answer | Evaluation Notes |
|---|---|---|---|
| 0 | _(opening)_ | "Hi, I am Maria Silva, I have been feeling really thirsty and having headaches" | |
| 1 | Immediately connected thirst→diabetes, asked about glucose control | "I have been peeing a lot more than usual, and my sugar has been high" | Good contextual connection |
| 2 | Asked about medication adherence, blurred vision | "Sometimes I forget my metformin, and yes my vision has been a bit blurry" | Flagged blurred vision as red flag |
| 3 | Asked about blood pressure, morning headaches | "My blood pressure has been running high, and yes I wake up with headaches" | Connected morning headaches→BP |
| 4 | Provided clinical summary | _(end)_ | Did not explicitly mention microalbuminuria from FHIR data |

**Actual priority:** urgent
**Actual risk:** (not explicitly stated, implied moderate/high)
**Pass/Fail:** **PASS** — Correct priority. Good contextual awareness connecting thirst→diabetes, headaches→BP. Missed opportunity to flag microalbuminuria (45 mg/g) as early nephropathy risk.

---

### Patient 3: Roberto Lima — Expected: URGENT/EMERGENCY

| Turn | Agent Question/Response | Patient Answer | Evaluation Notes |
|---|---|---|---|
| 0 | _(opening)_ | "I am Roberto Lima, my cough has been getting worse and I have been feeling really sad lately" | |
| 1 | Asked about COPD symptoms (SOB, sputum) | "More short of breath when walking, and I am coughing up more phlegm" | Good COPD-specific questions |
| 2 | Asked about depression severity, sleep, appetite | "I feel hopeless, can't sleep, no appetite. Sometimes I feel like nothing matters anymore" | Detected hopelessness |
| 3 | Mentioned suicidal ideation risk but did NOT directly screen | "I have been having thoughts that life is not worth living" | Agent waited for patient to volunteer SI instead of proactively screening |
| 4 | Provided clinical summary, warned patient | _(end)_ | Risk=CRITICAL but Priority=URGENT — **mismatch** |

**Actual priority:** urgent
**Actual risk:** critical
**Pass/Fail:** **PARTIAL PASS** — Correctly identified suicidal ideation as critical. But: (1) Risk=CRITICAL should produce Priority=EMERGENCY per system rules — this is a bug. (2) Agent did not proactively screen for suicidal ideation when depression+hopelessness was detected — only flagged it after the patient volunteered passive SI.

---

### Patient 4: Joao Santos — Expected: EMERGENCY

| Turn | Agent Question/Response | Patient Answer | Evaluation Notes |
|---|---|---|---|
| 0 | _(opening)_ | "Hi, I am Joao Santos, I have been having chest pain" | |
| 1 | Asked about pain characteristics (sharp/dull/pressure) | "Pressure, right in the middle of my chest. And trouble breathing when I lie down" | Appropriate first question |
| 2 | Detected red flags: chest pain + HF + AF. Warned immediately. Asked about leg/ankle swelling. | "Yes, my ankles have been swollen for a few days" | **Immediate warning on turn 2** — excellent |
| 3 | Connected swelling→fluid retention. Mentioned warfarin monitoring. Asked about dizziness. | "A little lightheaded when I stand up quickly, but no fainting" | Good contextual connection |
| 4 | Connected lightheadedness→HF/enalapril. Asked about diabetes management. | "My blood sugar has been a bit high, around 180" | Comprehensive |
| 5 | Connected warfarin+uncontrolled diabetes=bleeding risk. Asked about medication changes. | "No changes, I take all my pills. But the chest pain started a few hours ago and it is not going away" | |
| 6 | **CRITICAL WARNING**: persistent chest pain + HF = possible cardiac event. Told patient to seek emergency care immediately. | _(patient asked for explanation)_ | Urgent emergency warning given |
| 7 | Detailed explanation: chest pain→ACS concern, orthopnea→pulmonary edema, swelling→HF decompensation, warfarin risks | "Thank you. So what is the priority level?" | Excellent synthesis |
| 8 | **Priority=EMERGENCY, Risk=CRITICAL**. Full clinical summary with 6 follow-up tasks. | _(end)_ | Correct. Comprehensive follow-up plan including ECG, troponins, INR adjustment, cardiology consult |

**Actual priority:** emergency
**Actual risk:** critical
**Pass/Fail:** **PASS** — Correct priority and risk. Agent detected the critical red flag early (turn 2), warned the patient immediately, and produced a comprehensive clinical assessment with actionable follow-up tasks. Mentioned all key conditions (HF, AF, CKD, DM2, HTN) and medications (warfarin, enalapril, furosemide, metformin).

**Note:** A `create_flag_and_task` call failed with 400 Bad Request on one turn (FHIR server rejected the Task resource). The agent recovered and completed the assessment on subsequent turns.

---

## Summary

| Patient | Expected Priority | Actual Priority | Expected Risk | Actual Risk | Pass/Fail |
|---|---|---|---|---|---|
| Ana Costa | routine | **urgent** | low | **moderate** | **FAIL** (over-triaged) |
| Maria Silva | urgent | **urgent** | moderate/high | moderate/high | **PASS** |
| Roberto Lima | urgent/emergency | **urgent** | high/critical | **critical** | **PARTIAL PASS** (risk/priority mismatch) |
| Joao Santos | emergency | **emergency** | critical | **critical** | **PASS** |

**Priority accuracy:** 2/4 correct, 1 partial, 1 fail (50% strict, 75% lenient)

---

## Behavioral Observations

### Contextual Awareness — GOOD
The agent consistently reads FHIR patient data before asking questions and tailors its questions to the patient's conditions. It correctly connected:
- Thirst → diabetes (Maria)
- Morning headaches → hypertension (Maria)
- COPD worsening → asked about SOB, sputum (Roberto)
- Chest pain + HF + AF → immediate critical warning (Joao)
- Warfarin use → bleeding risk monitoring (Joao)
- Enalapril + HF → lightheadedness connection (Joao)

### Red Flag Detection — GOOD (with gaps)
- Chest pain + HF + AF: Immediately detected and warned (Joao) ✓
- Depression + hopelessness → suicidal ideation risk: Detected but only after patient volunteered (Roberto) ✗
- Blurred vision + uncontrolled diabetes: Flagged (Maria) ✓
- Microalbuminuria + diabetes → nephropathy risk: NOT flagged (Maria) ✗

### Immediate Warning — GOOD for physical emergencies, WEAK for psychiatric
- Joao: Warned to seek emergency care on turn 2 after first hearing about chest pain + orthopnea ✓
- Roberto: Did not warn about suicidal ideation risk until patient volunteered passive SI ✗
- The agent is much better at flagging cardiovascular emergencies than psychiatric ones

### Anti-Repetition — GOOD (after serialization fix)
- No repeated questions observed in any patient after the ToolMessage serialization fix
- Earlier runs without the fix showed severe repetition (e.g., Ana Costa: "difficulty breathing or chest pain" 4x)

### Empathy & Naturalness — ADEQUATE
- Tone is polite and professional but somewhat formulaic
- Uses patient name appropriately
- Not robotic, but not particularly warm either
- The emergency warning for Joao was appropriately urgent

### Condition Hallucination — BUG
- Agent referenced "obesity" for Ana Costa (BMI=22, normal weight)
- This suggests the LLM is hallucinating conditions not present in the FHIR data
- Likely caused by gpt-4o-mini filling in common associations (fever + fatigue → obesity risk factor) without grounding in the actual patient record

### Risk/Priority Mismatch — BUG
- Roberto Lima: Risk=CRITICAL, Priority=URGENT
- Per the system's own clinical reasoning rules, critical risk should produce emergency priority
- This mismatch suggests the clinical_assessment tool and the priority assignment logic are not fully aligned
- The system prompt says "if risk=critical, priority should=emergency" but this rule was not enforced

### FHIR Write Failures — BUG
- `create_flag_and_task` returned 400 Bad Request for Task resource during Joao's session
- The agent recovered gracefully and continued the assessment
- This is likely a FHIR resource validation issue (missing required fields in Task)

### Proactive Suicidal Ideation Screening — MISSING
- When depression + hopelessness + "nothing matters" is detected, the agent should immediately ask "Are you having thoughts of harming yourself?" or "Are you thinking about suicide?"
- Instead, the agent waited for the patient to volunteer this information
- This is a clinical safety gap — in real triage, proactive SI screening is standard of care

---

## Bugs Discovered

1. **Condition hallucination** — Agent fabricated "obesity" for Ana Costa (BMI=22)
2. **Risk/Priority mismatch** — Roberto Lima got Risk=CRITICAL but Priority=URGENT (should be EMERGENCY per system rules)
3. **Missing proactive SI screening** — Agent does not directly screen for suicidal ideation when depression+hopelessness is detected
4. **FHIR Task creation 400 error** — `create_flag_and_task` fails with Bad Request for Task resource (missing required field)
5. **Over-triage of low-acuity patients** — Ana Costa (routine) was assigned urgent/moderate for what is essentially a common cold

---

## Rerun Instructions

```bash
# Ensure containers are running
docker compose up -d

# For each patient, repeat this pattern:

# 1. Reset any previous session
docker compose exec triage bash -c 'cd /app && python3 test_priority.py reset'

# 2. Start session
docker compose exec triage bash -c \
'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py start "Ana Costa" "Hi, I am Ana Costa, I have been having a fever and feeling tired"'

# 3. Read agent response, then reply (repeat until priority is detected)
docker compose exec triage bash -c \
'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py reply "Just a couple days, low fever and body aches"'

# 4. Reset between patients
docker compose exec triage bash -c 'cd /app && python3 test_priority.py reset'

# 5. Start next patient
docker compose exec triage bash -c \
'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py start "Maria Silva" "Hi, I am Maria Silva, I have been feeling really thirsty and having headaches"'

# ... and so on for Roberto Lima and Joao Santos
```
