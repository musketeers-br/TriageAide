_A vector-search knowledge base of past clinical assessments, running on InterSystems IRIS, gives the LLM a deterministic calibration signal — making its triage reasoning faster, more structured, and clinically defensible._

---

## The Problem with Probabilistic Medicine

The LLM answered correctly. But would it answer the same way for the next patient with the same profile? Same conditions, same medications, same symptoms — would the risk score drift? Would the priority shift from "emergency" to "urgent"? Would the follow-up tasks be different?

This is the fundamental limitation of pure LLM reasoning: it is **probabilistic by nature**. The same input can produce different outputs across sessions, model versions, or even temperature settings. In clinical decision support, variability is not just an inconvenience — it is a liability. An assessment that cannot be reproduced is an assessment that cannot be trusted.

The solution: give the LLM a library of past clinical assessments, retrieved by deterministic similarity, as a calibration signal. The LLM still reasons. But now it reasons with reference cases in context — cases that were **mathematically** selected, not recalled from training data.

---

## Vector Search: Why InterSystems IRIS

If the LLM itself were asked to "recall a similar patient," it would fabricate one — plausible-sounding, internally consistent, and entirely fictional. That is not recall; it is hallucination by proxy.

Vector cosine similarity does not hallucinate. It is a deterministic mathematical operation: given two embeddings, compute the cosine of the angle between them. The result is always the same for the same vectors. There is no temperature, no sampling, no drift.

InterSystems IRIS for Health supports the `%Vector` data type natively, alongside the `VECTOR_COSINE()` SQL function. This means the FHIR server that holds the patient's longitudinal record also hosts the vector-search knowledge base — no second database, no separate vector index, no ETL pipeline. The triage agent queries both through a single connection.

---

## The Knowledge Base Schema

The data schema is defined in `TriageAide.TriageKnowledge`, an IRIS persistent class:

| Column | Type | Purpose |
|---|---|---|
| `SourceId` | `%String(MAXLEN=200)` | Encounter ID, unique key for idempotent upsert |
| `Age` | `%Integer` | Structured age for optional hybrid SQL pre-filter |
| `Sex` | `%String(MAXLEN=20)` | "M" or "F" |
| `ChiefComplaint` | `%String(MAXLEN=1000)` | Chief complaint text |
| `Vitals` | `%String(MAXLEN=1000)` | Formatted: "BP 165/95, HR 102, RR 22, Temp 37.8, SpO2 94%, Pain 7/10" |
| `Labs` | `%String(MAXLEN=2000)` | Formatted: "WBC 11.2, Troponin 0.12, BNP 280" |
| `ClinicalNotes` | `%String(MAXLEN="")` | Raw clinical notes |
| `Demographics` | `%String(MAXLEN=500)` | "67-year-old male" |
| `ESILevel` | `%Integer(MINVAL=1, MAXVAL=5)` | Emergency Severity Index (1=critical, 5=non-urgent) |
| `SourceDocument` | `%String(MAXLEN="")` | The exact text that was embedded |
| `EmbeddingModel` | `%String(MAXLEN=200)` | Model id, validated at query time |
| `Embedding` | `%Vector(DOUBLE, LEN=1536)` | The vector (1536 dims for OpenAI; 768 for Ollama) |

The `EmbeddingModel` column stores which model produced each vector — `openai/text-embedding-3-small` or `ollama/nomic-embed-text` — and is validated at query time. This prevents the silent failure of querying a 1536-dimensional space with 768-dimensional vectors.

---

## Synthetic Dataset

