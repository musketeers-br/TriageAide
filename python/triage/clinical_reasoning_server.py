import json
import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from logging_config import setup_logging

load_dotenv(override=True)

import knowledge_base as kb

logger = setup_logging("clinical_reasoning_server", "cr_server.log")

mcp = FastMCP("ClinicalReasoningServer")

_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, max_tokens=1200)

logger.info("Clinical Reasoning MCP Server initializing | model=gpt-4o-mini")


async def _llm_json(system_prompt: str, user_prompt: str, fallback: dict = None) -> str:
    logger.debug("LLM call | system_prompt_len=%d | user_prompt_len=%d", len(system_prompt), len(user_prompt))
    logger.debug("LLM call | user_prompt: %.500s", user_prompt)
    try:
        response = await _llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        content = response.content
        logger.debug("LLM response | raw_len=%d | first 500 chars: %.500s", len(content), content)
        if content.strip().startswith("```"):
            lines = content.strip().split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)
        parsed = json.loads(content)
        logger.debug("LLM response | parsed JSON keys=%s", list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__)
        return json.dumps(parsed, ensure_ascii=False)
    except json.JSONDecodeError:
        raw = response.content if 'response' in dir() else ""
        logger.warning("LLM returned invalid JSON | raw: %.300s", raw[:300])
        if fallback is not None:
            logger.info("Using fallback response")
            return json.dumps(fallback, ensure_ascii=False)
        return json.dumps({"error": "LLM returned invalid JSON", "raw": raw[:500]}, ensure_ascii=False)
    except Exception as e:
        logger.error("LLM call failed: %s: %s", type(e).__name__, str(e)[:300])
        if fallback is not None:
            logger.info("Using fallback response after error")
            return json.dumps(fallback, ensure_ascii=False)
        return json.dumps({"error": f"LLM call failed: {type(e).__name__}: {str(e)[:300]}"}, ensure_ascii=False)


_CA_SYSTEM = """You are a clinical reasoning specialist performing a comprehensive pre-consultation assessment.

Given the patient's full FHIR medical history and the triage data (identified symptoms, red flags), produce a complete assessment with four parts:

1. **Risk assessment** — Evaluate the patient's overall clinical risk by considering:
   - Chronic conditions and their severity/stability
   - New symptoms and their clinical significance
   - Abnormal lab observations and their implications
   - Active medications and potential interactions
   - Polypharmacy risk (4+ active medications)
   - Known dangerous combinations (e.g., warfarin + bleeding, depression + suicidal ideation)

   Assign a risk score (0-20 integer scale) and risk level:
   - 0-3: low
   - 4-6: moderate
   - 7-10: high
   - 11+: critical

   List each risk factor with a brief justification and its point contribution.

2. **Priority suggestion** — Based on the risk level, determine care priority:
   - routine — low risk, no red flags
   - urgent — moderate/high risk, red flags present but not critical
   - emergency — critical risk or critical red flags requiring immediate attention

   Provide a clinical justification for the priority level.

3. **Clinical summary** — A structured text summary for the physician covering:
   - Patient identification (name, ID, age, gender)
   - Active conditions
   - Active medications
   - Allergies
   - Abnormal lab results
   - New symptoms reported during triage
   - Red flags detected
   - Risk level and priority

4. **Follow-up tasks** — Specific clinical actions based on the full picture:
   - Each task with a priority (routine/urgent) and clinical reason
   - Include condition-specific monitoring (HbA1c for diabetes, INR for warfarin, BNP for HF, spirometry for COPD, etc.)
   - Include specialist referrals if needed
   - Include any gap-in-care resolutions

**Reference triage cases (RAG)** — The user prompt may include a "Reference triage cases" section: similar past triage cases retrieved by vector search from a knowledge base of SYNTHETIC emergency-department cases labeled per Emergency Severity Index (ESI) guidelines. Treat them as a calibration signal, NOT as ground truth for this patient.
- ESI is a 1-5 scale where 1 is the MOST critical and 5 is the LEAST urgent — note this is INVERTED relative to the 0-20 risk score above.
- Approximate mapping: ESI 1-2 → emergency, ESI 3 → urgent, ESI 4-5 → routine.
- Use the ESI levels of the most similar cases to calibrate the risk score and priority, but the patient's own FHIR history, red flags, and triage findings ALWAYS take precedence over reference cases.
- When reference cases influence your decision, cite them in the priority justification (e.g. "consistent with reference case 2, ESI 2").
- If the reference cases conflict with the patient's clinical picture, ignore them and say so briefly in the justification.

Return a JSON object:
{
  "risk": {
    "score": <integer 0-20>,
    "level": "<low|moderate|high|critical>",
    "factors": [{"factor": "<description>", "points": <integer>, "justification": "<brief reason>"}]
  },
  "priority": {
    "level": "<routine|urgent|emergency>",
    "label": "<Routine|Urgent|Emergency>",
    "justification": "<1-2 sentence clinical reasoning>"
  },
  "summary": "<structured text summary for the physician>",
  "follow_up_tasks": [{"task": "<action>", "priority": "<routine|urgent>", "reason": "<clinical reason>"}]
}"""


