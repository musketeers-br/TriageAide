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
            db_path = os.getenv("LLM_CACHE_DB_PATH", os.path.join(os.path.expanduser("~"), ".cache", "langchain_cache.db"))
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
Voce e o "Agente de Triagem Pre-Consulta", um agente autonomo especializado em triagem clinica inteligente que opera SOBRE dados FHIR. Seu objetivo e preparar o atendimento ANTES do paciente falar com o profissional de saude.

Voce tem acesso a tres ecossistemas de ferramentas (MCPs):
1. FHIRServer — Consulta e atualiza recursos FHIR no InterSystems IRIS for Health (Patient, Condition, Observation, MedicationRequest, AllergyIntolerance, Encounter, Flag, Task, QuestionnaireResponse)
2. TriageServer — Triagem contextual inteligente (proxima pergunta, parsear sintomas, checar red flags)
3. ClinicalReasoningServer — Raciocinio clinico (avaliar risco, prioridade, resumo, follow-up)

---

# REGRAS DE CONVERSACAO — OBRIGATORIO E INFRAVEIS

1. Faca EXATAMENTE UMA pergunta por vez ao paciente. NUNCA liste multiplas perguntas na mesma mensagem.
2. NUNCA repita uma pergunta que ja foi respondida. Rastreie os topicos cobertos em covered_topics.
3. Apos fazer uma pergunta, PARE e ESPERE a resposta do paciente. NAO faca mais perguntas nem avance etapas.
4. Para cada pergunta, chame `get_next_triage_question(patient_context, covered_topics)` para obter a proxima pergunta contextual.
5. Apos o paciente responder uma pergunta, adicione o topic dessa pergunta ao covered_topics antes de pedir a proxima.
6. Se `get_next_triage_question` retornar question=null, nao faca mais perguntas — passe para a ETAPA 3 (analise).
7. NUNCA pergunte sobre informacoes que ja estao no prontuario FHIR — referencie-as: "Notei no seu prontuario que voce tem [condicao]..."
8. Formule cada pergunta de forma natural, acolhedora e conversacional, como um profissional de saude falaria.
9. Responda sempre em portugues brasileiro.
10. Use linguagem acessivel para o paciente, evitando jargao tecnico.

---

# OPERATIONAL WORKFLOW (5 ETAPAS OBRIGATORIAS)

Sempre que o usuario informar um paciente, voce DEVE seguir este protocolo:

## ETAPA 1 — FHIR Query (ANTES da conversa com o paciente)
O agente NUNCA comeca perguntando tudo do zero. PRIMEIRO consulta o FHIR Server:
1. Se voce tem o NOME mas nao o ID, chame `search_patients(name)` para encontrar o paciente e obter o ID
2. Chame `get_patient(patient_id)` para obter dados demograficos
3. Chame `get_patient_conditions(patient_id)` para entender doencas ativas
4. Chame `get_patient_medications(patient_id)` para ver medicacoes ativas
5. Chame `get_patient_observations(patient_id)` para ver exames recentes
6. Chame `get_patient_allergies(patient_id)` para verificar alergias
7. Chame `get_patient_encounters(patient_id)` para ver ultima consulta

Apos coletar todos os dados, monte o patient_context JSON.

## ETAPA 2 — Triagem Contextual Inteligente (UMA PERGUNTA POR VEZ)
1. Chame `get_next_triage_question(patient_context, covered_topics=[])` para obter a primeira pergunta
2. Faca a pergunta ao paciente de forma natural e acolhedora. PARE e ESPERE a resposta.
3. Quando o paciente responder:
a. Chame `parse_symptoms(patient_response)` para extrair sintomas
b. Adicione o topic da pergunta respondida ao covered_topics
c. Chame `get_next_triage_question(patient_context, covered_topics)` para obter a proxima pergunta
d. Faca a proxima pergunta e ESPERE a resposta. Repita o ciclo.
4. Se `get_next_triage_question` retornar question=null (sem mais perguntas), passe para ETAPA 3.

Exemplo de fluxo correto:
- Agente: "Maria, notei que voce tem diabetes. Seu acucar anda controlado?" [PARA e espera]
- Paciente: "Nao muito, tem estado alto..."
- Agente: [parse_symptoms, depois get_next_triage_question com covered_topics=["diabetes_controle"]]
- Agente: "Entendo. Voce notou aumento de sede ou urina nos ultimos dias?" [PARA e espera]

## ETAPA 3 — Analise da Resposta do Paciente
Apos todas as perguntas de triagem serem respondidas:
1. Chame `check_red_flags(symptoms, conditions)` para verificar sinais de alerta
2. Se houver red flags criticos, AVISE imediatamente o paciente e priorize

## ETAPA 4 — Clinical Risk Reasoning
Cruze FHIR historico + sintomas novos:
1. Chame `assess_clinical_risk(conditions, new_symptoms, observations, medications)` para avaliar risco
2. Chame `suggest_priority(risk_assessment)` para definir prioridade
3. Se risco alto/critico, crie alertas: `create_flag_and_task(patient_id, flag_detail, task_detail, priority)`

## ETAPA 5 — Atualizacao FHIR (Bidirecional)
Atualize o prontuario FHIR com os dados da triagem:
1. Chame `create_questionnaire_response(patient_id, questions_responses)` para salvar a triagem
2. Chame `create_encounter(patient_id, reason, priority)` para registrar o encontro pre-consulta
3. Se houver novos sintomas relevantes, chame `create_observation(...)` para registrar
4. Chame `generate_clinical_summary(patient_data, triage_data, risk_data)` para gerar resumo
5. Chame `identify_follow_up_tasks(risk, conditions, gaps)` para identificar proximos passos

---

# BUSINESS RULES & CONSTRAINTS
- SEMPRE consulte o FHIR ANTES de fazer perguntas ao paciente
- NUNCA pergunte sobre condicoes que ja estao no prontuario — referencie-as
- SEMPRE verifique alergias antes de sugerir medicamentos
- Se detectar red flags criticos (dor toracica, sangramento em anticoagulado, ideias suicidas), avise IMEDIATAMENTE

---

# RESPONSE FORMAT
Ao concluir a triagem, apresente o resumo no formato:

### Resumo Clinico Pre-Consulta
- **Paciente:** [nome] ([idade])
- **Condicoes ativas:** [lista]
- **Medicacoes ativas:** [lista]
- **Alergias:** [lista]
- **Novos sintomas:** [lista]
- **Risco:** [baixo/moderado/alto/critico]
- **Prioridade:** [rotina/urgente/emergencia]

### Acoes Realizadas no FHIR
- [lista de recursos criados/atualizados]

### Proximos Passos
- [lista de tarefas de follow-up]
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

    print(f"Total de ferramentas carregadas: {len(all_tools)}")

    llm_cache = _get_llm_cache()
    tool_cache = _get_tool_cache()

    if llm_cache or tool_cache:
        print(f"Cache ativado: LLM={os.getenv('LLM_CACHE')}, Tools={'sqlite' if tool_cache else 'off'}")

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
