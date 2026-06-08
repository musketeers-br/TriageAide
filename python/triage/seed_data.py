import os
import json
import re
import requests
from pathlib import Path
from dotenv import load_dotenv
from logging_config import setup_logging

load_dotenv()

logger = setup_logging("seed_data")

FHIR_BASE = os.getenv("FHIR_BASE_URL", "http://localhost:32783/fhir/r4")
FHIR_USER = os.getenv("FHIR_USER", "_SYSTEM")
FHIR_PASS = os.getenv("FHIR_PASS", "SYS")

SEED_DIR = Path(__file__).parent / "seed_data"

PATIENT_TAG = "triage-seed"


def _auth():
    return (FHIR_USER, FHIR_PASS)


def _headers():
    return {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
    }


def _resolve_references(obj, uuid_map):
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k == "reference" and isinstance(v, str) and v.startswith("urn:uuid:"):
                uuid_key = v
                if uuid_key in uuid_map:
                    result[k] = f"Patient/{uuid_map[uuid_key]}"
                else:
                    result[k] = v
            else:
                result[k] = _resolve_references(v, uuid_map)
        return result
    elif isinstance(obj, list):
        return [_resolve_references(item, uuid_map) for item in obj]
    return obj


def _extract_id_from_location(location):
    m = re.search(r"/(\d+)/_history/", location)
    if m:
        return m.group(1)
    parts = location.rstrip("/").split("/")
    for p in parts:
        if p.isdigit():
            return p
    return "?"


def _create_resource(resource_type, resource):
    url = f"{FHIR_BASE}/{resource_type}"
    logger.debug("POST %s | resource id=%s", url, resource.get("id", "(new)"))
    resp = requests.post(
        url,
        json=resource,
        headers=_headers(),
        auth=_auth(),
        timeout=30,
    )
    if resp.status_code in (200, 201):
        location = resp.headers.get("Location", "")
        rid = _extract_id_from_location(location)
        if rid and rid != "?":
            logger.debug("Created %s/%s", resource_type, rid)
            return rid, None
        logger.warning("Created %s but could not extract ID from Location: %s", resource_type, location)
        return None, f"Created but could not extract ID from Location header: {location}"
    else:
        logger.error("Failed to create %s | HTTP %d: %s", resource_type, resp.status_code, resp.text[:200])
        return None, f"{resp.status_code}: {resp.text[:200]}"


def load_all():
    bundles = sorted(SEED_DIR.glob("patient_*.json"))
    if not bundles:
        logger.warning("No bundles found in %s", SEED_DIR)
        return

    logger.info("Loading %d bundle(s) into %s ...", len(bundles), FHIR_BASE)
    total_created = 0

    for bundle_path in bundles:
        logger.info("--- %s ---", bundle_path.name)
        with open(bundle_path, "r", encoding="utf-8") as f:
            bundle = json.load(f)

        uuid_map = {}
        patient_entries = []
        other_entries = []

        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            resource_type = resource.get("resourceType", "?")
            full_url = entry.get("fullUrl", "")
            if resource_type == "Patient":
                patient_entries.append((full_url, json.loads(json.dumps(resource))))
            else:
                other_entries.append((full_url, json.loads(json.dumps(resource))))

        for full_url, resource in patient_entries:
            resource.setdefault("meta", {})
            resource["meta"].setdefault("tag", [])
            if not any(t.get("code") == PATIENT_TAG for t in resource["meta"]["tag"]):
                resource["meta"]["tag"].append(
                    {
                        "system": "http://hospital.smarthealthit.org/tag",
                        "code": PATIENT_TAG,
                    }
                )
            rid, err = _create_resource("Patient", resource)
            if rid:
                name = _extract_name(resource)
                logger.info(" Patient/%s %s OK", rid, name)
                uuid_map[full_url] = rid
                total_created += 1
            else:
                logger.error(" Patient ERROR %s", err)

        for full_url, resource in other_entries:
            resolved = _resolve_references(resource, uuid_map)
            resource_type = resolved.get("resourceType", "?")
            rid, err = _create_resource(resource_type, resolved)
            if rid:
                logger.info(" %s/%s OK", resource_type, rid)
                total_created += 1
            else:
                logger.error(" %s ERROR %s", resource_type, err)

    logger.info("Total resources created: %d", total_created)


