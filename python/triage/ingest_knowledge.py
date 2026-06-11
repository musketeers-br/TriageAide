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

# Exact dataset schema (see the dataset card "Data Instances"):
#   encounter_id, patient_id, site_id, country, age, sex, arrival_timestamp,
#   chief_complaint, clinical_notes,
#   systolic_bp, diastolic_bp, heart_rate, respiratory_rate, temperature, spo2, pain_score,
#   wbc, hemoglobin, platelet_count, sodium, potassium, creatinine, glucose,
#   troponin, bnp, lactate, inr,
#   esi_level
# site_id/country/arrival_timestamp are federated-learning artifacts and are not embedded.

VITAL_FIELDS = (
    ("heart_rate", "HR"),
    ("respiratory_rate", "RR"),
    ("temperature", "Temp"),
    ("spo2", "SpO2"),
)

LAB_FIELDS = (
    ("wbc", "WBC"),
    ("hemoglobin", "Hb"),
    ("platelet_count", "Plt"),
    ("sodium", "Na"),
    ("potassium", "K"),
    ("creatinine", "Cr"),
    ("glucose", "Glucose"),
    ("troponin", "Troponin"),
    ("bnp", "BNP"),
    ("lactate", "Lactate"),
    ("inr", "INR"),
)


def _num(value) -> str:
    """Render a numeric field compactly ('102.0' -> '102', '37.8' stays)."""
    if value is None or value == "":
        return ""
    try:
        f = float(value)
        return str(int(f)) if f == int(f) else str(round(f, 2))
    except (TypeError, ValueError):
        return str(value).strip()


def format_vitals(row: dict) -> str:
    bits = []
    sbp, dbp = _num(row.get("systolic_bp")), _num(row.get("diastolic_bp"))
    if sbp and dbp:
        bits.append(f"BP {sbp}/{dbp}")
    for key, label in VITAL_FIELDS:
        value = _num(row.get(key))
        if value:
            bits.append(f"{label} {value}%" if label == "SpO2" else f"{label} {value}")
    pain = _num(row.get("pain_score"))
    if pain:
        bits.append(f"Pain {pain}/10")
    return ", ".join(bits)


def format_labs(row: dict) -> str:
    bits = []
    for key, label in LAB_FIELDS:
        value = _num(row.get(key))
        if value:
            bits.append(f"{label} {value}")
    return ", ".join(bits)


def _parse_esi(raw):
    digits = [c for c in str(raw) if c.isdigit()]
    if not digits:
        return None
    esi = int(digits[0])
    return esi if 1 <= esi <= 5 else None


def map_row(row: dict, idx: int):
    """Map one dataset row to a knowledge-base record, or None if no usable ESI."""
    esi = _parse_esi(row.get("esi_level"))
    if esi is None:
        return None

    complaint = kb._stringify(row.get("chief_complaint"), 1000)
    notes = kb._stringify(row.get("clinical_notes"), 4000)
    vitals = format_vitals(row)
    labs = format_labs(row)

    age = None
    try:
        age = int(row.get("age")) if row.get("age") not in (None, "") else None
    except (TypeError, ValueError):
        pass
    sex = kb._stringify(row.get("sex"), 20)
    demographics_bits = []
    if age is not None:
        demographics_bits.append(f"{age}-year-old")
    if sex:
        demographics_bits.append(sex)
    demographics = " ".join(demographics_bits)

    if not (complaint or notes):
        return None

    document = kb.build_case_document(
        chief_complaint=complaint, vitals=vitals, labs=labs, notes=notes,
        demographics=demographics,
    )
    source_id = kb._stringify(row.get("encounter_id"), 200) or f"row-{idx}"
    return {
        "source_id": source_id,
        "age": age,
        "sex": sex,
        "chief_complaint": complaint,
        "vitals": vitals[:1000],
        "labs": labs[:2000],
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
                Age INTEGER,
                Sex VARCHAR(20),
                ChiefComplaint VARCHAR(1000),
                Vitals VARCHAR(1000),
                Labs VARCHAR(2000),
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
    "(SourceId, Age, Sex, ChiefComplaint, Vitals, Labs, ClinicalNotes, Demographics, "
    "ESILevel, SourceDocument, EmbeddingModel, Embedding) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TO_VECTOR(?, DOUBLE))"
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
                        record["source_id"], record["age"], record["sex"],
                        record["chief_complaint"], record["vitals"], record["labs"],
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
