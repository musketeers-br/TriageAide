import json
import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv(override=True)

mcp = FastMCP("ClinicalReasoningServer")

_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, max_tokens=1200)


async def _llm_json(system_prompt: str, user_prompt: str, fallback: dict = None) -> str:
    try:
        response = await _llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        content = response.content
        if content.strip().startswith("```"):
            lines = content.strip().split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)
        parsed = json.loads(content)
        return json.dumps(parsed, ensure_ascii=False)
    except json.JSONDecodeError:
        raw = response.content if 'response' in dir() else ""
        if fallback is not None:
            return json.dumps(fallback, ensure_ascii=False)
        return json.dumps({"error": "LLM returned invalid JSON", "raw": raw[:500]}, ensure_ascii=False)
    except Exception as e:
        if fallback is not None:
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

    user_prompt = f"""Patient FHIR data:
{ctx_summary}

Triage data:
{triage_summary}

Perform a comprehensive clinical assessment. Return JSON with risk, priority, summary, and follow_up_tasks."""

    fallback = {
        "risk": {"score": 0, "level": "low", "factors": []},
        "priority": {"level": "routine", "label": "Routine", "justification": "Assessment failed, defaulting to routine."},
        "summary": "Clinical assessment could not be completed due to an error.",
        "follow_up_tasks": [],
    }

    return await _llm_json(_CA_SYSTEM, user_prompt, fallback=fallback)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8002)
