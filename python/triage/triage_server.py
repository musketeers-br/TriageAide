import json
from fastmcp import FastMCP

mcp = FastMCP("TriageServer")

RED_FLAGS = {
    "shortness of breath": ["heart failure", "copd", "asthma", "atrial fibrillation"],
    "chest pain": ["heart failure", "hypertension", "atrial fibrillation"],
    "excessive thirst": ["diabetes", "diabetes type 2"],
    "blurred vision": ["diabetes", "diabetes type 2", "hypertension"],
    "leg swelling": ["heart failure", "hypertension"],
    "dizziness": ["hypertension", "atrial fibrillation"],
    "bleeding": ["warfarin", "anticoagulant"],
    "worsening cough": ["copd", "heart failure"],
    "suicidal ideation": ["depression"],
    "severe fatigue": ["diabetes", "heart failure", "depression"],
}

SYMPTOM_CATEGORIES = {
    "general": ["fatigue", "tiredness", "fever", "weight loss", "excessive thirst"],
    "cardiovascular": ["shortness of breath", "chest pain", "palpitation", "leg swelling", "dizziness"],
    "respiratory": ["cough", "difficulty breathing", "worsening cough", "wheezing"],
    "neurological": ["headache", "dizziness", "blurred vision", "confusion"],
    "metabolic": ["excessive thirst", "polydipsia", "polyuria", "blurred vision"],
    "mental": ["sadness", "insomnia", "suicidal ideation", "anxiety", "irritability"],
}


def _build_question_plan(patient_context: dict) -> list[dict]:
    conditions = [c.get("display", "").lower() for c in patient_context.get("conditions", []) if c.get("status") == "active"]
    medications = [m.get("medication", "").lower() for m in patient_context.get("medications", []) if m.get("status") == "active"]
    allergies = patient_context.get("allergies", [])
    last_encounter = patient_context.get("last_encounter", "")

    plan = []

    plan.append({"topic": "reason_for_visit", "question": "How are you feeling today?"})

    for cond in conditions:
        if "diabetes" in cond:
            plan.append({"topic": "diabetes_control", "question": "I noticed you have diabetes. Has your blood sugar been controlled lately?"})
            plan.append({"topic": "diabetes_symptoms", "question": "Have you had increased thirst, hunger, or urination in recent days?"})
            plan.append({"topic": "diabetes_vision", "question": "Have you noticed any changes in your vision?"})
        if "hypertens" in cond:
            plan.append({"topic": "hypertension_control", "question": "Has your blood pressure been controlled lately?"})
            plan.append({"topic": "hypertension_symptoms", "question": "Have you felt dizzy or had headaches recently?"})
            plan.append({"topic": "hypertension_swelling", "question": "Have you noticed swelling in your legs?"})
        if "heart failure" in cond or ("insufficiency" in cond and "cardiac" in cond):
            plan.append({"topic": "hf_shortness_of_breath", "question": "Have you had shortness of breath when lying down or climbing stairs?"})
            plan.append({"topic": "hf_swelling", "question": "Have you noticed swelling in your legs or abdomen?"})
        if "atrial fibrillation" in cond or "fibrillation" in cond:
            plan.append({"topic": "af_palpitation", "question": "Have you felt your heart racing or fluttering recently?"})
        if "copd" in cond or "obstructive" in cond:
            plan.append({"topic": "copd_shortness_of_breath", "question": "Has your shortness of breath worsened in recent days?"})
            plan.append({"topic": "copd_cough", "question": "Have you had increased coughing or different sputum than usual?"})
        if "depress" in cond:
            plan.append({"topic": "depression_emotional", "question": "How are you feeling emotionally?"})
            plan.append({"topic": "depression_risk", "question": "Have you had thoughts of hurting yourself or giving up?"})
        if "osteoarthritis" in cond or "arthrosis" in cond:
            plan.append({"topic": "osteoarthritis_pain", "question": "How is your knee pain?"})
            plan.append({"topic": "osteoarthritis_impact", "question": "Does the pain affect your daily activities?"})

    for med in medications:
        if "warfarin" in med:
            plan.append({"topic": "warfarin_bleeding", "question": "Have you noticed any unusual bleeding or bruising?"})
        if "metformin" in med:
            plan.append({"topic": "metformin_gi", "question": "Have you had nausea, abdominal pain, or diarrhea?"})

    for allergy in allergies:
        substance = allergy.get("substance", "").lower()
        severity = allergy.get("criticality", "")
        if "anaphylaxis" in str(allergy.get("reactions", [])) or severity == "high":
            plan.append({"topic": f"allergy_{substance.replace(' ', '_')}", "question": f"Reminder: you have a severe allergy to {substance}. Avoid this medication."})

    if last_encounter:
        plan.append({"topic": "changes_since_last", "question": f"Your last visit was on {last_encounter}. Has anything changed since then?"})

    seen = set()
    unique_plan = []
    for item in plan:
        if item["topic"] not in seen:
            seen.add(item["topic"])
            unique_plan.append(item)

    return unique_plan


