"""
PROGRESSIVE ENTITY ENRICHMENT — the core/winning feature of this system.

Given a starting identifier (e.g. an email address), this module:
  1. Searches ALL normalized records across ALL sources for that identifier.
  2. Extracts any OTHER identifiers present on the matched records
     (phone, username, member_id, email — whichever weren't the seed).
  3. Uses each newly discovered identifier to search the remaining sources.
  4. Repeats until no new identifiers are discovered (or a hop cap is hit,
     as a safety net against pathological data).
  5. Returns a fully unified entity plus a step-by-step trace of the
     discovery process, so the UI can visualize exactly how the system
     "connected the dots" — this trace is what the demo video should show.

This is intentionally separate from the (simpler) import-time matching in
matching.py/entity_repo.py: import-time matching links records into entities
as data arrives; this module re-traverses the identifier graph live at
search time, which is what the assignment spec explicitly asks for.
"""
from database import NormalizedRecord, MasterEntity
from entity_repo import create_entity_from_record, enrich_entity_with_record

IDENTIFIER_FIELDS = ["email", "phone", "username", "member_id"]
MAX_HOPS = 6  # safety cap so a data quirk can never cause an infinite loop


def _find_records_by_identifier(session, field, value):
    return session.query(NormalizedRecord).filter(
        getattr(NormalizedRecord, field) == value
    ).all()


def progressive_search(session, seed_field, seed_value):
    """
    Returns:
      {
        "entity": MasterEntity | None,
        "trace": [ {hop, field, value, records_found, new_identifiers}, ... ],
        "matched_records": [NormalizedRecord, ...],
      }
    """
    if seed_field not in IDENTIFIER_FIELDS:
        raise ValueError(f"seed_field must be one of {IDENTIFIER_FIELDS}")

    seen_identifiers = {(seed_field, seed_value)}
    frontier = [(seed_field, seed_value)]
    all_matched_records = []
    trace = []
    entity = None
    hop = 0

    while frontier and hop < MAX_HOPS:
        next_frontier = []
        for field, value in frontier:
            records = _find_records_by_identifier(session, field, value)
            new_identifiers_this_step = []

            for rec in records:
                if rec not in all_matched_records:
                    all_matched_records.append(rec)

                # Fold this record into the unified entity.
                if entity is None:
                    entity = (session.query(MasterEntity).get(rec.master_entity_id)
                              if rec.master_entity_id else None)
                    if entity is None:
                        entity = create_entity_from_record(session, rec, status="active")
                        session.flush()
                else:
                    enrich_entity_with_record(
                        session, entity, rec, matched_field=field,
                        matched_value=value, confidence=1.0 if field in ("email", "phone") else 0.9,
                        hop=hop,
                    )

                # Discover new identifiers on this record we haven't searched yet.
                for id_field in IDENTIFIER_FIELDS:
                    id_value = getattr(rec, id_field)
                    if id_value and (id_field, id_value) not in seen_identifiers:
                        seen_identifiers.add((id_field, id_value))
                        next_frontier.append((id_field, id_value))
                        new_identifiers_this_step.append({"field": id_field, "value": id_value})

            trace.append({
                "hop": hop,
                "searched_field": field,
                "searched_value": value,
                "records_found": len(records),
                "new_identifiers_discovered": new_identifiers_this_step,
            })

        frontier = next_frontier
        hop += 1

    if entity:
        session.commit()

    return {"entity": entity, "trace": trace, "matched_records": all_matched_records}
