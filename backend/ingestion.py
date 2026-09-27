"""
Ingestion pipeline: CSV -> raw_records -> (after mapping is confirmed)
normalized_records -> import-time matching -> master_entities.

Processing runs in a background thread per batch so the HTTP request that
triggers it returns immediately; batch.status is updated as it progresses
and polled by the frontend (GET /batches/{id}/status), so the UI reflects
real state even after a page refresh — no in-memory-only progress bar.

At real scale (100k-2M+ rows) this same batch-based, indexed, status-tracked
design is what you'd hand off to a proper task queue (Celery/RQ + Redis)
instead of a thread — see ARCHITECTURE.md for the scaling story. For the
demo dataset sizes here, a thread is sufficient and keeps the stack simple.
"""
import json
import threading
import pandas as pd
from database import (get_session, RawRecord, NormalizedRecord, FieldMapping,
                       ImportBatch, CANONICAL_FIELDS)
from normalization import normalize_field
from matching import find_matching_entity
from entity_repo import create_entity_from_record, enrich_entity_with_record

BATCH_SIZE = 500  # rows per DB commit — avoids holding huge transactions in memory


def ingest_csv(session, source_id, batch_id, file_path):
    """Reads a CSV in chunks and stores each row as an untouched raw_record.
    Chunked reading means we never load an entire multi-million-row file
    into memory at once."""
    total = 0
    for chunk in pd.read_csv(file_path, chunksize=BATCH_SIZE, dtype=str):
        chunk = chunk.where(pd.notnull(chunk), None)
        for i, row in chunk.iterrows():
            session.add(RawRecord(
                batch_id=batch_id, source_id=source_id, row_index=int(i),
                data_json=json.dumps(row.to_dict()),
            ))
            total += 1
        session.commit()

    batch = session.query(ImportBatch).get(batch_id)
    batch.total_rows = total
    batch.status = "mapping_suggested"
    session.commit()
    return total


def get_columns_and_samples(file_path, n_samples=5):
    df = pd.read_csv(file_path, nrows=n_samples, dtype=str)
    columns = list(df.columns)
    samples = df.where(pd.notnull(df), None).to_dict(orient="records")
    return columns, samples


def save_mapping(session, batch_id, mapping: dict):
    """mapping: {source_column: canonical_field}"""
    session.query(FieldMapping).filter_by(batch_id=batch_id).delete()
    for col, canonical in mapping.items():
        session.add(FieldMapping(
            batch_id=batch_id, source_column=col, canonical_field=canonical,
            confirmed=True, suggested_by="user",
        ))
    batch = session.query(ImportBatch).get(batch_id)
    batch.status = "mapping_confirmed"
    session.commit()


def _process_batch_sync(batch_id):
    """The actual pipeline: normalize -> match -> enrich/create entities.
    Runs on a background thread; owns its own DB session."""
    session = get_session()
    try:
        batch = session.query(ImportBatch).get(batch_id)
        batch.status = "cleaning"
        session.commit()

        mappings = {m.source_column: m.canonical_field
                    for m in session.query(FieldMapping).filter_by(batch_id=batch_id)}
        raw_records = session.query(RawRecord).filter_by(batch_id=batch_id).all()

        batch.status = "indexing"
        session.commit()

        processed, matched, created, errors = 0, 0, 0, 0

        for raw in raw_records:
            try:
                data = json.loads(raw.data_json)
                normalized_values = {}
                raw_values = {}
                for col, canonical in mappings.items():
                    if canonical == "ignore" or canonical not in CANONICAL_FIELDS:
                        continue
                    raw_val = data.get(col)
                    raw_values[canonical] = raw_val
                    normalized_values[canonical] = normalize_field(canonical, raw_val)

                record = NormalizedRecord(
                    raw_record_id=raw.id, batch_id=batch_id, source_id=raw.source_id,
                    raw_json=json.dumps(raw_values, default=str),
                    **{f: normalized_values.get(f) for f in CANONICAL_FIELDS},
                )
                session.add(record)
                session.flush()

                if batch.status != "matching":
                    batch.status = "matching"

                match = find_matching_entity(session, record)
                if match:
                    entity, field, value, confidence = match
                    enrich_entity_with_record(session, entity, record, field, value, confidence)
                    matched += 1
                else:
                    create_entity_from_record(session, record, status="newly_created")
                    created += 1

                processed += 1
                if processed % BATCH_SIZE == 0:
                    batch.processed_rows = processed
                    batch.matched_rows = matched
                    batch.new_entity_rows = created
                    session.commit()

            except Exception as e:
                errors += 1
                batch.error_log = (batch.error_log or "") + f"Row {raw.row_index}: {e}\n"

        batch.processed_rows = processed
        batch.matched_rows = matched
        batch.new_entity_rows = created
        batch.error_rows = errors
        batch.status = "completed" if errors == 0 else "completed_with_errors"
        from datetime import datetime
        batch.completed_at = datetime.utcnow()
        session.commit()

    except Exception as e:
        session.rollback()
        batch = session.query(ImportBatch).get(batch_id)
        if batch:
            batch.status = "failed"
            batch.error_log = (batch.error_log or "") + f"Fatal: {e}\n"
            session.commit()
    finally:
        session.close()


def start_processing(batch_id):
    thread = threading.Thread(target=_process_batch_sync, args=(batch_id,), daemon=True)
    thread.start()
