"""Shared vector-search knowledge base helpers (RAG) for the triage app.

Used by two consumers, which MUST stay symmetrical:
- ingest_knowledge.py — builds one canonical document per dataset case, embeds it,
  and stores it in IRIS (TriageAide.TriageKnowledge) alongside its ESI level.
- clinical_reasoning_server.py — builds the same style of document for the current
  patient, embeds it with the SAME model, and retrieves the most similar cases via
  IRIS VECTOR_COSINE.

Everything here degrades gracefully: any failure (IRIS down, table missing, embedding
provider unreachable) is logged and search_similar_cases() returns [], so the clinical
assessment keeps working exactly as before RAG was introduced.

Configuration (env):
  RAG_ENABLED         true|false (default true) — master switch, handy for A/B runs
  EMBEDDINGS_PROVIDER openai | ollama (default openai)
  EMBEDDINGS_MODEL    default: text-embedding-3-small (openai) / nomic-embed-text (ollama)
  OLLAMA_BASE_URL     default http://ollama:11434
  RAG_TOP_K           default 5
  RAG_MIN_SIMILARITY  default 0.50 (cosine; retrieved cases below this are discarded)
  RAG_AGE_WINDOW      default 0 (disabled). When > 0 and the patient's age is known,
                      retrieval is restricted to cases within +/- N years (hybrid
                      search: SQL filter + vector ranking)
  IRIS_HOST/IRIS_PORT/IRIS_NAMESPACE/IRIS_USERNAME/IRIS_PASSWORD — DB-API connection
"""

import hashlib
import os

from logging_config import setup_logging

logger = setup_logging("knowledge_base")

