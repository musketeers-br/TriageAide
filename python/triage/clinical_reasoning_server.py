import json
from fastmcp import FastMCP

mcp = FastMCP("ClinicalReasoningServer")

RISK_SCORING = {
    "chronic_conditions": {"dm2": 2, "has": 2, "hf": 4, "af": 3, "ckd": 3, "copd": 3, "depression": 1, "osteoarthritis": 1},
    "symptom_weights": {"shortness of breath": 4, "chest pain": 5, "bleeding": 4, "suicidal ideation": 5, "fatigue": 2, "excessive thirst": 2, "blurred vision": 3, "leg swelling": 3, "dizziness": 2, "worsening cough": 3, "palpitation": 3},
    "observation_flags": {"H": 1, "L": 1},
}

PRIORITY_MAP = {
    (0, 3): {"level": "routine", "label": "Routine", "color": "green"},
    (4, 6): {"level": "urgent", "label": "Urgent", "color": "orange"},
    (7, 99): {"level": "emergency", "label": "Emergency", "color": "red"},
}


@mcp.tool()
async def assess_clinical_risk(conditions: list, new_symptoms: list, observations: list, medications: list) -> str:
    """Assesses the patient's clinical risk by cross-referencing existing conditions, new symptoms, abnormal observations, and medications. Returns risk score (low/moderate/high/critical) with justification."""
    try:
        if conditions is None:
            cond_list = []
        elif isinstance(conditions, str):
            cond_list = json.loads(conditions)
        else:
            cond_list = conditions
    except json.JSONDecodeError:
        cond_list = []
    try:
        if new_symptoms is None:
            symp_list = []
        elif isinstance(new_symptoms, str):
            symp_list = json.loads(new_symptoms)
        else:
            symp_list = new_symptoms
    except json.JSONDecodeError:
        symp_list = []
    try:
        if observations is None:
            obs_list = []
        elif isinstance(observations, str):
            obs_list = json.loads(observations)
        else:
            obs_list = observations
    except json.JSONDecodeError:
        obs_list = []
    try:
        if medications is None:
            med_list = []
        elif isinstance(medications, str):
            med_list = json.loads(medications)
        else:
            med_list = medications
    except json.JSONDecodeError:
        med_list = []

    risk_score = 0
    risk_factors = []

    for c in cond_list:
        name = (c.get("display", "") if isinstance(c, dict) else str(c)).lower()
        for cond_key, score in RISK_SCORING["chronic_conditions"].items():
            if cond_key in name:
                risk_score += score
                risk_factors.append(f"Chronic condition: {name} (+{score})")

    for s in symp_list:
        name = (s.get("symptom", "") if isinstance(s, dict) else str(s)).lower()
        sev = (s.get("estimated_severity", "moderate") if isinstance(s, dict) else "moderate")
        for symp_key, weight in RISK_SCORING["symptom_weights"].items():
            if symp_key in name:
                mult = {"mild": 0.5, "moderate": 1.0, "severe": 1.5}.get(sev, 1.0)
                adjusted = int(weight * mult)
                risk_score += adjusted
                risk_factors.append(f"Symptom: {name} ({sev}) (+{adjusted})")

    for o in obs_list:
        interp = (o.get("interpretation", "") if isinstance(o, dict) else "")
        display = (o.get("display", "") if isinstance(o, dict) else str(o))
        if interp in RISK_SCORING["observation_flags"]:
            risk_score += RISK_SCORING["observation_flags"][interp]
            risk_factors.append(f"Abnormal lab: {display} ({interp})")

    active_meds = [m for m in med_list if (m.get("status", "") if isinstance(m, dict) else "") == "active"]
    if len(active_meds) >= 4:
        risk_score += 2
        risk_factors.append(f"Polypharmacy: {len(active_meds)} active medications (+2)")

    warfarin_active = any("warfarin" in ((m.get("medication", "") if isinstance(m, dict) else str(m)).lower()) for m in active_meds)
    if warfarin_active:
        for s in symp_list:
            name = (s.get("symptom", "") if isinstance(s, dict) else str(s)).lower()
            if "bleeding" in name:
                risk_score += 5
                risk_factors.append("CRITICAL INTERACTION: Warfarin + bleeding (+5)")

    if risk_score <= 3:
        level = "low"
    elif risk_score <= 6:
        level = "moderate"
    elif risk_score <= 10:
        level = "high"
    else:
        level = "critical"

    return json.dumps(
        {
            "risk_score": risk_score,
            "risk_level": level,
            "risk_factors": risk_factors,
            "factor_count": len(risk_factors),
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def suggest_priority(risk_assessment: dict) -> str:
    """Determines care priority based on risk assessment. risk_assessment = JSON string with risk_score and risk_level."""
    try:
        if risk_assessment is None:
            risk = {}
        elif isinstance(risk_assessment, str):
            risk = json.loads(risk_assessment)
        else:
            risk = risk_assessment
    except json.JSONDecodeError:
        return json.dumps({"level": "routine", "label": "Routine", "justification": "Invalid risk data, defaulting to routine"})

    score = risk.get("risk_score", 0)
    level = risk.get("risk_level", "low")

    priority = PRIORITY_MAP.get("default", {"level": "routine", "label": "Routine", "color": "green"})
    for (lo, hi), p in PRIORITY_MAP.items():
        if lo <= score <= hi:
            priority = p
            break

    justifications = {
        "routine": "Patient with low clinical risk, no red flags identified.",
        "urgent": "Patient with moderate/high risk factors. Needs priority attention.",
        "emergency": "Patient with critical risk or red flags identified. Immediate attention required.",
    }

    return json.dumps(
        {
            "priority_level": priority["level"],
            "priority_label": priority["label"],
            "color": priority["color"],
            "justification": justifications.get(priority["level"], ""),
            "risk_score": score,
            "risk_level": level,
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def generate_clinical_summary(patient_data: dict, triage_data: dict, risk_data: dict) -> str:
    """Generates structured clinical summary for the physician. patient_data = JSON with demographic data, triage_data = JSON with triage data, risk_data = JSON with risk assessment."""
    try:
        if patient_data is None:
            patient = {}
        elif isinstance(patient_data, str):
            patient = json.loads(patient_data)
        else:
            patient = patient_data
    except json.JSONDecodeError:
        patient = {}
    try:
        if triage_data is None:
            triage = {}
        elif isinstance(triage_data, str):
            triage = json.loads(triage_data)
        else:
            triage = triage_data
    except json.JSONDecodeError:
        triage = {}
    try:
        if risk_data is None:
            risk = {}
        elif isinstance(risk_data, str):
            risk = json.loads(risk_data)
        else:
            risk = risk_data
    except json.JSONDecodeError:
        risk = {}

    summary_sections = []

    name = patient.get("name", "Patient")
    summary_sections.append(f"PATIENT: {name} | ID: {patient.get('id', '?')} | {patient.get('gender', '?')} | DOB: {patient.get('birthDate', '?')}")

    active_conditions = [c.get("display", "") for c in patient.get("conditions", []) if c.get("status") == "active"]
    if active_conditions:
        summary_sections.append(f"ACTIVE CONDITIONS: {'; '.join(active_conditions)}")

    active_meds = [f"{m.get('medication', '?')} ({m.get('dosage', '')})" for m in patient.get("medications", []) if m.get("status") == "active"]
    if active_meds:
        summary_sections.append(f"MEDICATIONS: {'; '.join(active_meds)}")

    allergies = [f"{a.get('substance', '?')} ({a.get('criticality', '')})" for a in patient.get("allergies", [])]
    if allergies:
        summary_sections.append(f"ALLERGIES: {'; '.join(allergies)}")

    abnormal_obs = [f"{o.get('display', '?')}={o.get('value', '?')} {o.get('unit', '')}" for o in patient.get("observations", []) if o.get("interpretation") in ("H", "L")]
    if abnormal_obs:
        summary_sections.append(f"ABNORMAL LABS: {'; '.join(abnormal_obs)}")

    new_symptoms = [s.get("symptom", "") for s in triage.get("identified_symptoms", [])]
    if new_symptoms:
        summary_sections.append(f"NEW SYMPTOMS: {'; '.join(new_symptoms)}")

    red_flags = triage.get("red_flags", {})
    if isinstance(red_flags, dict) and red_flags.get("alerts"):
        alerts_text = "; ".join(a.get("red_flag", "") for a in red_flags["alerts"])
        summary_sections.append(f"RED FLAGS: {alerts_text}")

    summary_sections.append(f"RISK: {risk.get('risk_level', '?').upper()} (score={risk.get('risk_score', '?')})")
    summary_sections.append(f"PRIORITY: {triage.get('priority', {}).get('priority_label', '?')}")

    return json.dumps(
        {
            "summary": "\n".join(summary_sections),
            "risk_level": risk.get("risk_level", "?"),
            "priority": triage.get("priority", {}).get("priority_level", "?"),
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def identify_follow_up_tasks(risk: dict, conditions: list, gaps_in_care: list = []) -> str:
    """Identifies follow-up tasks based on risk, conditions, and gaps in care. risk = JSON with risk_level, conditions = JSON list of conditions, gaps_in_care = JSON list of gaps."""
    try:
        if risk is None:
            risk_data = {"risk_level": "low"}
        elif isinstance(risk, str):
            risk_data = json.loads(risk)
        else:
            risk_data = risk
    except json.JSONDecodeError:
        risk_data = {"risk_level": "low"}
    try:
        if conditions is None:
            cond_list = []
        elif isinstance(conditions, str):
            cond_list = json.loads(conditions)
        else:
            cond_list = conditions
    except json.JSONDecodeError:
        cond_list = []
    try:
        if gaps_in_care is None:
            gaps = []
        elif isinstance(gaps_in_care, str):
            gaps = json.loads(gaps_in_care)
        else:
            gaps = gaps_in_care
    except json.JSONDecodeError:
        gaps = []

    tasks = []

    risk_level = risk_data.get("risk_level", "low")
    if risk_level in ("high", "critical"):
        tasks.append({"task": "Schedule specialist consultation within 48h", "priority": "urgent", "reason": f"{risk_level.capitalize()} risk"})

    for c in cond_list:
        name = (c.get("display", "") if isinstance(c, dict) else str(c)).lower()
        if "diabetes" in name:
            tasks.append({"task": "Order HbA1c and fasting glucose", "priority": "routine", "reason": "Diabetes monitoring"})
            tasks.append({"task": "Schedule ophthalmology consult (retinopathy screening)", "priority": "routine", "reason": "DM complications screening"})
        if "hypertens" in name:
            tasks.append({"task": "Monitor blood pressure at home", "priority": "routine", "reason": "Hypertension control"})
        if "heart failure" in name or ("insufficiency" in name and "cardiac" in name):
            tasks.append({"task": "Order BNP and echocardiogram", "priority": "urgent", "reason": "HF monitoring"})
        if "fibrillation" in name:
            tasks.append({"task": "Check INR and adjust warfarin", "priority": "urgent", "reason": "Anticoagulation control"})
        if "copd" in name:
            tasks.append({"task": "Order spirometry and blood gas", "priority": "routine", "reason": "COPD monitoring"})
        if "depress" in name:
            tasks.append({"task": "Schedule psychiatric follow-up", "priority": "routine", "reason": "Depression monitoring"})

    for gap in gaps:
        gap_text = gap if isinstance(gap, str) else gap.get("description", str(gap))
        tasks.append({"task": f"Resolve: {gap_text}", "priority": "routine", "reason": "Gap in care"})

    return json.dumps({"tasks": tasks, "total": len(tasks)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8002)