The knowledge base is derived from the [`olaflaitinen/fedmml-ed-triage`](https://huggingface.co/datasets/olaflaitinen/fedmml-ed-triage) dataset on Hugging Face — a synthetic emergency-department triage dataset labeled per Emergency Severity Index (ESI) guidelines. Because the original dataset requires an acceptance agreement, we generated a complementary synthetic dataset using LLM instructions that preserve the original schema while producing patients that align with our existing test profiles. This makes it easy for anyone to try the application without licensing friction, while still testing the quality of the vector search.

The synthetic patients map to the original test profiles as follows:

| Base Patient Profile | Clinical Criteria | Generated Patient | Simulated Data Equivalency |
|---|---|---|---|
| Ana Costa | Mild symptoms, zero red flags, ESI 5 | Lucas Almeida & Juliana Ribeiro | Stable vitals (SpO2 99-100%), labs NULL, ESI 5 |
| Maria Silva | Uncontrolled T2DM, high CV risk, ESI 3 | Carlos Oliveira | BP 158/92, Glucose 245, Troponin alert, ESI 3 |
| Roberto Lima | Severe respiratory distress, ESI 2 | Sandra Souza | SpO2 88%, WBC 13.2, tachypnea, ESI 2 |
| Joao Santos | Hypercomplex geriatric, multiorgan failure, ESI 1-2 | Francisco Souza & Tereza Menezes | Highly abnormal BNP/Cr/Troponin, ESI 1-2 |

Having ESI-1 through ESI-5 in the knowledge base gives the LLM a concrete scale to calibrate against. When the agent retrieves a case labeled ESI 2 (emergent), it reinforces the urgency of the current patient's situation.

---

## Architecture

The RAG step lives inside the `clinical_assessment()` tool on the **ClinicalReasoningServer** MCP (:8002). The flow is:

```
FHIR Query → Contextual Triage → Red Flags → Vector Search → Clinical Assessment + RAG → FHIR Update
```

Two files implement it:

**`knowledge_base.py`** — Shared helpers used symmetrically at ingestion and query time:

```python
def build_case_document(chief_complaint="", vitals="", labs="", notes="", demographics=""):
    """Canonical document template — MUST be identical for corpus and query."""
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
```

This function is called with each dataset row during ingestion to produce the embedded document, and again with the current patient's data at query time. Template symmetry is critical — format mismatch between corpus and query is a classic cause of recall collapse.

The vector search itself is a SQL query using IRIS's native `VECTOR_COSINE()`:

```python
cursor.execute(f"""
    SELECT TOP {top_k} SourceId, SourceDocument, ESILevel, EmbeddingModel,
           VECTOR_COSINE(Embedding, TO_VECTOR(?, DOUBLE))
    FROM TriageAide.TriageKnowledge
    ORDER BY 5 DESC
""", [vector_to_sql(query_vector)])
```

**`clinical_reasoning_server.py`** — The consumer. When `RAG_ENABLED` is true, `build_patient_query_document()` constructs a query from the patient's FHIR context and triage data (deliberately excluding the patient's name — noise + privacy), feeds it to `search_similar_cases()`, and injects the results as a "Reference triage cases" section in the LLM prompt.

Every failure path in the pipeline — IRIS unreachable, table missing, embedding provider down, model mismatch — logs a warning and returns `[]`. The clinical assessment proceeds exactly as it did before RAG was introduced. This enables safe A/B testing: flip `RAG_ENABLED=false`, restart, and compare outputs.

---

## Walkthrough: Joao Santos — With RAG vs. Without

Joao Santos is the complex cardiovascular patient from the first article: chronic heart failure, atrial fibrillation, type 2 diabetes, hypertension, CKD stage 3, on warfarin. He reports trouble breathing at night and swollen legs.

The triage interaction is identical in both scenarios — the agent asks about chest pain, Joao declines further questions and requests the clinical assessment. The difference is in what happens next.

### Without the Knowledge Base (61.1s)

```
⏱ 61.1s

assistant: ### Pre-Consultation Clinical Summary
- **Patient:** Joao Santos (68)
- **Active conditions:** Chronic heart failure, Atrial fibrillation, ...
- **Risk:** Critical
- **Priority:** Emergency

### FHIR Actions Performed
- [Flag created for critical condition, Emergency consultation task created,
  INR monitoring task created, Renal function monitoring task created,
  Diabetes management review task created, Medication review task created]

### Next Steps
- Immediate cardiology consultation for heart failure management.
- Monitor INR closely due to warfarin therapy.
- ...
```

The assessment is correct — but the FHIR actions are collapsed into a single bullet with no structure, and the response takes **over a minute**.

### With the Knowledge Base (36.8s)

```
⏱ 36.8s

assistant: ### Pre-Consultation Clinical Summary
- **Patient:** Joao Santos (68)
- **Active conditions:** Chronic heart failure, Atrial fibrillation, ...
- **Risk:** Critical
- **Priority:** Emergency

### FHIR Actions Performed
- Created a new encounter for the emergency consultation.
- Flag created for critical risk factors.
- Task created for immediate cardiology consultation.
- Task to monitor INR and renal function closely.
- Task to adjust diabetes management plan.
- Task to evaluate and optimize heart failure medications.

### Next Steps
- Immediate cardiology consultation ...
- Close monitoring of INR and renal function (creatinine) ...
- Adjust diabetes management plan ...
- Evaluate and optimize heart failure medications ...
```

Two differences stand out:

1. **Structured output** — Each FHIR action is a distinct, numbered bullet with a clear verb. The no-RAG version collapsed everything into a single run-on line. The RAG version organizes them into discrete, actionable items.

2. **40% faster** — 36.8s vs 61.1s. The reference cases pre-load the LLM's reasoning path, reducing the search space for decision-making. The model spends less time "figuring out what to do" because the retrieved cases show it what an ESI-2 assessment looks like.

### Why? The Vector Search Logs

When the RAG pipeline runs, the server logs show exactly which cases were retrieved:

