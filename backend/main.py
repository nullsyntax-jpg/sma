import os
import json
import shutil
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import (init_db, get_session, Source, ImportBatch, FieldMapping,
                       NormalizedRecord, MasterEntity, MasterEntityField,
                       MatchLog, CANONICAL_FIELDS)
from field_mapping import suggest_mapping
from ingestion import ingest_csv, get_columns_and_samples, save_mapping, start_processing
from enrichment import progressive_search, IDENTIFIER_FIELDS

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="Multi-Database Entity Resolution Platform")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

init_db()

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


# ---------------------------------------------------------------- sources --
@app.post("/api/sources")
def create_source(name: str = Form(...), source_type: str = Form("csv")):
    session = get_session()
    src = Source(name=name, source_type=source_type)
    session.add(src)
    session.commit()
    result = {"id": src.id, "name": src.name, "source_type": src.source_type}
    session.close()
    return result


@app.get("/api/sources")
def list_sources():
    session = get_session()
    sources = session.query(Source).all()
    result = [{"id": s.id, "name": s.name, "source_type": s.source_type,
               "created_at": str(s.created_at), "batches": len(s.batches)} for s in sources]
    session.close()
    return result


@app.get("/api/sources/{source_id}")
def get_source_detail(source_id: int):
    """Powers the Source Detail page: source info + every batch imported
    under it, each with its confirmed/suggested mapping if one exists."""
    session = get_session()
    source = session.query(Source).get(source_id)
    if not source:
        session.close()
        raise HTTPException(404, "Source not found")

    batches = session.query(ImportBatch).filter_by(source_id=source_id).order_by(ImportBatch.id.desc()).all()
    batch_list = []
    for b in batches:
        mappings = session.query(FieldMapping).filter_by(batch_id=b.id).all()
        batch_list.append({
            "id": b.id, "filename": b.filename, "part_label": b.part_label,
            "status": b.status, "total_rows": b.total_rows, "processed_rows": b.processed_rows,
            "matched_rows": b.matched_rows, "new_entity_rows": b.new_entity_rows,
            "error_rows": b.error_rows, "error_log": b.error_log,
            "created_at": str(b.created_at),
            "completed_at": str(b.completed_at) if b.completed_at else None,
            "mapping": [{"source_column": m.source_column, "canonical_field": m.canonical_field,
                         "confidence": m.confidence, "suggested_by": m.suggested_by}
                        for m in mappings],
        })

    result = {
        "id": source.id, "name": source.name, "source_type": source.source_type,
        "created_at": str(source.created_at), "batches": batch_list,
    }
    session.close()
    return result


# ---------------------------------------------------------------- upload ---
@app.post("/api/sources/{source_id}/upload")
def upload_file(source_id: int, file: UploadFile = File(...), part_label: str = Form(None)):
    session = get_session()
    source = session.query(Source).get(source_id)
    if not source:
        session.close()
        raise HTTPException(404, "Source not found")

    file_path = os.path.join(UPLOAD_DIR, f"{source_id}_{file.filename}")
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    batch = ImportBatch(source_id=source_id, filename=file.filename,
                         part_label=part_label, status="uploaded")
    session.add(batch)
    session.commit()
    batch_id = batch.id

    ingest_csv(session, source_id, batch_id, file_path)
    columns, samples = get_columns_and_samples(file_path)
    session.close()

    mapping_suggestion = suggest_mapping(columns, samples)

    return {"batch_id": batch_id, "columns": columns, "sample_rows": samples,
            "suggested_mapping": mapping_suggestion, "canonical_fields": CANONICAL_FIELDS}


@app.post("/api/batches/{batch_id}/mapping")
def confirm_mapping(batch_id: int, mapping: str = Form(...)):
    """mapping is a JSON string: {"source_column": "canonical_field", ...}"""
    session = get_session()
    parsed = json.loads(mapping)
    save_mapping(session, batch_id, parsed)
    session.close()
    return {"status": "mapping_confirmed"}


@app.post("/api/batches/{batch_id}/process")
def process_batch(batch_id: int):
    start_processing(batch_id)
    return {"status": "processing_started"}


@app.get("/api/batches/{batch_id}/status")
def batch_status(batch_id: int):
    session = get_session()
    b = session.query(ImportBatch).get(batch_id)
    if not b:
        session.close()
        raise HTTPException(404, "Batch not found")
    result = {
        "id": b.id, "filename": b.filename, "status": b.status,
        "total_rows": b.total_rows, "processed_rows": b.processed_rows,
        "matched_rows": b.matched_rows, "new_entity_rows": b.new_entity_rows,
        "error_rows": b.error_rows, "error_log": b.error_log,
        "created_at": str(b.created_at), "completed_at": str(b.completed_at) if b.completed_at else None,
    }
    session.close()
    return result


@app.get("/api/batches")
def list_batches():
    session = get_session()
    batches = session.query(ImportBatch).order_by(ImportBatch.id.desc()).all()
    result = [{"id": b.id, "source_id": b.source_id, "filename": b.filename,
               "status": b.status, "total_rows": b.total_rows,
               "processed_rows": b.processed_rows} for b in batches]
    session.close()
    return result