def clean():
    logger.info("Removing test resources tagged with '%s' ...", PATIENT_TAG)
    removed = 0

    for resource_type in ["Patient", "Condition", "Observation",
                          "MedicationRequest", "AllergyIntolerance",
                          "Encounter", "Flag", "Task",
                          "QuestionnaireResponse", "ClinicalImpression"]:
        url = f"{FHIR_BASE}/{resource_type}"
        params = {"_tag": PATIENT_TAG, "_count": 500}
        try:
            resp = requests.get(
                url, params=params, headers=_headers(), auth=_auth(), timeout=30
            )
            if resp.status_code != 200:
                continue
            bundle = resp.json()
            for entry in bundle.get("entry", []):
                rid = entry["resource"].get("id")
                del_url = f"{FHIR_BASE}/{resource_type}/{rid}"
                dr = requests.delete(del_url, headers=_headers(), auth=_auth(), timeout=15)
                if dr.status_code in (200, 204):
                    removed += 1
        except Exception:
            pass

    for resource_type in ["Condition", "Observation", "MedicationRequest",
                          "AllergyIntolerance", "Encounter", "Flag", "Task",
                          "QuestionnaireResponse", "ClinicalImpression"]:
        url = f"{FHIR_BASE}/{resource_type}"
        params = {"_count": 500}
        try:
            resp = requests.get(
                url, params=params, headers=_headers(), auth=_auth(), timeout=30
            )
            if resp.status_code != 200:
                continue
            bundle = resp.json()
            for entry in bundle.get("entry", []):
                res = entry["resource"]
                subject = res.get("subject", {}).get("reference", "")
                if subject.startswith("Patient/"):
                    pid = subject.split("/")[1]
                    pat_url = f"{FHIR_BASE}/Patient/{pid}"
                    pr = requests.get(pat_url, headers=_headers(), auth=_auth(), timeout=10)
                    if pr.status_code == 200:
                        pat = pr.json()
                        tags = pat.get("meta", {}).get("tag", [])
                        if any(t.get("code") == PATIENT_TAG for t in tags):
                            del_url = f"{FHIR_BASE}/{resource_type}/{res['id']}"
                            dr = requests.delete(del_url, headers=_headers(), auth=_auth(), timeout=15)
                            if dr.status_code in (200, 204):
                                removed += 1
        except Exception:
            pass

    logger.info("Resources removed: %d", removed)


def _extract_name(resource):
    names = resource.get("name", [])
    if names:
        n = names[0]
        return " ".join(n.get("given", [])) + " " + n.get("family", "")
    return ""


def list_seed_patients():
    url = f"{FHIR_BASE}/Patient"
    params = {"_tag": PATIENT_TAG, "_count": 50}
    resp = requests.get(url, params=params, headers=_headers(), auth=_auth(), timeout=30)
    if resp.status_code != 200:
        logger.error("Error %d: %s", resp.status_code, resp.text[:200])
        return

    bundle = resp.json()
    entries = bundle.get("entry", [])
    if not entries:
        logger.info("No test patients found.")
        return

    logger.info("Test patients (%d):", len(entries))
    for entry in entries:
        p = entry["resource"]
        name = _extract_name(p)
        logger.info(" id=%s %s gender=%s birthDate=%s", p['id'], name, p.get('gender'), p.get('birthDate'))


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "load"

    if cmd == "load":
        load_all()
    elif cmd == "clean":
        clean()
    elif cmd == "reload":
        clean()
        load_all()
    elif cmd == "list":
        list_seed_patients()
    else:
        logger.error("Usage: python seed_data.py [load|clean|reload|list]")
