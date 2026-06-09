import json
import os
import time
from dotenv import load_dotenv
from fastmcp import FastMCP
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from logging_config import setup_logging

load_dotenv(override=True)

logger = setup_logging("triage_server", "triage_server.log")

mcp = FastMCP("TriageServer")

_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, max_tokens=800)

logger.info("Triage MCP Server initializing | model=gpt-4o-mini")


_session_state: dict[str, dict] = {}

_SESSION_TTL = 3600


def _get_session(patient_id: str) -> dict:
    now = time.time()
    expired = [k for k, v in _session_state.items() if now - v.get("_ts", 0) > _SESSION_TTL]
    for k in expired:
        del _session_state[k]
    if patient_id not in _session_state:
        _session_state[patient_id] = {
            "covered_topics": [],
            "questions_asked": [],
            "last_question": None,
            "last_topic": None,
            "conversation_log": [],
            "_ts": now,
        }
    session = _session_state[patient_id]
    session["_ts"] = now
    return session


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


_Q_SYSTEM = """You are a pre-consultation triage nurse deciding the next question to ask a patient.

Given the patient's FHIR medical history, the topics already covered in conversation, the conversation so far, and optionally the patient's initial message, determine the NEXT most important question to ask.

Rules:
- If the patient's initial message already states their reason for visit or symptoms, do NOT ask "How are you feeling today?" — instead, acknowledge what they shared and ask the first relevant condition-specific follow-up.
- Ask about the most clinically urgent topic first: red-flag symptoms related to existing conditions, then condition control, then medication side effects, then general changes.
- Reference a condition from the FHIR record at most ONCE — in the first question where it becomes relevant. After that, ask follow-up questions naturally without re-stating the condition name. The patient already knows.
- Do not repeat a topic that is already in covered_topics, unless the patient's answer was unclear or incomplete and you need to clarify.
- ABSOLUTELY DO NOT ask a question that was already asked in the conversation history below. If the patient already answered a question about a symptom (even partially), move on to the next topic. Re-asking the same question makes the conversation feel robotic and frustrating.
- Be empathetic and concise. The patient may be unwell — avoid repetitive phrasing that makes the conversation feel robotic or tiresome.
- Formulate the question in a natural, welcoming, conversational manner — as a healthcare professional would speak to a patient.
- Each question should cover exactly ONE clinical topic.
- Vary your phrasing. Never use the same sentence structure or wording as a previous question in the conversation.

Return a JSON object with:
- "question": the question text (string or null if no more questions)
- "topic": a short snake_case identifier for the topic (string or null)
- "remaining_topics": list of topic identifiers still to cover after this one
- "total_remaining": count of remaining topics after this one"""


_A_SYSTEM = """You are a clinical assistant extracting structured symptom data from a patient's response during pre-consultation triage.

Given the patient's free-text response and their FHIR medical context, extract:

1. **Symptoms** — identify each symptom mentioned. Use standard clinical terminology:
   - "dizzy" → "dizziness"
   - "thirsty" / "really thirsty" / "drinking a lot" → "excessive thirst"
   - "can't breathe" / "hard to breathe" / "out of breath" → "shortness of breath"
   - "heart racing" / "heart fluttering" → "palpitation"
   - "swollen legs" / "ankle swelling" → "leg swelling"
   - "blurry vision" / "vision changes" → "blurred vision"
   - "feeling down" / "sad" → "sadness"
   - "can't sleep" / "trouble sleeping" → "insomnia"
   - "want to hurt myself" / "thoughts of giving up" → "suicidal ideation"
   - "coughing more" / "cough got worse" → "worsening cough"
   - "tired" / "exhausted" / "no energy" → "fatigue"
   - Apply the same logic for Portuguese: "sede" → "excessive thirst", "falta de ar" → "shortness of breath", "tontura" → "dizziness", etc.

2. **Category** — classify each symptom: cardiovascular, respiratory, metabolic, neurological, mental, general

3. **Severity** — mild, moderate, or severe based on descriptors and clinical context:
   - "very", "severe", "unbearable", "worsening", "really", "a lot" → severe
   - "mild", "slight", "little", "a bit" → mild
   - Otherwise → moderate

4. **Negation** — "no chest pain" or "haven't felt dizzy" means the symptom is ABSENT. Do NOT include negated symptoms.

5. **Duration** — extract if mentioned (e.g., "for 3 days", "since last week")

6. **Overall severity** — the highest severity among identified symptoms, or "mild" if no symptoms found.

Return a JSON object:
{
  "raw_response": "<first 200 chars of response>",
  "identified_symptoms": [{"symptom": "<standard term>", "category": "<category>", "severity": "<mild|moderate|severe>"}],
  "duration": "<extracted duration or empty string>",
  "overall_severity": "<mild|moderate|severe>"
}"""