# ------------------------------------------------------ progressive search --
@app.get("/api/search")
def search(field: str, value: str):
    if field not in IDENTIFIER_FIELDS:
        raise HTTPException(400, f"field must be one of {IDENTIFIER_FIELDS}")
    session = get_session()
    result = progressive_search(session, field, value)

    entity = result["entity"]
    if not entity:
        session.close()
        return {"found": False, "trace": result["trace"]}

    field_sources = session.query(MasterEntityField).filter_by(master_entity_id=entity.id).all()
    provenance = {}
    for f in field_sources:
        provenance.setdefault(f.field_name, []).append({
            "value": f.value, "source_id": f.source_id,
            "normalized_record_id": f.normalized_record_id,
        })

    source_ids = sorted({f.source_id for f in field_sources})
    from database import Source
    source_names = {s.id: s.name for s in session.query(Source).filter(Source.id.in_(source_ids))}

    response = {
        "found": True,
        "entity": {
            "id": entity.id, "name": entity.name, "email": entity.email,
            "phone": entity.phone, "username": entity.username,
            "member_id": entity.member_id, "address": entity.address,
            "company": entity.company, "status": entity.status,
        },
        "sources": [{"id": sid, "name": source_names.get(sid, f"Source {sid}")} for sid in source_ids],
        "field_provenance": provenance,
        "trace": result["trace"],
        "hops": len(result["trace"]),
        "records_examined": len(result["matched_records"]),
    }
    session.close()
    return response


@app.get("/api/entities/{entity_id}")
def get_entity(entity_id: int):
    """Powers the Entity Detail page: full entity, per-field provenance
    (which source contributed each value), the sources it was matched
    across, and the match/enrichment history as a hop-ordered trace —
    the same shape /api/search returns, so Entity Detail works whether
    you arrive via a fresh search or by clicking an entity elsewhere."""
    session = get_session()
    entity = session.query(MasterEntity).get(entity_id)
    if not entity:
        session.close()
        raise HTTPException(404, "Entity not found")

    field_rows = session.query(MasterEntityField).filter_by(master_entity_id=entity_id).all()
    provenance = {}
    for f in field_rows:
        provenance.setdefault(f.field_name, []).append({
            "value": f.value, "source_id": f.source_id,
            "normalized_record_id": f.normalized_record_id,
        })

    source_ids = sorted({f.source_id for f in field_rows})
    source_names = {s.id: s.name for s in session.query(Source).filter(Source.id.in_(source_ids))}

    logs = session.query(MatchLog).filter_by(master_entity_id=entity_id).order_by(MatchLog.hop, MatchLog.id).all()

    result = {
        "id": entity.id, "name": entity.name, "email": entity.email,
        "phone": entity.phone, "username": entity.username,
        "member_id": entity.member_id, "address": entity.address,
        "company": entity.company, "status": entity.status,
        "created_at": str(entity.created_at), "updated_at": str(entity.updated_at),
        "sources": [{"id": sid, "name": source_names.get(sid, f"Source {sid}")} for sid in source_ids],
        "field_provenance": provenance,
        "match_log": [{"field": l.matched_on_field, "value": l.matched_value,
                        "confidence": l.confidence, "hop": l.hop} for l in logs],
    }
    session.close()
    return result


@app.get("/api/entities")
def list_entities(limit: int = 50):
    session = get_session()
    entities = session.query(MasterEntity).order_by(MasterEntity.id.desc()).limit(limit).all()
    result = [{"id": e.id, "name": e.name, "email": e.email, "phone": e.phone,
               "username": e.username, "status": e.status} for e in entities]
    session.close()
    return result


# -------------------------------------------------------------- stats -----
@app.get("/api/stats")
def stats():
    session = get_session()
    from sqlalchemy import func
    total_sources = session.query(func.count(Source.id)).scalar()
    total_batches = session.query(func.count(ImportBatch.id)).scalar()
    total_records = session.query(func.count(NormalizedRecord.id)).scalar()
    total_entities = session.query(func.count(MasterEntity.id)).scalar()
    matched_records = session.query(func.count(NormalizedRecord.id)).filter(
        NormalizedRecord.master_entity_id.isnot(None)).scalar()
    unresolved = session.query(func.count(NormalizedRecord.id)).filter(
        NormalizedRecord.master_entity_id.is_(None)).scalar()
    new_entities = session.query(func.count(MasterEntity.id)).filter(
        MasterEntity.status == "newly_created").scalar()
    failed_batches = session.query(func.count(ImportBatch.id)).filter(
        ImportBatch.status.in_(["failed", "completed_with_errors"])).scalar()

    result = {
        "total_sources": total_sources, "total_batches": total_batches,
        "total_records": total_records, "total_entities": total_entities,
        "matched_records": matched_records, "unresolved_records": unresolved,
        "new_entities": new_entities, "batches_with_errors": failed_batches,
    }
    session.close()
    return result


# ------------------------------------------------------------ frontend ----
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
