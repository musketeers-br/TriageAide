import json
from fastmcp import FastMCP

mcp = FastMCP("ClinicalReasoningServer")

RISK_SCORING = {
    "chronic_conditions": {"dm2": 2, "has": 2, "ic": 4, "fa": 3, "drc": 3, "dpoc": 3, "depressao": 1, "artrose": 1},
    "symptom_weights": {"dispneia": 4, "dor toracica": 5, "sangramento": 4, "ideias suicidas": 5, "fadiga": 2, "sede excessiva": 2, "visao embaçada": 3, "inchaco pernas": 3, "tontura": 2, "piora da tosse": 3, "palpitacao": 3},
    "observation_flags": {"H": 1, "L": 1},
}

PRIORITY_MAP = {
    (0, 3): {"level": "routine", "label": "Rotina", "color": "green"},
    (4, 6): {"level": "urgent", "label": "Urgente", "color": "orange"},
    (7, 99): {"level": "emergency", "label": "Emergencia", "color": "red"},
}


@mcp.tool()
async def assess_clinical_risk(conditions: list, new_symptoms: list, observations: list, medications: list) -> str:
    """Avalia o risco clinico do paciente cruzando condicoes existentes, novos sintomas, observacoes anormais e medicacoes. Retorna score de risco (baixo/moderado/alto/critico) com justificativa."""
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
                risk_factors.append(f"Condicao cronica: {name} (+{score})")

    for s in symp_list:
        name = (s.get("symptom", "") if isinstance(s, dict) else str(s)).lower()
        sev = (s.get("estimated_severity", "moderate") if isinstance(s, dict) else "moderate")
        for symp_key, weight in RISK_SCORING["symptom_weights"].items():
            if symp_key in name:
                mult = {"mild": 0.5, "moderate": 1.0, "severe": 1.5}.get(sev, 1.0)
                adjusted = int(weight * mult)
                risk_score += adjusted
                risk_factors.append(f"Sintoma: {name} ({sev}) (+{adjusted})")

    for o in obs_list:
        interp = (o.get("interpretation", "") if isinstance(o, dict) else "")
        display = (o.get("display", "") if isinstance(o, dict) else str(o))
        if interp in RISK_SCORING["observation_flags"]:
            risk_score += RISK_SCORING["observation_flags"][interp]
            risk_factors.append(f"Exame anormal: {display} ({interp})")

    active_meds = [m for m in med_list if (m.get("status", "") if isinstance(m, dict) else "") == "active"]
    if len(active_meds) >= 4:
        risk_score += 2
        risk_factors.append(f"Polifarmacia: {len(active_meds)} medicamentos ativos (+2)")

    warfarin_active = any("warfarina" in ((m.get("medication", "") if isinstance(m, dict) else str(m)).lower()) for m in active_meds)
    if warfarin_active:
        for s in symp_list:
            name = (s.get("symptom", "") if isinstance(s, dict) else str(s)).lower()
            if "sangramento" in name:
                risk_score += 5
                risk_factors.append("INTERACAO CRITICA: Warfarina + sangramento (+5)")

    if risk_score <= 3:
        level = "baixo"
    elif risk_score <= 6:
        level = "moderado"
    elif risk_score <= 10:
        level = "alto"
    else:
        level = "critico"

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
    """Define prioridade de atendimento baseada na avaliacao de risco. risk_assessment = JSON string com risk_score e risk_level."""
    try:
        if risk_assessment is None:
            risk = {}
        elif isinstance(risk_assessment, str):
            risk = json.loads(risk_assessment)
        else:
            risk = risk_assessment
    except json.JSONDecodeError:
        return json.dumps({"level": "routine", "label": "Rotina", "justification": "Dados de risco invalidos, defaulting para rotina"})

    score = risk.get("risk_score", 0)
    level = risk.get("risk_level", "baixo")

    priority = PRIORITY_MAP.get("default", {"level": "routine", "label": "Rotina", "color": "green"})
    for (lo, hi), p in PRIORITY_MAP.items():
        if lo <= score <= hi:
            priority = p
            break

    justifications = {
        "routine": "Paciente com baixo risco clinico, sem red flags identificados.",
        "urgent": "Paciente com fatores de risco moderado/alto. Necessita atencao prioritaria.",
        "emergency": "Paciente com risco critico ou red flags identificados. Atencao imediata.",
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
    """Gera resumo clinico estruturado para o medico. patient_data = JSON com dados demograficos, triage_data = JSON com dados da triagem, risk_data = JSON com avaliacao de risco."""
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

    name = patient.get("name", "Paciente")
    summary_sections.append(f"PACIENTE: {name} | ID: {patient.get('id', '?')} | {patient.get('gender', '?')} | Nasc: {patient.get('birthDate', '?')}")

    active_conditions = [c.get("display", "") for c in patient.get("conditions", []) if c.get("status") == "active"]
    if active_conditions:
        summary_sections.append(f"CONDICOES ATIVAS: {'; '.join(active_conditions)}")

    active_meds = [f"{m.get('medication', '?')} ({m.get('dosage', '')})" for m in patient.get("medications", []) if m.get("status") == "active"]
    if active_meds:
        summary_sections.append(f"MEDICACOES: {'; '.join(active_meds)}")

    allergies = [f"{a.get('substance', '?')} ({a.get('criticality', '')})" for a in patient.get("allergies", [])]
    if allergies:
        summary_sections.append(f"ALERGIAS: {'; '.join(allergies)}")

    abnormal_obs = [f"{o.get('display', '?')}={o.get('value', '?')} {o.get('unit', '')}" for o in patient.get("observations", []) if o.get("interpretation") in ("H", "L")]
    if abnormal_obs:
        summary_sections.append(f"EXAMES ANORMAIS: {'; '.join(abnormal_obs)}")

    new_symptoms = [s.get("symptom", "") for s in triage.get("identified_symptoms", [])]
    if new_symptoms:
        summary_sections.append(f"NOVOS SINTOMAS: {'; '.join(new_symptoms)}")

    red_flags = triage.get("red_flags", {})
    if isinstance(red_flags, dict) and red_flags.get("alerts"):
        alerts_text = "; ".join(a.get("red_flag", "") for a in red_flags["alerts"])
        summary_sections.append(f"SINAIS DE ALERTA: {alerts_text}")

    summary_sections.append(f"RISCO: {risk.get('risk_level', '?').upper()} (score={risk.get('risk_score', '?')})")
    summary_sections.append(f"PRIORIDADE: {triage.get('priority', {}).get('priority_label', '?')}")

    return json.dumps(
        {
            "summary": "\n".join(summary_sections),
            "risk_level": risk.get("risk_level", "?"),
            "priority": triage.get("priority", {}).get("priority_level", "?"),
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def identify_follow_up_tasks(risk: dict, conditions: list, gaps_in_care: list = None) -> str:
    """Identifica tarefas de follow-up baseadas no risco, condicoes e lacunas no cuidado. risk = JSON com risk_level, conditions = JSON lista de condicoes, gaps_in_care = JSON lista de lacunas."""
    try:
        if risk is None:
            risk_data = {"risk_level": "baixo"}
        elif isinstance(risk, str):
            risk_data = json.loads(risk)
        else:
            risk_data = risk
    except json.JSONDecodeError:
        risk_data = {"risk_level": "baixo"}
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

    risk_level = risk_data.get("risk_level", "baixo")
    if risk_level in ("alto", "critico"):
        tasks.append({"task": "Agendar consulta com especialista em ate 48h", "priority": "urgent", "reason": f"Risco {risk_level}"})

    for c in cond_list:
        name = (c.get("display", "") if isinstance(c, dict) else str(c)).lower()
        if "diabetes" in name:
            tasks.append({"task": "Solicitar HbA1c e glicemia de jejum", "priority": "routine", "reason": "Monitoramento diabetes"})
            tasks.append({"task": "Agendar consulta com oftalmologia (retinopatia)", "priority": "routine", "reason": "Rastreamento complicacoes DM"})
        if "hipertens" in name:
            tasks.append({"task": "Monitorar pressao arterial em casa", "priority": "routine", "reason": "Controle HAS"})
        if "insuficiencia" in name and "cardiaca" in name:
            tasks.append({"task": "Solicitar BNP e ecocardiograma", "priority": "urgent", "reason": "Monitoramento IC"})
        if "fibrilacao" in name:
            tasks.append({"task": "Verificar INR e ajustar warfarina", "priority": "urgent", "reason": "Controle anticoagulacao"})
        if "dpoc" in name:
            tasks.append({"task": "Solicitar espirometria e gasometria", "priority": "routine", "reason": "Monitoramento DPOC"})
        if "depress" in name:
            tasks.append({"task": "Agendar acompanhamento psiquiatrico", "priority": "routine", "reason": "Monitoramento depressao"})

    for gap in gaps:
        gap_text = gap if isinstance(gap, str) else gap.get("description", str(gap))
        tasks.append({"task": f"Resolver: {gap_text}", "priority": "routine", "reason": "Lacuna no cuidado"})

    return json.dumps({"tasks": tasks, "total": len(tasks)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8002)