@mcp.tool()
async def get_next_triage_question(patient_context: str, covered_topics: list[str] = None) -> str:
    """Returns the NEXT triage question (one at a time) based on FHIR history and already covered topics. patient_context = JSON with patient data. covered_topics = list of already answered topics (e.g. ["diabetes_control","hypertension_control"])."""
    try:
        ctx = json.loads(patient_context)
    except json.JSONDecodeError:
        return json.dumps({"error": "patient_context must be valid JSON"}, ensure_ascii=False)

    covered = covered_topics if covered_topics else []

    covered_set = set(covered)
    full_plan = _build_question_plan(ctx)
    remaining = [q for q in full_plan if q["topic"] not in covered_set]

    if not remaining:
        return json.dumps(
            {"question": None, "topic": None, "remaining_topics": [], "total_remaining": 0},
            ensure_ascii=False,
        )

    next_q = remaining[0]
    all_remaining_topics = [q["topic"] for q in remaining[1:]]

    return json.dumps(
        {
            "question": next_q["question"],
            "topic": next_q["topic"],
            "remaining_topics": all_remaining_topics,
            "total_remaining": len(remaining) - 1,
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def get_all_triage_topics(patient_context: str) -> str:
    """Returns all available triage topics for the patient. patient_context = JSON with patient data. Use to see all topics before starting triage."""
    try:
        ctx = json.loads(patient_context)
    except json.JSONDecodeError:
        return json.dumps({"error": "patient_context must be valid JSON"}, ensure_ascii=False)

    full_plan = _build_question_plan(ctx)
    return json.dumps(
        {
            "topics": [{"topic": q["topic"], "question": q["question"]} for q in full_plan],
            "total": len(full_plan),
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def parse_symptoms(patient_response: str) -> str:
    """Extracts and structures symptoms, duration, and severity from the patient's response. patient_response = free text of the patient's response."""
    response_lower = patient_response.lower()

    found_symptoms = []
    for category, symptoms in SYMPTOM_CATEGORIES.items():
        for symptom in symptoms:
            if symptom in response_lower:
                found_symptoms.append({"symptom": symptom, "category": category})

    duration = ""
    for marker in ["for ", "last ", "past ", "since "]:
        if marker in response_lower:
            idx = response_lower.index(marker)
            snippet = response_lower[idx : idx + 30]
            duration = snippet.strip()
            break

    severity = "moderate"
    if any(w in response_lower for w in ["very", "severe", "strong", "serious", "unbearable", "worsening"]):
        severity = "severe"
    elif any(w in response_lower for w in ["mild", "slight", "little", "minimal"]):
        severity = "mild"

    return json.dumps(
        {
            "raw_response": patient_response[:200],
            "identified_symptoms": found_symptoms,
            "estimated_duration": duration,
            "estimated_severity": severity,
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def check_red_flags(symptoms: list, conditions: list) -> str:
    """Checks warning signs (red flags) by cross-referencing current symptoms with existing conditions. symptoms = JSON list of symptoms, conditions = JSON list of active conditions."""
    try:
        if symptoms is None:
            symptom_list = []
        elif isinstance(symptoms, str):
            symptom_list = json.loads(symptoms)
        else:
            symptom_list = symptoms
    except json.JSONDecodeError:
        symptom_list = [{"symptom": str(symptoms)}]
    try:
        if conditions is None:
            condition_list = []
        elif isinstance(conditions, str):
            condition_list = json.loads(conditions)
        else:
            condition_list = conditions
    except json.JSONDecodeError:
        condition_list = [{"display": str(conditions)}]

    condition_names = [c.get("display", "").lower() if isinstance(c, dict) else c.lower() for c in condition_list]
    symptom_names = [s.get("symptom", "").lower() if isinstance(s, dict) else s.lower() for s in symptom_list]

    alerts = []
    for symptom_name in symptom_names:
        for flag_symptom, related_conditions in RED_FLAGS.items():
            if flag_symptom in symptom_name or symptom_name in flag_symptom:
                for rc in related_conditions:
                    if any(rc in cn for cn in condition_names):
                        alerts.append(
                            {
                                "red_flag": f"{symptom_name} + {rc}",
                                "symptom": symptom_name,
                                "related_condition": rc,
                                "risk": "elevated",
                            }
                        )

    has_critical = any(s.get("symptom", "").lower() in ["chest pain", "suicidal ideation", "bleeding", "shortness of breath"] for s in (symptom_list if isinstance(symptom_list, list) else []))

    return json.dumps(
        {
            "alerts": alerts,
            "has_critical_red_flag": has_critical,
            "alert_count": len(alerts),
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def build_questionnaire_response_data(patient_id: str, questions: list, answers: list) -> str:
    """Builds data structure for FHIR QuestionnaireResponse ready to be saved. questions = JSON list of questions, answers = JSON list of answers (same order)."""
    try:
        if questions is None:
            q_list = []
        elif isinstance(questions, str):
            q_list = json.loads(questions)
        else:
            q_list = questions
    except json.JSONDecodeError:
        q_list = [str(questions)] if questions else []
    try:
        if answers is None:
            a_list = []
        elif isinstance(answers, str):
            a_list = json.loads(answers)
        else:
            a_list = answers
    except json.JSONDecodeError:
        a_list = [str(answers)] if answers else []

    items = []
    for i, (q, a) in enumerate(zip(q_list, a_list)):
        items.append({"question": str(q), "answer": str(a)})

    return json.dumps(
        {"patient_id": patient_id, "items": items, "total": len(items)},
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)
