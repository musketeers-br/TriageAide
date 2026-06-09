# Priority Test Plan — Dynamic Agent Priority Sense Evaluation

**Goal:** Dynamically simulate 4 test patients interacting with the triage agent to evaluate whether it assigns correct care priorities.

**Method:** Turn-by-turn interaction — I (the LLM) play each patient, read the agent's questions, and respond naturally as that patient would. No scripted/fixed responses.

**Last executed:** _(to be filled after run)_

---

## Test Harness

A Python script `python/triage/test_priority.py` enables turn-by-turn agent interaction:

```bash
# Start a new session
docker compose exec triage bash -c 'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py start "Ana Costa" "Hi, I'\''m Ana Costa, I'\''ve been having a fever and feeling tired"'

# Reply to agent's question (after reading the output)
docker compose exec triage bash -c 'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py reply "It started two days ago, just a low fever and body aches"'

# Check session status
docker compose exec triage bash -c 'cd /app && python3 test_priority.py status'

# Reset session (between patients)
docker compose exec triage bash -c 'cd /app && python3 test_priority.py reset'
```

### How the script works

- `start <patient_name> <opening_message>` — Creates a new agent session, sends the opening message, prints the agent's response, saves state to `/tmp/triage_test_session.json`
- `reply <answer>` — Loads session, appends patient answer, invokes agent, prints response, saves updated state
- `status` — Shows current session info (patient, turn count, priority if determined)
- `reset` — Clears session state
- Auto-detects when the agent outputs the final clinical summary (priority/risk lines)
- Creates a fresh agent per invocation (no caching: `LLM_CACHE=off`)

---

## Patient Profiles & Personas

### Patient 1: Ana Costa (ID: 2605) — ROUTINE expected

| Field | Value |
|---|---|
| **Name** | Ana Costa |
| **Age** | 27F |
| **Conditions** | None active (resolved tonsillitis 2024) |
| **Medications** | None |
| **Allergies** | None |
| **Key vitals** | BMI 22, BP 110/70 (normal) |

**Opening:** "Hi, I'm Ana Costa, I've been having a fever and feeling tired for a couple days"

**Persona:** Young healthy woman with a minor acute complaint. Slightly impatient, not worried. Answers are brief and casual. Symptoms are mild: low-grade fever, fatigue, maybe mild sore throat. No red flags, no chronic conditions to explore.

**Expected agent behavior:**
- Asks simple acute questions (duration, other symptoms, temperature)
- No deep chronic condition probing
- No red flag alerts
- Assigns **routine** priority

---

### Patient 2: Maria Silva (ID: 2627) — URGENT expected

| Field | Value |
|---|---|
| **Name** | Maria Silva |
| **Age** | 58F |
| **Conditions** | Type 2 Diabetes (2018), Essential Hypertension (2015) |
| **Medications** | Metformin 850mg 12/12h, Losartan 50mg daily |
| **Allergies** | Penicillin/Amoxicillin (skin rash) |
| **Key labs** | HbA1c 8.2% (HIGH), Fasting Glucose 180 (HIGH), Microalbuminuria 45 (HIGH) |
| **Key vitals** | BP 148/92 (elevated) |

**Opening:** "Hi, I'm Maria Silva, I've been feeling really thirsty and having headaches"

**Persona:** 58-year-old woman with uncontrolled diabetes and hypertension. She's been feeling increasingly thirsty, urinating more than usual, occasional blurred vision. Sometimes forgets to take metformin on time. Headaches are likely related to elevated BP. She's somewhat aware her diabetes "isn't great" but doesn't realize how poorly controlled it is.

**Expected agent behavior:**
- Connects thirst → diabetes, asks about glucose control
- Asks about polyuria/polydipsia (diabetes-specific)
- Asks about medication adherence
- Asks about blood pressure control
- Flags elevated HbA1c + microalbuminuria risk (early nephropathy)
- Assigns **urgent** priority (moderate/high risk)

---

### Patient 3: Roberto Lima (ID: 2642) — URGENT/EMERGENCY expected

| Field | Value |
|---|---|
| **Name** | Roberto Lima |
| **Age** | 65M |
| **Conditions** | COPD (2016), Essential Hypertension (2010), Knee Osteoarthritis (2018), Major Depressive Disorder (2023) |
| **Medications** | Losartan 50mg, Tiotropium 18mcg inhaled, Sertraline 50mg, Paracetamol 750mg PRN |
| **Allergies** | Dipyrone/Metamizole (anaphylaxis — severe) |
| **Key labs** | SpO2 93% (LOW), FEV1 45% predicted (LOW), PHQ-9 18 (severe depression) |

**Opening:** "I'm Roberto Lima, my cough has been getting worse and I've been feeling really sad lately"

