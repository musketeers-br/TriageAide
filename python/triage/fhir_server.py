import os
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastmcp import FastMCP
from logging_config import setup_logging

load_dotenv()

logger = setup_logging("fhir_server", "fhir_server.log")

mcp = FastMCP("FHIRServer")

FHIR_BASE = os.getenv("FHIR_BASE_URL", "http://localhost:32783/fhir/r4")
FHIR_USER = os.getenv("FHIR_USER", "_SYSTEM")
FHIR_PASS = os.getenv("FHIR_PASS", "SYS")

logger.info("FHIR Server MCP initializing | FHIR_BASE=%s | user=%s", FHIR_BASE, FHIR_USER)


def _fhir_get(path: str, params: dict = None) -> dict:
    url = f"{FHIR_BASE}{path}"
    logger.debug("GET %s | params=%s", url, json.dumps(params or {}, default=str))
    try:
        resp = requests.get(
            url,
            params=params or {},
            headers={"Accept": "application/fhir+json"},
            auth=(FHIR_USER, FHIR_PASS),
            timeout=30,
        )
        logger.debug("GET %s => %d (%d bytes)", url, resp.status_code, len(resp.text))
        resp.raise_for_status()
        data = resp.json()
        if "total" in data:
            logger.debug("GET %s | bundle total=%d entries=%d", path, data.get("total", "?"), len(data.get("entry", [])))
        return data
    except requests.exceptions.HTTPError as e:
        logger.error("GET %s => HTTP %d: %s", url, resp.status_code, resp.text[:500])
        raise
    except requests.exceptions.RequestException as e:
        logger.error("GET %s => connection error: %s", url, e)
        raise


def _fhir_post(resource_type: str, resource: dict) -> dict:
    url = f"{FHIR_BASE}/{resource_type}"
    logger.debug("POST %s | resource id=%s", url, resource.get("id", "(new)"))
    try:
        resp = requests.post(
            url,
            json=resource,
            headers={
                "Content-Type": "application/fhir+json",
                "Accept": "application/fhir+json",
            },
            auth=(FHIR_USER, FHIR_PASS),
            timeout=30,
        )
        logger.debug("POST %s => %d | Location=%s", url, resp.status_code, resp.headers.get("Location", ""))
        resp.raise_for_status()
        location = resp.headers.get("Location", "")
        rid = ""
        parts = location.split("/")
        for i, p in enumerate(parts):
            if p == resource_type and i + 1 < len(parts):
                rid = parts[i + 1]
                break
        logger.info("Created %s/%s", resource_type, rid or "?")
        if resp.text and resp.headers.get("Content-Type", "").startswith("application/json"):
            body = resp.json()
            logger.debug("POST %s/%s | response body: %s", resource_type, rid, json.dumps(body, ensure_ascii=False)[:500])
            return body
        return {"id": rid, "resourceType": resource_type}
    except requests.exceptions.HTTPError as e:
        logger.error("POST %s => HTTP %d: %s", url, resp.status_code, resp.text[:500])
        raise
    except requests.exceptions.RequestException as e:
        logger.error("POST %s => connection error: %s", url, e)
        raise


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
    """Search for patients by name (partial, case-insensitive). Use this tool WHEN YOU DO NOT HAVE the patient ID, only the name. Returns list of patients with ID, name, and date of birth."""
    logger.info("search_patients | name=%s", name)
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
    logger.info("search_patients | found=%d", len(patients))
    return json.dumps({"total": len(patients), "patients": patients}, ensure_ascii=False)


@mcp.tool()
async def get_patient(patient_id: str) -> str:
    """Retrieves demographic data for a patient by ID. Returns name, gender, date of birth, and identifiers."""
    logger.info("get_patient | patient_id=%s", patient_id)
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
    """Retrieves all conditions/diseases for a patient. Returns active and resolved conditions with ICD-10 codes."""
    logger.info("get_patient_conditions | patient_id=%s", patient_id)
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
    """Retrieves all medications for a patient. Includes active and discontinued medications."""
    logger.info("get_patient_medications | patient_id=%s", patient_id)
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
    """Retrieves laboratory observations and vital signs for a patient. Optional filter by LOINC code (e.g. 4548-4 for HbA1c)."""
    logger.info("get_patient_observations | patient_id=%s | code=%s | count=%d", patient_id, code or "(all)", count)
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
    """Retrieves allergies and intolerances for a patient. Includes type, criticality, and reactions."""
    logger.info("get_patient_allergies | patient_id=%s", patient_id)
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
    """Retrieves previous encounters/visits for the patient. Includes type, date, and status."""
    logger.info("get_patient_encounters | patient_id=%s | count=%d", patient_id, count)
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
    patient_id: str, code: str, display: str, value: float, unit: str, effective_date: str = "", category: str = "laboratory",
) -> str:
    """Creates a new clinical observation for the patient on the FHIR Server. code = LOINC code, display = test name, value = numeric value, unit = unit of measure."""
    logger.info("create_observation | patient_id=%s | code=%s | display=%s | value=%s %s", patient_id, code, display, value, unit)
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
    patient_id: str, code: str, display: str, clinical_status: str = "active",
) -> str:
    """Creates a new condition/disease for the patient on the FHIR Server. code = ICD-10 code, display = condition name, clinical_status = active|resolved|recurrence."""
    logger.info("create_condition | patient_id=%s | code=%s | display=%s | status=%s", patient_id, code, display, clinical_status)
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
    patient_id: str, questions_responses: str,
) -> str:
    """Saves the structured triage as QuestionnaireResponse on the FHIR Server. questions_responses = JSON string with list of {question, answer} or JSON from build_questionnaire_response_data (which wraps items in {patient_id, items, total})."""
    logger.info("create_questionnaire_response | patient_id=%s", patient_id)
    try:
        parsed = json.loads(questions_responses)
    except json.JSONDecodeError:
        return json.dumps({"error": "questions_responses must be valid JSON with list of {question, answer}"})

    if isinstance(parsed, dict) and "items" in parsed:
        qr_list = parsed["items"]
    elif isinstance(parsed, list):
        qr_list = parsed
    else:
        return json.dumps({"error": "questions_responses must be a list of {question, answer} or {items: [...]} object"})

    items = []
    for i, qr in enumerate(qr_list):
        if isinstance(qr, dict):
            q_text = qr.get("question", "")
            a_text = str(qr.get("answer", ""))
        else:
            q_text = str(qr)
            a_text = ""
        items.append(
            {
                "linkId": f"q{i+1}",
                "text": q_text,
                "answer": [{"valueString": a_text}],
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
    patient_id: str, reason: str, priority: str = "routine",
) -> str:
    """Creates a pre-consultation encounter on the FHIR Server. reason = reason for visit, priority = routine|urgent|emergency."""
    logger.info("create_encounter | patient_id=%s | reason=%s | priority=%s", patient_id, reason[:80], priority)
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
    patient_id: str, flag_detail: str, task_detail: str, priority: str = "high",
) -> str:
    """Creates a clinical alert (Flag) and a follow-up task (Task) for the patient on the FHIR Server. flag_detail = alert description, task_detail = task description, priority = low|routine|urgent|high."""
    logger.info("create_flag_and_task | patient_id=%s | priority=%s | flag=%s", patient_id, priority, flag_detail[:80])
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
    logger.info("Starting FHIR MCP Server on port 8000...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
