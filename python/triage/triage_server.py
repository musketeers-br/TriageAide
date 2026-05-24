import json
from fastmcp import FastMCP

mcp = FastMCP("TriageServer")

RED_FLAGS = {
    "dispneia": ["insuficiencia cardiaca", "dpoc", "asma", "fibrilacao atrial"],
    "dor toracica": ["insuficiencia cardiaca", "hipertensao", "fibrilacao atrial"],
    "sede excessiva": ["diabetes", "diabetes tipo 2"],
    "visao embaçada": ["diabetes", "diabetes tipo 2", "hipertensao"],
    "inchaco pernas": ["insuficiencia cardiaca", "hipertensao"],
    "tontura": ["hipertensao", "fibrilacao atrial"],
    "sangramento": ["warfarina", "anticoagulante"],
    "piora da tosse": ["dpoc", "insuficiencia cardiaca"],
    "ideias suicidas": ["depressao"],
    "fadiga intensa": ["diabetes", "insuficiencia cardiaca", "depressao"],
}

SYMPTOM_CATEGORIES = {
    "geral": ["fadiga", "cansaco", "febre", "perda de peso", "sede excessiva"],
    "cardiovascular": ["dispneia", "dor toracica", "palpitacao", "inchaco pernas", "tontura"],
    "respiratorio": ["tosse", "falta de ar", "piora da tosse", "sibilo"],
    "neurologico": ["cefaleia", "tontura", "visao embaçada", "confusao"],
    "metabolico": ["sede excessiva", "polidipsia", "poliuria", "visao embaçada"],
    "mental": ["tristeza", "insônia", "ideias suicidas", "ansiedade", "irritabilidade"],
}


def _build_question_plan(patient_context: dict) -> list[dict]:
    conditions = [c.get("display", "").lower() for c in patient_context.get("conditions", []) if c.get("status") == "active"]
    medications = [m.get("medication", "").lower() for m in patient_context.get("medications", []) if m.get("status") == "active"]
    allergies = patient_context.get("allergies", [])
    last_encounter = patient_context.get("last_encounter", "")

    plan = []

    plan.append({"topic": "motivo_consulta", "question": "Como voce esta se sentindo hoje?"})

    for cond in conditions:
        if "diabetes" in cond:
            plan.append({"topic": "diabetes_controle", "question": "Notei que voce tem diabetes. Seu acucar anda controlado ultimamente?"})
            plan.append({"topic": "diabetes_sintomas", "question": "Teve aumento de sede, fome ou urina nos ultimos dias?"})
            plan.append({"topic": "diabetes_visao", "question": "Notou alguma mudanca na visao?"})
        if "hipertens" in cond:
            plan.append({"topic": "hipertensao_controle", "question": "Sua pressao tem sido controlada ultimamente?"})
            plan.append({"topic": "hipertensao_sintomas", "question": "Sentiu tontura ou dor de cabeca recentemente?"})
            plan.append({"topic": "hipertensao_inchaco", "question": "Notou inchaco nas pernas?"})
        if "insuficiencia" in cond and "cardiaca" in cond:
            plan.append({"topic": "ic_falta_ar", "question": "Teve falta de ar ao deitar ou ao subir escadas?"})
            plan.append({"topic": "ic_inchaco", "question": "Notou inchaco nas pernas ou abdome?"})
        if "fibrilacao" in cond:
            plan.append({"topic": "fa_palpitacao", "question": "Sentiu palpitar ou coracao acelerado recentemente?"})
        if "dpoc" in cond or "obstructive" in cond:
            plan.append({"topic": "dpoc_falta_ar", "question": "Sua falta de ar piorou nos ultimos dias?"})
            plan.append({"topic": "dpoc_tosse", "question": "Teve tosse com mais secrecao ou diferente do habitual?"})
        if "depress" in cond:
            plan.append({"topic": "depressao_emocional", "question": "Como esta se sentindo emocionalmente?"})
            plan.append({"topic": "depressao_risco", "question": "Teve pensamentos de se machucar ou desistir?"})
        if "artrose" in cond or "osteoartrite" in cond:
            plan.append({"topic": "artrose_dor", "question": "Como esta a dor no joelho?"})
            plan.append({"topic": "artrose_impacto", "question": "A dor afeta suas atividades diarias?"})

    for med in medications:
        if "warfarina" in med or "varfarina" in med:
            plan.append({"topic": "warfarina_sangramento", "question": "Notou algum sangramento incomum ou hematomas?"})
        if "metformina" in med:
            plan.append({"topic": "metformina_gi", "question": "Teve enjoos, dor abdominal ou diarreia?"})

    for allergy in allergies:
        substance = allergy.get("substance", "").lower()
        severity = allergy.get("criticality", "")
        if "anafilaxia" in str(allergy.get("reactions", [])) or severity == "high":
            plan.append({"topic": f"alergia_{substance.replace(' ', '_')}", "question": f"Lembre-se: voce tem alergia grave a {substance}. Evite esse medicamento."})

    if last_encounter:
        plan.append({"topic": "mudanca_desde_ultima", "question": f"Sua ultima consulta foi em {last_encounter}. Houve alguma mudanca desde entao?"})

    seen = set()
    unique_plan = []
    for item in plan:
        if item["topic"] not in seen:
            seen.add(item["topic"])
            unique_plan.append(item)

    return unique_plan