_RF_SYSTEM = """You are a clinical safety officer checking for red flags (warning signs) in a pre-consultation triage.

Given the patient's current symptoms, active conditions, and active medications, identify dangerous clinical combinations that require urgent attention.

Check for these known high-risk combinations AND any other clinically significant ones:
- Chest pain + heart failure / hypertension / atrial fibrillation
- Shortness of breath + heart failure / COPD / asthma
- Bleeding + warfarin / anticoagulant
- Suicidal ideation + depression / antidepressants
- Excessive thirst / blurred vision + diabetes (possible poor control)
- Dizziness + hypertension / atrial fibrillation / antihypertensives
- Leg swelling + heart failure / hypertension
- Worsening cough + COPD / heart failure / ACE inhibitors
- Confusion + diabetes (possible hypoglycemia) / heart failure
- Severe fatigue + heart failure / diabetes / depression
- Any drug-symptom interaction beyond the list above

For each alert, classify the risk as:
- "critical" — requires immediate emergency attention (chest pain, active bleeding on anticoagulant, suicidal ideation, severe respiratory distress)
- "elevated" — needs urgent follow-up but not immediately life-threatening

Return a JSON object:
{
  "alerts": [
    {
      "red_flag": "<brief description of the dangerous combo>",
      "symptom": "<the symptom involved>",
      "related_condition_or_medication": "<the condition or medication involved>",
      "risk": "<elevated|critical>",
      "explanation": "<1-2 sentence clinical reasoning>"
    }
  ],
  "has_critical_red_flag": <true if any alert has risk="critical">,
  "alert_count": <number of alerts>
}"""


@mcp.tool()
async def get_next_triage_question(
    patient_context: str,
    covered_topics: list[str] = [],
    patient_initial_message: str = "",
    patient_id: str = "",
    conversation_history: str = "",
) -> str:
    """Returns the NEXT triage question (one at a time) based on FHIR history, already covered topics, and optionally the patient's initial message. If the initial message already states the reason for visit, the tool skips the generic opener and goes directly to condition-specific questions. patient_context = JSON with patient data. covered_topics = list of already answered topics. patient_initial_message = the patient's first message to the agent (optional). patient_id = the patient's FHIR ID (required for session tracking to prevent repetitive questions). conversation_history = brief summary of Q&A so far, e.g. "Q: difficulty breathing? A: No trouble breathing" (optional but strongly recommended to prevent repetition)."""
    logger.info("get_next_triage_question | patient_id=%s | covered_topics=%s | initial_msg=%.80s | conv_history_len=%d", patient_id, covered_topics, patient_initial_message[:80] if patient_initial_message else "", len(conversation_history) if conversation_history else 0)
    try:
        ctx = json.loads(patient_context)
    except json.JSONDecodeError:
        return json.dumps({"error": "patient_context must be valid JSON"}, ensure_ascii=False)

    caller_topics = covered_topics or []

    session_covered = []
    session_conversation = []
    if patient_id:
        session = _get_session(patient_id)
        session_covered = session.get("covered_topics", [])
        session_conversation = session.get("conversation_log", [])
        merged_covered = list(dict.fromkeys(session_covered + caller_topics))
    else:
        merged_covered = caller_topics

    if conversation_history:
        all_conversation = "\n".join(session_conversation + [conversation_history])
    else:
        all_conversation = "\n".join(session_conversation)

    ctx_summary = json.dumps(ctx, ensure_ascii=False)[:2000]
    conv_section = ""
    if all_conversation.strip():
        conv_section = f"""
Conversation so far (DO NOT repeat any question already asked below):
{all_conversation.strip()}
"""

    user_prompt = f"""Patient FHIR context:
{ctx_summary}

Covered topics: {json.dumps(merged_covered)}

Patient's initial message: {patient_initial_message or "(not provided)"}
{conv_section}
Determine the next question to ask. If a topic was already covered in the conversation above, do NOT ask about it again. Return JSON with question, topic, remaining_topics, total_remaining."""

    fallback = {
        "question": None,
        "topic": None,
        "remaining_topics": [],
        "total_remaining": 0,
    }

    result = await _llm_json(_Q_SYSTEM, user_prompt, fallback=fallback)
    logger.debug("get_next_triage_question | result: %.200s", result[:200])

    try:
        parsed = json.loads(result)
        topic = parsed.get("topic")
        question = parsed.get("question")
        if patient_id and topic and question:
            session = _get_session(patient_id)
            if topic not in session["covered_topics"]:
                session["covered_topics"].append(topic)
            session["questions_asked"].append({"question": question, "topic": topic})
            session["last_question"] = question
            session["last_topic"] = topic
            if conversation_history:
                session["conversation_log"].append(conversation_history)
            logger.info("Session updated | patient_id=%s | covered_topics=%s | total_asked=%d", patient_id, session["covered_topics"], len(session["questions_asked"]))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Could not update session state: %s", e)

    return result


