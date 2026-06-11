"""Ingest the fedmml-ed-triage dataset into IRIS as a vector-searchable knowledge base.

Downloads the (synthetic) emergency-department triage dataset from Hugging Face,
builds one canonical text document per case, embeds documents in batches, and
upserts everything into TriageAide.TriageKnowledge via IRIS DB-API.

Run inside the triage container (it already has the Python stack and the .env):

    docker compose exec triage python3 ingest_knowledge.py --limit 1000

Idempotent: rows are keyed by the dataset row id (INSERT OR UPDATE), so re-running
refreshes data instead of duplicating it. Use --recreate to drop and rebuild the
table — required when switching to an embedding model with a different dimension.
"""

import argparse
import sys
from collections import Counter

from dotenv import load_dotenv

load_dotenv(override=True)

import knowledge_base as kb
from logging_config import setup_logging

logger = setup_logging("ingest_knowledge")

DEFAULT_DATASET = "olaflaitinen/fedmml-ed-triage"

# Best-effort column mapping: the dataset card is not machine-stable, so we probe
# common field names. Run with --inspect to print the actual schema and adjust.
ESI_KEYS = ("esi", "esi_level", "esi-level", "acuity", "triage_level", "triage_acuity", "label", "target")
COMPLAINT_KEYS = ("chief_complaint", "chiefcomplaint", "complaint", "presenting_complaint", "reason_for_visit", "reason")
NOTES_KEYS = ("clinical_notes", "notes", "note", "text", "narrative", "clinical_text", "history", "hpi", "description")
VITALS_BLOB_KEYS = ("vitals", "vital_signs")
VITALS_FIELDS = (
    ("heart_rate", "HR"), ("hr", "HR"), ("pulse", "HR"),
    ("respiratory_rate", "RR"), ("rr", "RR"),
    ("systolic_bp", "SBP"), ("sbp", "SBP"), ("diastolic_bp", "DBP"), ("dbp", "DBP"),
    ("blood_pressure", "BP"), ("bp", "BP"),
    ("spo2", "SpO2"), ("o2_sat", "SpO2"), ("oxygen_saturation", "SpO2"),
    ("temperature", "Temp"), ("temp", "Temp"),
    ("pain_score", "Pain"), ("pain", "Pain"),
)
AGE_KEYS = ("age", "patient_age")
GENDER_KEYS = ("gender", "sex", "patient_gender")


def _lower_map(row: dict) -> dict:
    return {str(k).lower(): k for k in row}


def _get(row: dict, lower: dict, keys) -> str:
    for key in keys:
        if key in lower:
            value = row[lower[key]]
            if value not in (None, ""):
                return kb._stringify(value, max_len=4000)
    return ""


def _parse_esi(raw: str):
    digits = [c for c in str(raw) if c.isdigit()]
    if not digits:
        return None
    esi = int(digits[0])
    return esi if 1 <= esi <= 5 else None


def map_row(row: dict, idx: int):
    """Map one dataset row to a knowledge-base record, or None if no usable ESI."""
    lower = _lower_map(row)

    esi = _parse_esi(_get(row, lower, ESI_KEYS))
    if esi is None:
        return None

    complaint = _get(row, lower, COMPLAINT_KEYS)
    notes = _get(row, lower, NOTES_KEYS)

    vitals = _get(row, lower, VITALS_BLOB_KEYS)
    if not vitals:
        bits, seen = [], set()
        for key, label in VITALS_FIELDS:
            if key in lower and label not in seen:
                value = kb._stringify(row[lower[key]], max_len=50)
                if value:
                    bits.append(f"{label} {value}")
                    seen.add(label)
        vitals = ", ".join(bits)

    demographics_bits = []
    age = _get(row, lower, AGE_KEYS)
    gender = _get(row, lower, GENDER_KEYS)
    if age:
        demographics_bits.append(f"{age}-year-old" if age.isdigit() else age)
    if gender:
        demographics_bits.append(gender)
    demographics = " ".join(demographics_bits)

    if not (complaint or notes):
        # Fall back to every textual field we haven't already used, so the case
        # still produces a meaningful document.
        used = set(ESI_KEYS) | set(COMPLAINT_KEYS) | set(NOTES_KEYS) | set(VITALS_BLOB_KEYS) \
            | {k for k, _ in VITALS_FIELDS} | set(AGE_KEYS) | set(GENDER_KEYS)
        notes = "; ".join(
            f"{k}: {kb._stringify(v, 300)}" for k, v in row.items()
            if str(k).lower() not in used and isinstance(v, str) and v.strip()
        )
        if not notes:
            return None

    document = kb.build_case_document(
        chief_complaint=complaint, vitals=vitals, notes=notes, demographics=demographics
    )
    source_id = _get(row, lower, ("id", "case_id", "encounter_id", "record_id", "patient_id")) or f"row-{idx}"
    return {
        "source_id": source_id[:200],
        "chief_complaint": complaint[:1000],
        "vitals": vitals[:1000],
        "clinical_notes": notes,
        "demographics": demographics[:500],
        "esi_level": esi,
        "document": document,
    }