@mcp.tool()
async def get_next_triage_question(patient_context: str, covered_topics: list[str] = None) -> str:
    """Retorna a PROXIMA pergunta de triagem (uma por vez) baseada no historico FHIR e nos topicos ja cobertos. patient_context = JSON com dados do paciente. covered_topics = lista de topicos ja respondidos (ex: ["diabetes_controle","hipertensao_controle"])."""
    try:
        ctx = json.loads(patient_context)
    except json.JSONDecodeError:
        return json.dumps({"error": "patient_context deve ser JSON valido"}, ensure_ascii=False)

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
    """Retorna todos os topicos de triagem disponiveis para o paciente. patient_context = JSON com dados do paciente. Use para ver todos os topicos antes de comecar a triagem."""
    try:
        ctx = json.loads(patient_context)
    except json.JSONDecodeError:
        return json.dumps({"error": "patient_context deve ser JSON valido"}, ensure_ascii=False)

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
    """Extrai e estrutura sintomas, duracao e severidade da resposta do paciente. patient_response = texto livre da resposta do paciente."""
    response_lower = patient_response.lower()

    found_symptoms = []
    for category, symptoms in SYMPTOM_CATEGORIES.items():
        for symptom in symptoms:
            if symptom in response_lower:
                found_symptoms.append({"symptom": symptom, "category": category})

    duration = ""
    for marker in ["ha ", "faz ", "ultimos ", "ultima ", "desde "]:
        if marker in response_lower:
            idx = response_lower.index(marker)
            snippet = response_lower[idx : idx + 30]
            duration = snippet.strip()
            break

    severity = "moderate"
    if any(w in response_lower for w in ["muito", "intensa", "forte", "grave", "insuportavel", "piorando"]):
        severity = "severe"
    elif any(w in response_lower for w in ["leve", "pouco", "discreto", "minimo"]):
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
    """Verifica sinais de alerta (red flags) cruzando sintomas atuais com condicoes existentes. symptoms = JSON lista de sintomas, conditions = JSON lista de condicoes ativas."""
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

    has_critical = any(s.get("symptom", "").lower() in ["dor toracica", "ideias suicidas", "sangramento", "dispneia"] for s in (symptom_list if isinstance(symptom_list, list) else []))

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
    """Monta estrutura de dados para QuestionnaireResponse FHIR pronto para ser salvo. questions = JSON lista de perguntas, answers = JSON lista de respostas (mesma ordem)."""
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