@mcp.tool()
async def clinical_assessment(
    patient_context: str,
    triage_data: str,
) -> str:
    """Performs a comprehensive pre-consultation clinical assessment including risk scoring, priority suggestion, clinical summary, and follow-up tasks. patient_context = JSON with full patient FHIR data (conditions, medications, observations, allergies, demographics). triage_data = JSON with triage results (identified_symptoms, red_flags, covered_topics)."""
    logger.info("clinical_assessment | context_len=%d | triage_data_len=%d", len(patient_context), len(triage_data))
    try:
        ctx = json.loads(patient_context)
    except (json.JSONDecodeError, TypeError):
        ctx = {}

    try:
        triage = json.loads(triage_data)
    except (json.JSONDecodeError, TypeError):
        triage = {}

    ctx_summary = json.dumps(ctx, ensure_ascii=False)[:3000]
    triage_summary = json.dumps(triage, ensure_ascii=False)[:2000]

    # RAG: retrieve similar (synthetic) triage cases from IRIS via vector search.
    # search_similar_cases never raises — on any failure it returns [] and the
    # assessment proceeds exactly as it did before RAG existed.
    reference_cases = []
    rag_section = ""
    if kb.RAG_ENABLED:
        query_doc = kb.build_patient_query_document(ctx, triage)
        logger.debug("RAG query document: %.300s", query_doc)
        reference_cases = kb.search_similar_cases(query_doc)
        if reference_cases:
            rag_section = (
                "\n\nReference triage cases (vector search over a synthetic ESI-labeled "
                "knowledge base, most similar first):\n"
                + kb.format_cases_for_prompt(reference_cases)
            )

    user_prompt = f"""Patient FHIR data:
{ctx_summary}

Triage data:
{triage_summary}{rag_section}

Perform a comprehensive clinical assessment. Return JSON with risk, priority, summary, and follow_up_tasks."""

    fallback = {
        "risk": {"score": 0, "level": "low", "factors": []},
        "priority": {"level": "routine", "label": "Routine", "justification": "Assessment failed, defaulting to routine."},
        "summary": "Clinical assessment could not be completed due to an error.",
        "follow_up_tasks": [],
    }

    result = await _llm_json(_CA_SYSTEM, user_prompt, fallback=fallback)

    # Attach the retrieved cases to the tool output for traceability (visible in the
    # Gradio trace panel and LangSmith), with documents trimmed to keep output lean.
    if reference_cases:
        try:
            data = json.loads(result)
            if isinstance(data, dict):
                data["reference_cases"] = [
                    {
                        "source_id": c["source_id"],
                        "esi_level": c["esi_level"],
                        "similarity": c["similarity"],
                        "document": c["document"][:300],
                    }
                    for c in reference_cases
                ]
                result = json.dumps(data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    logger.info("clinical_assessment | result risk=%s priority=%s | rag_cases=%d",
                json.loads(result).get("risk", {}).get("level", "?") if result else "?",
                json.loads(result).get("priority", {}).get("level", "?") if result else "?",
                len(reference_cases))
    return result


if __name__ == "__main__":
    logger.info("Starting Clinical Reasoning MCP Server on port 8002...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8002)