def table_exists(cursor) -> bool:
    cursor.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = 'TriageAide' AND TABLE_NAME = 'TriageKnowledge'"
    )
    return cursor.fetchone()[0] > 0


def ensure_table(conn, dim: int, recreate: bool):
    cursor = conn.cursor()
    exists = table_exists(cursor)
    if exists and recreate:
        logger.info("Dropping %s (--recreate)", kb.TABLE)
        cursor.execute(f"DROP TABLE {kb.TABLE}")
        exists = False
    if not exists:
        logger.info("Creating %s with VECTOR(DOUBLE, %d)", kb.TABLE, dim)
        cursor.execute(f"""
            CREATE TABLE {kb.TABLE} (
                SourceId VARCHAR(200) NOT NULL UNIQUE,
                ChiefComplaint VARCHAR(1000),
                Vitals VARCHAR(1000),
                ClinicalNotes LONGVARCHAR,
                Demographics VARCHAR(500),
                ESILevel INTEGER,
                SourceDocument LONGVARCHAR,
                EmbeddingModel VARCHAR(200),
                Embedding VECTOR(DOUBLE, {dim})
            )
        """)
    conn.commit()


UPSERT_SQL = (
    f"INSERT OR UPDATE INTO {kb.TABLE} "
    "(SourceId, ChiefComplaint, Vitals, ClinicalNotes, Demographics, ESILevel, "
    "SourceDocument, EmbeddingModel, Embedding) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, TO_VECTOR(?, DOUBLE))"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Hugging Face dataset id")
    parser.add_argument("--split", default="train", help="Dataset split (default: train)")
    parser.add_argument("--limit", type=int, default=1000, help="Max rows to ingest (0 = all)")
    parser.add_argument("--batch-size", type=int, default=64, help="Embedding batch size")
    parser.add_argument("--recreate", action="store_true",
                        help="Drop and recreate the table (needed when the embedding dimension changes)")
    parser.add_argument("--inspect", action="store_true",
                        help="Print the dataset schema and the first mapped record, then exit")
    args = parser.parse_args()

    from datasets import load_dataset

    logger.info("Loading dataset %s (split=%s)...", args.dataset, args.split)
    try:
        dataset = load_dataset(args.dataset, split=args.split)
    except ValueError:
        dataset = next(iter(load_dataset(args.dataset).values()))
    logger.info("Dataset loaded | rows=%d | columns=%s", len(dataset), dataset.column_names)

    if args.inspect:
        print("Columns:", dataset.column_names)
        print("Features:", dataset.features)
        sample = dataset[0]
        print("First row:", {k: str(v)[:120] for k, v in sample.items()})
        print("Mapped record:", map_row(sample, 0))
        return 0

    rows = dataset if args.limit <= 0 else dataset.select(range(min(args.limit, len(dataset))))
    records, skipped = [], 0
    for idx, row in enumerate(rows):
        record = map_row(row, idx)
        if record is None:
            skipped += 1
        else:
            records.append(record)
    if not records:
        logger.error("No usable records mapped — run with --inspect and adjust the column mapping.")
        return 1
    logger.info("Mapped %d records (%d skipped without ESI/text)", len(records), skipped)

    embeddings = kb.get_embeddings()
    probe = embeddings.embed_query("dimension probe")
    dim = len(probe)
    logger.info("Embedding model %s | dimension=%d", kb.MODEL_ID, dim)

    conn = kb.get_connection()
    try:
        ensure_table(conn, dim, args.recreate)
        cursor = conn.cursor()
        inserted = 0
        esi_distribution = Counter()
        for start in range(0, len(records), args.batch_size):
            batch = records[start:start + args.batch_size]
            vectors = embeddings.embed_documents([r["document"] for r in batch])
            for record, vector in zip(batch, vectors):
                try:
                    cursor.execute(UPSERT_SQL, [
                        record["source_id"], record["chief_complaint"], record["vitals"],
                        record["clinical_notes"], record["demographics"], record["esi_level"],
                        record["document"], kb.MODEL_ID, kb.vector_to_sql(vector),
                    ])
                except Exception as e:
                    if "VECTOR" in str(e).upper():
                        logger.error(
                            "Vector insert failed — the table dimension likely does not match "
                            "the model dimension (%d). Re-run with --recreate. Error: %s", dim, e)
                        return 1
                    raise
                inserted += 1
                esi_distribution[record["esi_level"]] += 1
            conn.commit()
            logger.info("Progress: %d/%d", min(start + args.batch_size, len(records)), len(records))
    finally:
        conn.close()

    logger.info("Done | upserted=%d | skipped=%d | model=%s | dim=%d", inserted, skipped, kb.MODEL_ID, dim)
    logger.info("ESI distribution: %s", dict(sorted(esi_distribution.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