```
triage-app  | Vector search | match: id=ENC3005438
  document=Patient: 74-year-old F. Chief complaint: Altered mental status.
  Vitals: BP 102/54, HR 95, RR 22, Temp 36.2, SpO2 93%, Pain 5/10.
  Labs: WBC 8.9, Hb 10.1, Plt 150, Na 135, K 5.2, Cr 3.1, Glucose 198,
  Troponin 0.09, BNP 410, Lactate 3.2, INR 1.2.
  Notes: Tereza Menezes, history of ischemic cardiomyopathy (low EF),
  stage 3 CKD, and diabetes. High suspicion of acute decompensated heart failure.
  similarity=0.61

triage-app  | Vector search | match: id=ENC3005437
  document=Patient: 68-year-old M. Chief complaint: Severe dyspnea.
  Vitals: BP 162/98, HR 110, RR 26, Temp 36.4, SpO2 89%, Pain 8/10.
  Labs: WBC 10.5, Hb 11.2, Plt 165, Na 134.1, K 4.9, Cr 2.6, Glucose 138,
  Troponin 0.14, BNP 580, Lactate 2.4, INR 2.9.
  Notes: Francisco Souza, history of CHF, chronic AFib on anticoagulants, and CKD.
  similarity=0.60

triage-app  | Vector search | match: id=ENC3005434
  document=Patient: 55-year-old M. Chief complaint: Diabetic foot ulcer.
  Vitals: BP 158/92, HR 85, RR 18, Temp 36.9, SpO2 97%, Pain 4/10.
  Labs: WBC 11.5, Hb 14.1, Plt 280, Na 136, K 4.4, Cr 1.4, Glucose 245,
  Troponin 0.03, INR 1.
  Notes: Carlos Oliveira, presenting with numbness in lower extremities ...
  similarity=0.57

triage-app  | Vector search | match: id=ENC3005435
  document=Patient: 62-year-old F. Chief complaint: Shortness of breath.
  Vitals: BP 135/85, HR 121, RR 27, Temp 37.1, SpO2 88%, Pain 6/10.
  Labs: WBC 13.2, Hb 11.9, Plt 195, Na 140.2, K 3.9, Cr 0.9, Glucose 110,
  Troponin 0.02, Lactate 2.1, INR 1.
  Notes: Sandra Souza, presenting with acute respiratory distress ...
  similarity=0.51

triage-app  | Vector search | retrieved=4 (top_k=5, min_similarity=0.50)
```

The top two matches — **Tereza Menezes** (similarity 0.61) and **Francisco Souza** (similarity 0.60) — both present with acute decompensated heart failure on a background of cardiomyopathy, CKD, and diabetes. Both are labeled ESI 2 (emergent). The vector search didn't need to "understand" that Joao has CHF, AFib, and CKD. It mathematically found the nearest neighbors in embedding space, and those neighbors clustered around exactly his clinical profile.

These cases are injected into the LLM's system prompt as a "Reference triage cases" section, with explicit instructions:

> *Treat reference cases as a calibration signal, NOT as ground truth. The patient's own FHIR history, red flags, and triage findings ALWAYS take precedence. Use the ESI levels of the most similar cases to calibrate the risk score and priority.*

The result: the LLM produces a more structured, more decisive assessment — and produces it faster.

---

## Why This Matters

The improvement is not just about latency or formatting. It is about **defensibility**.

When a clinician reads the RAG-assisted assessment and asks "why emergency priority?", there is an answer beyond "the LLM said so": *"Because the most similar case in the knowledge base — a 68-year-old male with CHF, AFib, and CKD presenting with severe dyspnea and orthopnea — was classified ESI 2 (emergent). The retrieved case can be inspected, its ESI label validated, and the similarity score reproduced."*

This is the difference between a black box and an auditable system. Vector search provides a provenance chain: which case was retrieved, how similar it was, and what label it carried. The LLM still performs the reasoning — but it does so with a deterministic anchor.

---

## Conclusion

A knowledge base of past clinical assessments, powered by InterSystems IRIS vector search, transforms the LLM triage agent from a standalone probabilistic reasoner into a hybrid system: deterministic retrieval + probabilistic reasoning. The same FHIR server that stores the patient's longitudinal record also hosts the vector index. The same SQL connection that queries conditions and medications also runs `VECTOR_COSINE()`. No second database. No external vector store. No deployment complexity.

The result is faster, more structured, and clinically defensible assessments. And every component — the FHIR server, the vector search, the MCP architecture, the LangChain agent — is independently replaceable and testable.

The gap between probabilistic LLM reasoning and the reproducibility requirements of clinical medicine is real. With InterSystems IRIS as both the FHIR foundation and the vector search engine, that gap is closable — today.

---

### Footnote

_This article was developed with the assistance of Artificial Intelligence tools for drafting and language refinement. All technical validation and final review were performed by the author._
