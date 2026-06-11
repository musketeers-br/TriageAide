/// Vector-searchable triage knowledge base used by the Clinical Reasoning MCP server (RAG).
/// Rows are synthetic emergency-department triage cases from the Hugging Face dataset
/// olaflaitinen/fedmml-ed-triage, labeled with an Emergency Severity Index (ESI) level
/// assigned by clinical triage guidelines (1 = most critical, 5 = least urgent).
/// Populated by python/triage/ingest_knowledge.py (runs in the triage container and
/// connects over DB-API). The same canonical document template is used at ingestion
/// time and at query time — see python/triage/knowledge_base.py.
Class TriageAide.TriageKnowledge Extends %Persistent [ DdlAllowed ]
{

/// Stable identifier of the source row in the dataset (used for idempotent re-ingestion).
Property SourceId As %String(MAXLEN = 200) [ Required ];

Property ChiefComplaint As %String(MAXLEN = 1000);

/// Vital signs formatted as a short human-readable string (e.g. "HR 102, BP 140/90, SpO2 96%").
Property Vitals As %String(MAXLEN = 1000);

Property ClinicalNotes As %String(MAXLEN = "");

/// Short demographic descriptor (e.g. "67-year-old male").
Property Demographics As %String(MAXLEN = 500);

/// Emergency Severity Index: 1 = most critical, 5 = least urgent.
Property ESILevel As %Integer(MAXVAL = 5, MINVAL = 1);

/// The exact concatenated text that was embedded — kept for debugging and re-embedding.
Property SourceDocument As %String(MAXLEN = "");

/// Name of the embedding model that produced Embedding (e.g. "openai/text-embedding-3-small").
/// Validated at query time so corpus and query vectors always come from the same model.
Property EmbeddingModel As %String(MAXLEN = 200);

/// LEN must match the embedding model dimension (1536 = OpenAI text-embedding-3-small).
/// If you use a different model (e.g. Ollama nomic-embed-text = 768 dims), run
/// ingest_knowledge.py --recreate to rebuild this table with the right dimension.
Property Embedding As %Vector(DATATYPE = "DOUBLE", LEN = 1536);

Index SourceIdIdx On SourceId [ Unique ];

Index ESILevelIdx On ESILevel [ Type = bitmap ];

/// Remove all knowledge-base rows (the ingestion script can then repopulate from scratch).
ClassMethod Purge() As %Status
{
    return ..%KillExtent()
}

}
