"""
Master entity repository: create new entities, merge normalized records into
existing ones, and record per-field provenance (MasterEntityField) plus a
match_log entry for every decision — this is what makes every value on a
master entity traceable back to its source.
"""
from datetime import datetime
from database import MasterEntity, MasterEntityField, MatchLog

MERGEABLE_FIELDS = ["name", "email", "phone", "username", "member_id", "address", "company"]


def _record_field_provenance(session, entity, field_name, value, source_id, normalized_record_id):
    if not value:
        return
    exists = session.query(MasterEntityField).filter_by(
        master_entity_id=entity.id, field_name=field_name,
        value=value, source_id=source_id
    ).first()
    if exists:
        return
    session.add(MasterEntityField(
        master_entity_id=entity.id, field_name=field_name, value=value,
        source_id=source_id, normalized_record_id=normalized_record_id,
        is_primary=(getattr(entity, field_name, None) == value),
    ))


def create_entity_from_record(session, record, status="active"):
    entity = MasterEntity(
        name=record.name, email=record.email, phone=record.phone,
        username=record.username, member_id=record.member_id,
        address=record.address, company=record.company, status=status,
    )
    session.add(entity)
    session.flush()  # get entity.id without committing
    for field in MERGEABLE_FIELDS:
        _record_field_provenance(session, entity, field, getattr(record, field),
                                  record.source_id, record.id)
    record.master_entity_id = entity.id
    return entity


def enrich_entity_with_record(session, entity, record, matched_field, matched_value,
                               confidence, hop=0):
    """Fill in any blank fields on the entity from this record; never overwrite
    a populated field (conflict resolution rule: first-seen wins, but every
    value is still recorded with its source for full traceability)."""
    for field in MERGEABLE_FIELDS:
        new_val = getattr(record, field)
        if new_val:
            _record_field_provenance(session, entity, field, new_val,
                                      record.source_id, record.id)
            if not getattr(entity, field, None):
                setattr(entity, field, new_val)
    entity.updated_at = datetime.utcnow()
    record.master_entity_id = entity.id

    session.add(MatchLog(
        master_entity_id=entity.id, normalized_record_id=record.id,
        matched_on_field=matched_field, matched_value=str(matched_value),
        confidence=confidence, hop=hop,
    ))
    return entity
