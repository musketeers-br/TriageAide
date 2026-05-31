import os
import warnings
import hashlib
import json
import re
import sqlite3
from functools import wraps
from dotenv import load_dotenv

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

load_dotenv(override=True)


def _normalize_cache_prompt(prompt_str):
    """Strip volatile fields from serialized messages so cache keys match across runs.

    Removes: response_metadata, usage_metadata, token_usage, OpenAI chatcmpl-* IDs,
    tool_call IDs, and lc message IDs — all of which change between identical invocations.
    """
    try:
        msgs = json.loads(prompt_str)
    except (json.JSONDecodeError, TypeError):
        return prompt_str
    normalized = []
    for msg in msgs:
        kwargs = msg.get("kwargs", {})
        kwargs.pop("response_metadata", None)
        kwargs.pop("usage_metadata", None)
        kwargs.pop("id", None)
        add_kwargs = kwargs.get("additional_kwargs", {})
        add_kwargs.pop("refusal", None)
        tool_calls = add_kwargs.get("tool_calls", [])
        for tc in tool_calls:
            tc.pop("id", None)
        if "tool_call_id" in add_kwargs:
            add_kwargs["tool_call_id"] = "__normalized__"
        msg["kwargs"] = kwargs
        normalized.append(msg)
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False)


def _get_llm_cache():
    cache_type = os.getenv("LLM_CACHE", "").lower()
    if cache_type == "sqlite":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from langchain_community.cache import SQLiteCache
            default_db_path = os.path.join(os.path.expanduser("~"), ".cache", "langchain_cache.db")
            db_path = os.getenv("LLM_CACHE_DB_PATH", default_db_path)
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            return _NormalizedSQLiteCache(database_path=db_path)
        except ImportError:
            print("WARNING: langchain-community not installed, LLM cache disabled")
            return None
    elif cache_type == "memory":
        from langchain_core.caches import InMemoryCache
        return InMemoryCache()
    return None


class _NormalizedSQLiteCache:
    """SQLiteCache wrapper that normalizes prompt keys to improve cache hit rates in agent flows."""

    def __init__(self, database_path):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from langchain_core.caches import BaseCache
            from langchain_community.cache import SQLiteCache
        self._inner = SQLiteCache(database_path=database_path)
        BaseCache.register(_NormalizedSQLiteCache)

    def lookup(self, prompt, llm_string):
        return self._inner.lookup(_normalize_cache_prompt(prompt), llm_string)

    async def alookup(self, prompt, llm_string):
        return await self._inner.alookup(_normalize_cache_prompt(prompt), llm_string)

    def update(self, prompt, llm_string, return_val):
        return self._inner.update(_normalize_cache_prompt(prompt), llm_string, return_val)

    async def aupdate(self, prompt, llm_string, return_val):
        return await self._inner.aupdate(_normalize_cache_prompt(prompt), llm_string, return_val)

    def clear(self, **kwargs):
        return self._inner.clear(**kwargs)


