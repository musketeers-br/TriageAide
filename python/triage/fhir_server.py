import os
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("FHIRServer")

FHIR_BASE = os.getenv("FHIR_BASE_URL", "http://localhost:32783/fhir/r4")
FHIR_USER = os.getenv("FHIR_USER", "_SYSTEM")
FHIR_PASS = os.getenv("FHIR_PASS", "SYS")


def _fhir_get(path: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{FHIR_BASE}{path}",
        params=params or {},
        headers={"Accept": "application/fhir+json"},
        auth=(FHIR_USER, FHIR_PASS),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _fhir_post(resource_type: str, resource: dict) -> dict:
    resp = requests.post(
        f"{FHIR_BASE}/{resource_type}",
        json=resource,
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        },
        auth=(FHIR_USER, FHIR_PASS),
        timeout=30,
    )
    resp.raise_for_status()
    location = resp.headers.get("Location", "")
    rid = ""
    parts = location.split("/")
    for i, p in enumerate(parts):
        if p == resource_type and i + 1 < len(parts):
            rid = parts[i + 1]
            break
    if resp.text and resp.headers.get("Content-Type", "").startswith("application/json"):
        return resp.json()
    return {"id": rid, "resourceType": resource_type}


def _format_bundle(bundle: dict) -> str:
    entries = bundle.get("entry", [])
    total = bundle.get("total", len(entries))
    resources = []
    for e in entries:
        r = e.get("resource", {})
        rt = r.get("resourceType", "?")
        rid = r.get("id", "?")
        resources.append(f"{rt}/{rid}")
    return json.dumps({"total": total, "resources": resources}, indent=2)


@mcp.tool()
async def search_patients(name: str) -> str:
    """Busca pacientes pelo nome (parcial, case-insensitive). Use esta ferramenta QUANDO VOCE NAO TEM O ID do paciente, apenas o nome. Retorna lista de pacientes com ID, nome e data de nascimento."""
    parts = name.strip().split()
    queries = []
    if len(parts) >= 2:
        queries.append({"family": parts[-1], "_count": 20})
        queries.append({"given": parts[0], "_count": 20})
    for part in parts:
        queries.append({"name": part, "_count": 20})
    seen_ids = set()
    patients = []
    for params in queries:
        try:
            bundle = _fhir_get("/Patient", params)
            for e in bundle.get("entry", []):
                p = e["resource"]
                pid = p.get("id")
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                names = p.get("name", [])
                pname = ""
                if names:
                    n = names[0]
                    pname = " ".join(n.get("given", [])) + " " + n.get("family", "")
                patients.append({
                    "id": pid,
                    "name": pname,
                    "gender": p.get("gender"),
                    "birthDate": p.get("birthDate"),
                })
        except Exception:
            continue
        if patients:
            break
    return json.dumps({"total": len(patients), "patients": patients}, ensure_ascii=False)