RAG_ENABLED = os.getenv("RAG_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
EMBEDDINGS_PROVIDER = os.getenv("EMBEDDINGS_PROVIDER", "openai").strip().lower()
_DEFAULT_MODELS = {"openai": "text-embedding-3-small", "ollama": "nomic-embed-text"}
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", _DEFAULT_MODELS.get(EMBEDDINGS_PROVIDER, "text-embedding-3-small"))
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
RAG_MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.50"))
RAG_AGE_WINDOW = int(os.getenv("RAG_AGE_WINDOW", "0"))

IRIS_HOST = os.getenv("IRIS_HOST", "iris")
IRIS_PORT = int(os.getenv("IRIS_PORT", "1972"))
IRIS_NAMESPACE = os.getenv("IRIS_NAMESPACE", "USER")
IRIS_USERNAME = os.getenv("IRIS_USERNAME", "_SYSTEM")
IRIS_PASSWORD = os.getenv("IRIS_PASSWORD", "SYS")

TABLE = "TriageAide.TriageKnowledge"

# Qualified model id stored with each row and validated at query time, so corpus and
# query vectors are guaranteed to come from the same embedding space.
MODEL_ID = f"{EMBEDDINGS_PROVIDER}/{EMBEDDINGS_MODEL}"

_embeddings = None
_query_cache = {}
_QUERY_CACHE_MAX = 256


def get_embeddings():
    """Lazy singleton for the embeddings client (OpenAI or Ollama)."""
    global _embeddings
    if _embeddings is None:
        if EMBEDDINGS_PROVIDER == "ollama":
            from langchain_community.embeddings import OllamaEmbeddings
            _embeddings = OllamaEmbeddings(model=EMBEDDINGS_MODEL, base_url=OLLAMA_BASE_URL)
        else:
            from langchain_openai import OpenAIEmbeddings
            _embeddings = OpenAIEmbeddings(model=EMBEDDINGS_MODEL)
        logger.info("Embeddings client initialized | model=%s", MODEL_ID)
    return _embeddings


def get_connection():
    """Open a DB-API connection to IRIS (intersystems-irispython)."""
    import iris
    return iris.connect(IRIS_HOST, IRIS_PORT, IRIS_NAMESPACE, IRIS_USERNAME, IRIS_PASSWORD)


def vector_to_sql(vector) -> str:
    """Serialize an embedding for TO_VECTOR(?, DOUBLE)."""
    return ",".join(repr(float(x)) for x in vector)


def embed_query(text: str):
    """Embed a query string, with a small in-process cache (the same patient context
    can be assessed more than once per session)."""
    key = hashlib.sha256(f"{MODEL_ID}|{text}".encode()).hexdigest()
    if key in _query_cache:
        return _query_cache[key]
    vector = get_embeddings().embed_query(text)
    if len(_query_cache) >= _QUERY_CACHE_MAX:
        _query_cache.clear()
    _query_cache[key] = vector
    return vector


def build_case_document(chief_complaint: str = "", vitals: str = "", labs: str = "",
                        notes: str = "", demographics: str = "") -> str:
    """Canonical document template. Corpus documents (ingestion) and patient queries
    (clinical_assessment) must both go through this template — format asymmetry
    between corpus and query is a classic cause of poor vector-search recall."""
    parts = []
    if demographics:
        parts.append(f"Patient: {demographics}.")
    if chief_complaint:
        parts.append(f"Chief complaint: {chief_complaint}.")
    if vitals:
        parts.append(f"Vitals: {vitals}.")
    if labs:
        parts.append(f"Labs: {labs}.")
    if notes:
        parts.append(f"Notes: {notes}")
    return " ".join(parts).strip()


def _stringify(value, max_len: int = 500) -> str:
    """Flatten a JSON fragment (list/dict/scalar) into compact text for embedding."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (list, tuple)):
        text = "; ".join(filter(None, (_stringify(v, max_len) for v in value)))
    elif isinstance(value, dict):
        text = "; ".join(f"{k}: {_stringify(v, max_len)}" for k, v in value.items() if v not in (None, "", [], {}))
    else:
        text = str(value)
    text = " ".join(text.split())
    return text[:max_len]


def _first_key(data: dict, keys) -> str:
    if not isinstance(data, dict):
        return ""
    lower = {str(k).lower(): k for k in data}
    for key in keys:
        if key in lower:
            value = _stringify(data[lower[key]])
            if value:
                return value
    return ""


def extract_age(ctx: dict):
    """Best-effort extraction of the patient's age (int) from the consolidated FHIR
    context, used for the optional hybrid age filter. Returns None when unknown."""
    raw = _first_key(ctx, ("age",)) or _first_key(ctx.get("demographics", {}) if isinstance(ctx, dict) else {}, ("age",))
    digits = "".join(c for c in raw if c.isdigit())[:3]
    return int(digits) if digits else None


def build_patient_query_document(ctx: dict, triage: dict) -> str:
    """Build the vector-search query for the current patient from the consolidated
    FHIR context and the triage results, using the canonical case template.

    Deliberately excludes the patient's name (noise + privacy); the embedded text is
    symptoms/conditions/vitals/labs, which is what the corpus documents contain."""
    symptoms = _first_key(triage, ("identified_symptoms", "symptoms"))
    red_flags = _first_key(triage, ("red_flags",))

    demographics_bits = []
    age = _first_key(ctx, ("age",)) or _first_key(ctx.get("demographics", {}) if isinstance(ctx, dict) else {}, ("age",))
    gender = _first_key(ctx, ("gender", "sex")) or _first_key(ctx.get("demographics", {}) if isinstance(ctx, dict) else {}, ("gender", "sex"))
    if age:
        demographics_bits.append(f"{age}-year-old" if age.isdigit() else age)
    if gender:
        demographics_bits.append(gender)
    demographics = " ".join(demographics_bits)

    vitals = _first_key(ctx, ("vitals", "vital_signs"))
    labs = _first_key(ctx, ("observations", "labs", "lab_results"))

    notes_bits = []
    conditions = _first_key(ctx, ("conditions", "active_conditions", "problems"))
    medications = _first_key(ctx, ("medications", "active_medications"))
    if conditions:
        notes_bits.append(f"Conditions: {conditions}")
    if medications:
        notes_bits.append(f"Medications: {medications}")
    if red_flags:
        notes_bits.append(f"Red flags: {red_flags}")

    return build_case_document(
        chief_complaint=symptoms,
        vitals=vitals,
        labs=labs,
        notes=". ".join(notes_bits),
        demographics=demographics,
    )


def search_similar_cases(query_text: str, top_k: int = None, min_similarity: float = None,
                         age: int = None) -> list:
    """Vector search over the knowledge base. Returns a list of dicts:
    {source_id, document, esi_level, similarity} sorted by similarity (desc).

    When `age` is given and RAG_AGE_WINDOW > 0, retrieval is restricted to cases
    within +/- RAG_AGE_WINDOW years (hybrid search: SQL filter + vector ranking).

    Never raises: on any failure it logs a warning and returns [] so the caller can
    proceed without RAG."""
    if not RAG_ENABLED or not query_text:
        return []
    top_k = top_k or RAG_TOP_K
    min_similarity = RAG_MIN_SIMILARITY if min_similarity is None else min_similarity
    try:
        vector = embed_query(query_text)
        where = ""
        params = [vector_to_sql(vector)]
        if age is not None and RAG_AGE_WINDOW > 0:
            where = "WHERE (Age IS NULL OR Age BETWEEN ? AND ?) "
            params += [age - RAG_AGE_WINDOW, age + RAG_AGE_WINDOW]
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT TOP {int(top_k)} SourceId, SourceDocument, ESILevel, EmbeddingModel, "
                f"VECTOR_COSINE(Embedding, TO_VECTOR(?, DOUBLE)) "
                f"FROM {TABLE} {where}ORDER BY 5 DESC",
                params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        cases = []
        for source_id, document, esi_level, row_model, similarity in rows:
            if row_model and row_model != MODEL_ID:
                logger.warning(
                    "Knowledge base was embedded with %s but the configured model is %s — "
                    "skipping RAG. Re-run ingest_knowledge.py with the current model.",
                    row_model, MODEL_ID,
                )
                return []
            if similarity is None or float(similarity) < min_similarity:
                continue
            logger.info("Vector search | match: id=%s document=%s, similarity=%s", source_id, document, similarity)
            cases.append({
                "source_id": source_id,
                "document": document or "",
                "esi_level": int(esi_level) if esi_level is not None else None,
                "similarity": round(float(similarity), 4),
            })
        logger.info("Vector search | retrieved=%d (top_k=%d, min_similarity=%.2f)",
                    len(cases), top_k, min_similarity)
        return cases
    except Exception as e:
        logger.warning("Vector search unavailable, continuing without RAG: %s: %s",
                       type(e).__name__, str(e)[:300])
        return []


_ESI_LABELS = {
    1: "ESI 1 — immediate, life-threatening",
    2: "ESI 2 — emergent, high risk",
    3: "ESI 3 — urgent",
    4: "ESI 4 — less urgent",
    5: "ESI 5 — non-urgent",
}


def format_cases_for_prompt(cases: list) -> str:
    """Render retrieved cases as a numbered plain-text block for the LLM prompt."""
    lines = []
    for i, case in enumerate(cases, 1):
        esi = _ESI_LABELS.get(case.get("esi_level"), f"ESI {case.get('esi_level')}")
        lines.append(f"Case {i} (similarity {case['similarity']:.2f}, {esi}):")
        lines.append(case["document"][:800])
    return "\n".join(lines)