class ToolCache:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_cache (
                key TEXT PRIMARY KEY,
                content TEXT,
                artifact TEXT,
                is_tuple INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _make_key(self, tool_name, args):
        raw = json.dumps({"tool": tool_name, "args": args}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, tool_name, args):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT content, artifact, is_tuple FROM tool_cache WHERE key=?",
            (self._make_key(tool_name, args),),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        content = json.loads(row[0])
        if row[2]:
            artifact = json.loads(row[1])
            return (content, artifact)
        return content

    def set(self, tool_name, args, result):
        conn = sqlite3.connect(self.db_path)
        key = self._make_key(tool_name, args)
        if isinstance(result, tuple) and len(result) == 2:
            conn.execute(
                "INSERT OR REPLACE INTO tool_cache (key, content, artifact, is_tuple) VALUES (?, ?, ?, 1)",
                (key, json.dumps(result[0], ensure_ascii=False), json.dumps(result[1], ensure_ascii=False)),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO tool_cache (key, content, artifact, is_tuple) VALUES (?, ?, '', 0)",
                (key, json.dumps(result, ensure_ascii=False)),
            )
        conn.commit()
        conn.close()


def _get_tool_cache():
    if os.getenv("LLM_CACHE", "").lower() not in ("sqlite",):
        return None
    db_path = os.getenv("TOOL_CACHE_DB_PATH", os.path.join(os.path.expanduser("~"), ".cache", "tool_cache.db"))
    return ToolCache(db_path)


def _wrap_tools_with_cache(tools, tool_cache):
    if not tool_cache:
        return tools
    cached_tools = []
    for tool in tools:
        original_coroutine = getattr(tool, "coroutine", None)
        if original_coroutine is None:
            cached_tools.append(tool)
            continue
        tool_name = tool.name
        _cache = tool_cache

        async def cached_async(*args, __original=original_coroutine, __name=tool_name, __cache=_cache, **kwargs):
            cache_kwargs = {k: v for k, v in kwargs.items() if k not in ("config", "callbacks", "run_manager", "tool_call_id")}
            try:
                all_args = {"args": [str(a) for a in args], "kwargs": cache_kwargs}
                hit = __cache.get(__name, all_args)
            except (TypeError, ValueError):
                hit = None
                all_args = None
            if hit is not None:
                return hit
            result = await __original(*args, **kwargs)
            if all_args is not None:
                try:
                    __cache.set(__name, all_args, result)
                except (TypeError, ValueError):
                    pass
            return result

        tool.coroutine = cached_async
        cached_tools.append(tool)
    return cached_tools

SYSTEM_PROMPT = """\
# ROLE & CORE OBJECTIVE
You are the "Pre-Consultation Triage Agent", an autonomous agent specialized in intelligent clinical triage that operates ON FHIR data. Your objective is to prepare the consultation BEFORE the patient speaks with the healthcare professional.

You have access to three tool ecosystems (MCPs):
1. FHIRServer — Query and update FHIR resources on InterSystems IRIS for Health (Patient, Condition, Observation, MedicationRequest, AllergyIntolerance, Encounter, Flag, Task, QuestionnaireResponse)
2. TriageServer — Intelligent contextual triage (next question, parse symptoms, check red flags)
3. ClinicalReasoningServer — Clinical reasoning (assess risk, priority, summary, follow-up)

---

# LANGUAGE RULE — MANDATORY

You MUST communicate exclusively in English. All responses, questions, summaries, and clinical outputs must be in English. Do not use Portuguese or any other language.

---

# CONVERSATION RULES — MANDATORY & INFRACTIONABLE

1. Ask EXACTLY ONE question at a time to the patient. NEVER list multiple questions in the same message.
2. NEVER repeat a question that has already been answered. Track covered topics in covered_topics.
3. After asking a question, STOP and WAIT for the patient's answer. Do NOT ask more questions or advance steps.
4. For each question, call `get_next_triage_question(patient_context, covered_topics)` to get the next contextual question.
5. After the patient answers a question, add the topic of that question to covered_topics before asking the next one.
6. If `get_next_triage_question` returns question=null, do not ask more questions — proceed to STEP 3 (analysis).
7. NEVER ask about information already in the FHIR medical record — reference it: "I noticed in your record that you have [condition]..."
8. Formulate each question in a natural, welcoming, and conversational manner, as a healthcare professional would speak.
9. You MUST communicate exclusively in English — see LANGUAGE RULE above.
10. Use accessible language for the patient, avoiding technical jargon.

---

# OPERATIONAL WORKFLOW (5 MANDATORY STEPS)

Whenever the user provides a patient, you MUST follow this protocol:

## STEP 1 — FHIR Query (BEFORE conversation with the patient)
The agent NEVER starts by asking everything from scratch. FIRST query the FHIR Server:
1. If you have the NAME but not the ID, call `search_patients(name)` to find the patient and get the ID
2. Call `get_patient(patient_id)` to get demographic data
3. Call `get_patient_conditions(patient_id)` to understand active conditions
4. Call `get_patient_medications(patient_id)` to see active medications
5. Call `get_patient_observations(patient_id)` to see recent lab results
6. Call `get_patient_allergies(patient_id)` to check allergies
7. Call `get_patient_encounters(patient_id)` to see last visit

After collecting all data, build the patient_context JSON.

## STEP 2 — Intelligent Contextual Triage (ONE QUESTION AT A TIME)
1. Call `get_next_triage_question(patient_context, covered_topics=[])` to get the first question
2. Ask the patient the question in a natural and welcoming way. STOP and WAIT for the answer.
3. When the patient answers:
a. Call `parse_symptoms(patient_response)` to extract symptoms
b. Add the topic of the answered question to covered_topics
c. Call `get_next_triage_question(patient_context, covered_topics)` to get the next question
d. Ask the next question and WAIT for the answer. Repeat the cycle.
4. If `get_next_triage_question` returns question=null (no more questions), proceed to STEP 3.

Example of correct flow:
- Agent: "Maria, I noticed you have diabetes. Has your blood sugar been controlled?" [STOP and wait]
- Patient: "Not really, it's been high..."
- Agent: [parse_symptoms, then get_next_triage_question with covered_topics=["diabetes_control"]]
- Agent: "I understand. Have you noticed increased thirst or urination in recent days?" [STOP and wait]

## STEP 3 — Patient Response Analysis
After all triage questions have been answered:
1. Call `check_red_flags(symptoms, conditions)` to check for warning signs
2. If there are critical red flags, WARN the patient immediately and prioritize

## STEP 4 — Clinical Risk Reasoning
Cross-reference FHIR history + new symptoms:
1. Call `assess_clinical_risk(conditions, new_symptoms, observations, medications)` to assess risk
2. Call `suggest_priority(risk_assessment)` to determine priority
3. If high/critical risk, create alerts: `create_flag_and_task(patient_id, flag_detail, task_detail, priority)`

## STEP 5 — FHIR Update (Bidirectional)
Update the FHIR medical record with triage data:
1. Call `create_questionnaire_response(patient_id, questions_responses)` to save the triage
2. Call `create_encounter(patient_id, reason, priority)` to register the pre-consultation encounter
3. If there are relevant new symptoms, call `create_observation(...)` to record them
4. Call `generate_clinical_summary(patient_data, triage_data, risk_data)` to generate summary
5. Call `identify_follow_up_tasks(risk, conditions, gaps)` to identify next steps

---

# BUSINESS RULES & CONSTRAINTS
- ALWAYS query the FHIR Server BEFORE asking the patient questions
- NEVER ask about conditions already in the medical record — reference them
- ALWAYS check allergies before suggesting medications
- If you detect critical red flags (chest pain, bleeding in anticoagulated patient, suicidal ideation), warn IMMEDIATELY

---

# RESPONSE FORMAT
When concluding the triage, present the summary in the following format:

### Pre-Consultation Clinical Summary
- **Patient:** [name] ([age])
- **Active conditions:** [list]
- **Active medications:** [list]
- **Allergies:** [list]
- **New symptoms:** [list]
- **Risk:** [low/moderate/high/critical]
- **Priority:** [routine/urgent/emergency]

### FHIR Actions Performed
- [list of created/updated resources]

### Next Steps
- [list of follow-up tasks]
"""


def get_mcp_config():
    return {
        "fhir_server": {
            "transport": "http",
            "url": os.getenv("FHIR_MCP_URL", "http://localhost:8000/mcp"),
        },
        "triage_server": {
            "transport": "http",
            "url": os.getenv("TRIAGE_MCP_URL", "http://localhost:8001/mcp"),
        },
        "clinical_reasoning_server": {
            "transport": "http",
            "url": os.getenv("CR_MCP_URL", "http://localhost:8002/mcp"),
        },
    }


async def create_triage_agent():
    client = MultiServerMCPClient(get_mcp_config())

    all_tools = await client.get_tools()

    print(f"Total tools loaded: {len(all_tools)}")

    llm_cache = _get_llm_cache()
    tool_cache = _get_tool_cache()

    if llm_cache or tool_cache:
        print(f"Cache enabled: LLM={os.getenv('LLM_CACHE')}, Tools={'sqlite' if tool_cache else 'off'}")

    all_tools = _wrap_tools_with_cache(all_tools, tool_cache)

    model_kwargs = {}
    if llm_cache is not None:
        model_kwargs["cache"] = llm_cache
    model = ChatOpenAI(model="gpt-4o-mini", **model_kwargs)

    agent = create_agent(
        model,
        all_tools,
        system_prompt=SYSTEM_PROMPT,
    )

    return agent, client


def extract_ai_response(messages):
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content
    return None