@mcp.tool()
async def get_patient(patient_id: str) -> str:
    """Busca dados demograficos de um paciente pelo ID. Retorna nome, genero, data de nascimento e identificadores."""
    data = _fhir_get(f"/Patient/{patient_id}")
    names = data.get("name", [])
    name = ""
    if names:
        n = names[0]
        name = " ".join(n.get("given", [])) + " " + n.get("family", "")
    result = {
        "id": data.get("id"),
        "name": name,
        "gender": data.get("gender"),
        "birthDate": data.get("birthDate"),
        "identifier": [i.get("value", "") for i in data.get("identifier", [])],
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def get_patient_conditions(patient_id: str) -> str:
    """Busca todas as condicoes/doencas de um paciente. Retorna condicoes ativas e resolvidas com codigos ICD-10."""
    bundle = _fhir_get("/Condition", {"patient": patient_id, "_count": 100})
    conditions = []
    for e in bundle.get("entry", []):
        c = e["resource"]
        status = c.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", "?")
        code = c.get("code", {})
        display = code.get("text", code.get("coding", [{}])[0].get("display", "?"))
        icd = next(
            (
                cd.get("code")
                for cd in code.get("coding", [])
                if "icd-10" in cd.get("system", "").lower()
            ),
            "",
        )
        onset = c.get("onsetDateTime", c.get("onsetPeriod", {}).get("start", ""))
        abatement = c.get("abatementDateTime", "")
        conditions.append(
            {
                "id": c.get("id"),
                "status": status,
                "display": display,
                "icd10": icd,
                "onset": onset,
                "abatement": abatement,
            }
        )
    return json.dumps(
        {"total": bundle.get("total", len(conditions)), "conditions": conditions},
        ensure_ascii=False,
    )


@mcp.tool()
async def get_patient_medications(patient_id: str) -> str:
    """Busca todas as medicacoes de um paciente. Inclui medicacoes ativas e descontinuadas."""
    bundle = _fhir_get("/MedicationRequest", {"patient": patient_id, "_count": 100})
    medications = []
    for e in bundle.get("entry", []):
        m = e["resource"]
        med = m.get("medicationCodeableConcept", m.get("medicationReference", {}))
        display = med.get("text", med.get("coding", [{}])[0].get("display", "?"))
        status = m.get("status", "?")
        dosage = ""
        if m.get("dosageInstruction"):
            dosage = m["dosageInstruction"][0].get("text", "")
        medications.append(
            {"id": m.get("id"), "status": status, "medication": display, "dosage": dosage}
        )
    return json.dumps(
        {"total": bundle.get("total", len(medications)), "medications": medications},
        ensure_ascii=False,
    )


@mcp.tool()
async def get_patient_observations(patient_id: str, code: str = "", count: int = 20) -> str:
    """Busca observacoes laboratoriais e sinais vitais de um paciente. Filtro opcional por codigo LOINC (ex: 4548-4 para HbA1c)."""
    params = {"patient": patient_id, "_count": str(count), "_sort": "-date"}
    if code:
        params["code"] = code
    bundle = _fhir_get("/Observation", params)
    observations = []
    for e in bundle.get("entry", []):
        o = e["resource"]
        code_info = o.get("code", {})
        display = code_info.get("text", code_info.get("coding", [{}])[0].get("display", "?"))
        loinc = next(
            (
                cd.get("code")
                for cd in code_info.get("coding", [])
                if "loinc" in cd.get("system", "").lower()
            ),
            "",
        )
        vq = o.get("valueQuantity", {})
        value = vq.get("value")
        unit = vq.get("unit", "")
        date = o.get("effectiveDateTime", "")
        interpretation = ""
        if o.get("interpretation"):
            interpretation = o["interpretation"][0].get("coding", [{}])[0].get("code", "")
        component_summary = []
        for comp in o.get("component", []):
            cc = comp.get("code", {}).get("text", comp.get("code", {}).get("coding", [{}])[0].get("display", ""))
            cv = comp.get("valueQuantity", {})
            component_summary.append(f"{cc}: {cv.get('value', '?')} {cv.get('unit', '')}")
        obs_data = {
            "id": o.get("id"),
            "display": display,
            "loinc": loinc,
            "value": value,
            "unit": unit,
            "date": date,
            "interpretation": interpretation,
        }
        if component_summary:
            obs_data["components"] = component_summary
        observations.append(obs_data)
    return json.dumps(
        {"total": bundle.get("total", len(observations)), "observations": observations},
        ensure_ascii=False,
    )


@mcp.tool()
async def get_patient_allergies(patient_id: str) -> str:
    """Busca alergias e intolerancias de um paciente. Inclui tipo, criticalidade e reacoes."""
    bundle = _fhir_get("/AllergyIntolerance", {"patient": patient_id, "_count": 100})
    allergies = []
    for e in bundle.get("entry", []):
        a = e["resource"]
        code = a.get("code", {})
        display = code.get("text", code.get("coding", [{}])[0].get("display", "?"))
        reactions = []
        for rx in a.get("reaction", []):
            manifests = [m.get("text", m.get("coding", [{}])[0].get("display", "")) for m in rx.get("manifestation", [])]
            reactions.append({"manifestation": manifests, "severity": rx.get("severity", "")})
        allergies.append(
            {
                "id": a.get("id"),
                "type": a.get("type", ""),
                "category": a.get("category", []),
                "criticality": a.get("criticality", ""),
                "substance": display,
                "reactions": reactions,
            }
        )
    return json.dumps(
        {"total": bundle.get("total", len(allergies)), "allergies": allergies},
        ensure_ascii=False,
    )


@mcp.tool()
async def get_patient_encounters(patient_id: str, count: int = 10) -> str:
    """Busca encontros/consultas anteriores do paciente. Inclui tipo, data e status."""
    bundle = _fhir_get("/Encounter", {"patient": patient_id, "_count": str(count), "_sort": "-date"})
    encounters = []
    for e in bundle.get("entry", []):
        enc = e["resource"]
        types = [t.get("text", t.get("coding", [{}])[0].get("display", "")) for t in enc.get("type", [])]
        period = enc.get("period", {})
        encounters.append(
            {
                "id": enc.get("id"),
                "status": enc.get("status", ""),
                "type": types,
                "start": period.get("start", ""),
                "end": period.get("end", ""),
            }
        )
    return json.dumps(
        {"total": bundle.get("total", len(encounters)), "encounters": encounters},
        ensure_ascii=False,
    )


@mcp.tool()
async def create_observation(
    patient_id: str,
    code: str,
    display: str,
    value: float,
    unit: str,
    effective_date: str = "",
    category: str = "laboratory",
) -> str:
    """Cria uma nova observacao clinica para o paciente no FHIR Server. code = codigo LOINC, display = nome do exame, value = valor numerico, unit = unidade."""
    if not effective_date:
        effective_date = datetime.now(timezone.utc).isoformat().replace("+00:00", "+00:00")
    resource = {
        "resourceType": "Observation",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": category,
                    }
                ]
            }
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": code, "display": display}],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": effective_date,
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org"},
    }
    result = _fhir_post("Observation", resource)
    return json.dumps({"status": "created", "id": result.get("id"), "resource": f"Observation/{result.get('id')}"}, ensure_ascii=False)