**Persona:** 65-year-old man with COPD and severe depression. His cough has been worsening over the past week, more short of breath than usual when walking. He's been feeling deeply sad, hopeless, trouble sleeping, loss of appetite. He may hint at dark thoughts (not overtly suicidal, but enough for the agent to detect risk). On sertraline for depression.

**Expected agent behavior:**
- Asks about COPD symptoms (worsening SOB, sputum changes)
- Asks about depression severity and suicidal ideation
- **Critical red flag**: depression + sertraline + "dark thoughts" → warns immediately
- Asks about SpO2 levels and respiratory status
- Flags PHQ-9 score of 18 (severe) + sertraline interaction risk
- Assigns **urgent** or **emergency** priority (high/critical risk)

---

### Patient 4: Joao Santos (ID: 2610) — EMERGENCY expected

| Field | Value |
|---|---|
| **Name** | Joao Santos |
| **Age** | 71M |
| **Conditions** | Chronic Heart Failure (2020), Atrial Fibrillation (2019), Type 2 Diabetes (2012), Essential Hypertension (2008), CKD Stage 3 (2021) |
| **Medications** | Warfarin 5mg, Metformin 1000mg, Enalapril 20mg, Furosemide 40mg |
| **Allergies** | Aspirin/AAS (asthma exacerbation — severe) |
| **Key labs** | HbA1c 7.1%, INR 2.8, Creatinine 2.1 (HIGH), BNP 450 (HIGH), EF 35% (LOW) |

**Opening:** "Hi, I'm Joao Santos, I've been having chest pain"

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

Per patient, evaluate:

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

## Results

_(To be filled after testing)_

### Patient 1: Ana Costa — Expected: ROUTINE

| Turn | Agent Question | Patient Answer | Notes |
|---|---|---|---|
| 0 | _(opening)_ | "Hi, I'm Ana Costa, I've been having a fever and feeling tired for a couple days" | |
| 1 | | | |
| 2 | | | |
| ... | | | |

**Actual priority:** _TBD_
**Actual risk:** _TBD_
**Pass/Fail:** _TBD_

### Patient 2: Maria Silva — Expected: URGENT

| Turn | Agent Question | Patient Answer | Notes |
|---|---|---|---|
| 0 | _(opening)_ | "Hi, I'm Maria Silva, I've been feeling really thirsty and having headaches" | |
| 1 | | | |
| ... | | | |

**Actual priority:** _TBD_
**Actual risk:** _TBD_
**Pass/Fail:** _TBD_

### Patient 3: Roberto Lima — Expected: URGENT/EMERGENCY

| Turn | Agent Question | Patient Answer | Notes |
|---|---|---|---|
| 0 | _(opening)_ | "I'm Roberto Lima, my cough has been getting worse and I've been feeling really sad lately" | |
| 1 | | | |
| ... | | | |

**Actual priority:** _TBD_
**Actual risk:** _TBD_
**Pass/Fail:** _TBD_

### Patient 4: Joao Santos — Expected: EMERGENCY

| Turn | Agent Question | Patient Answer | Notes |
|---|---|---|---|
| 0 | _(opening)_ | "Hi, I'm Joao Santos, I've been having chest pain" | |
| 1 | | | |
| ... | | | |

**Actual priority:** _TBD_
**Actual risk:** _TBD_
**Pass/Fail:** _TBD_

---

## Summary

| Patient | Expected Priority | Actual Priority | Expected Risk | Actual Risk | Pass/Fail |
|---|---|---|---|---|---|
| Ana Costa | routine | _TBD_ | low | _TBD_ | _TBD_ |
| Maria Silva | urgent | _TBD_ | moderate/high | _TBD_ | _TBD_ |
| Roberto Lima | urgent/emergency | _TBD_ | high/critical | _TBD_ | _TBD_ |
| Joao Santos | emergency | _TBD_ | critical | _TBD_ | _TBD_ |

---

## Rerun Instructions

```bash
# Ensure containers are running
docker compose up -d

# For each patient, repeat this pattern:
# 1. Start session
docker compose exec triage bash -c 'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py start "Ana Costa" "Hi, I'\''m Ana Costa, I'\''ve been having a fever and feeling tired"'

# 2. Read agent response, then reply
docker compose exec triage bash -c 'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py reply "Just a couple days, low fever and body aches"'

# 3. Continue replying until priority is detected
# ...

# 4. Reset between patients
docker compose exec triage bash -c 'cd /app && python3 test_priority.py reset'

# 5. Start next patient
docker compose exec triage bash -c 'cd /app && LLM_CACHE=off LOG_LEVEL=INFO python3 test_priority.py start "Maria Silva" "Hi, I'\''m Maria Silva, I'\''ve been feeling really thirsty and having headaches"'
# ... and so on
```