@mcp.tool()
async def analyze_patient_response(
    patient_response: str,
    patient_context: str = "{}",
    patient_id: str = "",
    last_question_topic: str = "",
) -> str:
    """Extracts and structures symptoms, duration, and severity from the patient's response using clinical reasoning. Handles synonyms, Portuguese, negation, and clinical context. patient_response = free text of the patient's response. patient_context = JSON with patient data (optional, for clinical context). patient_id = the patient's FHIR ID (optional, used for session tracking to mark topics as covered). last_question_topic = the topic of the last question asked (optional, used to mark the topic as answered in the session)."""
    logger.info("analyze_patient_response | patient_id=%s | topic=%s | response=%.100s", patient_id, last_question_topic, patient_response[:100])
    try:
        ctx = json.loads(patient_context)
    except (json.JSONDecodeError, TypeError):
        ctx = {}

    ctx_summary = json.dumps(ctx, ensure_ascii=False)[:1500]
    user_prompt = f"""Patient medical context:
{ctx_summary}

Patient's response: {patient_response}

Extract structured symptom data from this response. Return JSON with raw_response, identified_symptoms, duration, overall_severity."""

    fallback = {
        "raw_response": patient_response[:200],
        "identified_symptoms": [],
        "duration": "",
        "overall_severity": "mild",
    }

    result = await _llm_json(_A_SYSTEM, user_prompt, fallback=fallback)
    logger.debug("analyze_patient_response | result: %.300s", result[:300])

    if patient_id and last_question_topic:
        session = _get_session(patient_id)
        if last_question_topic not in session["covered_topics"]:
            session["covered_topics"].append(last_question_topic)
        qa_entry = f"Q topic: {last_question_topic} | A: {patient_response[:200]}"
        session["conversation_log"].append(qa_entry)
        logger.info("Session updated after analyze | patient_id=%s | covered_topics=%s", patient_id, session["covered_topics"])

    return result


@mcp.tool()
async def check_red_flags(
    symptoms: list | str,
    conditions: list | str,
    medications: list | str | None = None,
) -> str:
    """Checks warning signs (red flags) by cross-referencing current symptoms with existing conditions and active medications using clinical reasoning. Detects drug-symptom interactions. symptoms = JSON list of identified symptoms (from analyze_patient_response). conditions = JSON list of active conditions. medications = JSON list of medications (optional but recommended for drug interaction detection)."""
    logger.info("check_red_flags | symptoms=%d | conditions=%d | medications=%s", 
                len(symptoms) if isinstance(symptoms, list) else 1,
                len(conditions) if isinstance(conditions, list) else 1,
                len(medications) if isinstance(medications, list) else 0)
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
            cond_list = []
        elif isinstance(conditions, str):
            cond_list = json.loads(conditions)
        else:
            cond_list = conditions
    except json.JSONDecodeError:
        cond_list = [{"display": str(conditions)}]

    try:
        if medications is None:
            med_list = []
        elif isinstance(medications, str):
            med_list = json.loads(medications)
        else:
            med_list = medications
    except json.JSONDecodeError:
        med_list = []

    user_prompt = f"""Identified symptoms:
{json.dumps(symptom_list, ensure_ascii=False)[:1500]}

Active conditions:
{json.dumps(cond_list, ensure_ascii=False)[:1500]}

Active medications:
{json.dumps(med_list, ensure_ascii=False)[:1500]}

Check for red flags and dangerous combinations. Return JSON with alerts, has_critical_red_flag, alert_count."""

    fallback = {
        "alerts": [],
        "has_critical_red_flag": False,
        "alert_count": 0,
    }

    result = await _llm_json(_RF_SYSTEM, user_prompt, fallback=fallback)
    logger.info("check_red_flags | alerts=%d | critical=%s",
                json.loads(result).get("alert_count", 0) if result else 0,
                json.loads(result).get("has_critical_red_flag", False) if result else False)
    return result


@mcp.tool()
async def build_questionnaire_response_data(
    patient_id: str,
    questions: list,
    answers: list,
) -> str:
    """Builds data structure for FHIR QuestionnaireResponse ready to be saved. questions = JSON list of questions, answers = JSON list of answers (same order)."""
    logger.info("build_questionnaire_response_data | patient_id=%s | questions=%d", patient_id, len(questions) if isinstance(questions, list) else 1)
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


@mcp.tool()
async def reset_triage_session(patient_id: str) -> str:
    """Clears the triage session state for a patient, including covered topics and conversation log. Call this when starting a new patient triage to ensure a clean state. patient_id = the patient's FHIR ID."""
    logger.info("reset_triage_session | patient_id=%s", patient_id)
    if patient_id in _session_state:
        del _session_state[patient_id]
        logger.info("Session cleared for patient_id=%s", patient_id)
    return json.dumps({"status": "ok", "patient_id": patient_id, "message": "Session state cleared"}, ensure_ascii=False)


if __name__ == "__main__":
    logger.info("Starting Triage MCP Server on port 8001...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)