@mcp.tool()
async def create_condition(
    patient_id: str,
    code: str,
    display: str,
    clinical_status: str = "active",
) -> str:
    """Cria uma nova condicao/doenca para o paciente no FHIR Server. code = codigo ICD-10, display = nome da condicao, clinical_status = active|resolved|recurrence."""
    resource = {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": clinical_status,
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }
            ]
        },
        "code": {
            "coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": code, "display": display}],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "recordedDate": datetime.now(timezone.utc).isoformat(),
    }
    result = _fhir_post("Condition", resource)
    return json.dumps({"status": "created", "id": result.get("id"), "resource": f"Condition/{result.get('id')}"}, ensure_ascii=False)


@mcp.tool()
async def create_questionnaire_response(
    patient_id: str,
    questions_responses: str,
) -> str:
    """Salva a triagem estruturada como QuestionnaireResponse no FHIR Server. questions_responses = JSON string com lista de {question, answer}."""
    try:
        qr_list = json.loads(questions_responses)
    except json.JSONDecodeError:
        return json.dumps({"error": "questions_responses deve ser JSON valido com lista de {question, answer}"})

    items = []
    for i, qr in enumerate(qr_list):
        items.append(
            {
                "linkId": f"q{i+1}",
                "text": qr.get("question", ""),
                "answer": [{"valueString": str(qr.get("answer", ""))}],
            }
        )

    resource = {
        "resourceType": "QuestionnaireResponse",
        "status": "completed",
        "subject": {"reference": f"Patient/{patient_id}"},
        "authored": datetime.now(timezone.utc).isoformat(),
        "item": items,
    }
    result = _fhir_post("QuestionnaireResponse", resource)
    return json.dumps({"status": "created", "id": result.get("id"), "resource": f"QuestionnaireResponse/{result.get('id')}"}, ensure_ascii=False)


@mcp.tool()
async def create_encounter(
    patient_id: str,
    reason: str,
    priority: str = "routine",
) -> str:
    """Cria um encontro pre-consulta no FHIR Server. reason = motivo da consulta, priority = routine|urgent|emergency."""
    priority_map = {
        "routine": "R",
        "urgent": "UR",
        "emergency": "EM",
    }
    resource = {
        "resourceType": "Encounter",
        "status": "planned",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "ambulatory",
        },
        "priority": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
                    "code": priority_map.get(priority, "R"),
                }
            ]
        },
        "type": [{"text": reason}],
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    result = _fhir_post("Encounter", resource)
    return json.dumps({"status": "created", "id": result.get("id"), "resource": f"Encounter/{result.get('id')}", "priority": priority}, ensure_ascii=False)


@mcp.tool()
async def create_flag_and_task(
    patient_id: str,
    flag_detail: str,
    task_detail: str,
    priority: str = "high",
) -> str:
    """Cria um alerta clinico (Flag) e uma tarefa de follow-up (Task) para o paciente no FHIR Server. flag_detail = descricao do alerta, task_detail = descricao da tarefa, priority = low|routine|urgent|high."""
    flag_resource = {
        "resourceType": "Flag",
        "status": "active",
        "code": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/flag-category",
                    "code": "clinical",
                    "display": "Clinical",
                }
            ],
            "text": flag_detail,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    flag_result = _fhir_post("Flag", flag_resource)

    task_resource = {
        "resourceType": "Task",
        "status": "requested",
        "intent": "order",
        "priority": priority,
        "description": task_detail,
        "for": {"reference": f"Patient/{patient_id}"},
    }
    task_result = _fhir_post("Task", task_resource)

    return json.dumps(
        {
            "flag": {"id": flag_result.get("id"), "resource": f"Flag/{flag_result.get('id')}"},
            "task": {"id": task_result.get("id"), "resource": f"Task/{task_result.get('id')}", "priority": priority},
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
