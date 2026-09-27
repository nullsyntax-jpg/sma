"""
Matching engine.

The hierarchy is a PRIORITIZED LIST of matcher rules, not one hardcoded
query — new rules can be appended without touching the engine itself
(see MATCH_HIERARCHY at the bottom). Each rule tries to find an existing
MasterEntity that a NormalizedRecord should attach to.
"""
from rapidfuzz import fuzz
from database import MasterEntity


def match_exact_email(session, record):
    if not record.email:
        return None
    entity = session.query(MasterEntity).filter(MasterEntity.email == record.email).first()
    return (entity, "email", record.email, 1.0) if entity else None


def match_exact_phone(session, record):
    if not record.phone:
        return None
    entity = session.query(MasterEntity).filter(MasterEntity.phone == record.phone).first()
    return (entity, "phone", record.phone, 0.97) if entity else None


def match_username(session, record):
    if not record.username:
        return None
    entity = session.query(MasterEntity).filter(MasterEntity.username == record.username).first()
    return (entity, "username", record.username, 0.9) if entity else None


def match_member_id(session, record):
    if not record.member_id:
        return None
    entity = session.query(MasterEntity).filter(MasterEntity.member_id == record.member_id).first()
    return (entity, "member_id", record.member_id, 0.9) if entity else None


FUZZY_BLOCK_CANDIDATE_LIMIT = 50  # cap candidates per block so this stays O(1)-ish per row, not O(n)


def match_fuzzy_name_address(session, record):
    """
    Lowest-confidence fallback rule. Two independent guards keep this rule
    safe at scale, both learned from testing against a 150k-row dataset:

    1. CORRECTNESS: name alone is not a reliable identifier — with a small
       pool of common first/last names, unrelated people collide on name by
       chance far more often than real entity duplicates occur (a version
       without this guard mis-merged ~98% of an unrelated 150k-row test
       set). We therefore REQUIRE a second corroborating field (address) to
       be present on both sides before this rule can fire at all; name
       similarity alone is insufficient evidence of a real match.

    2. PERFORMANCE: comparing against every existing master entity is an
       O(n) scan per row (O(n*m) overall) and does not scale to the
       100k-2M row target. We block first — only pull candidates whose
       normalized name shares the same 3-character prefix (index-friendly
       LIKE 'abc%' on the now-indexed `name` column) — before running the
       expensive fuzzy comparison on that much smaller candidate set.
    """
    if not record.name or not record.address:
        return None

    prefix = record.name[:3]
    candidates = (session.query(MasterEntity)
                  .filter(MasterEntity.name.like(f"{prefix}%"))
                  .filter(MasterEntity.address.isnot(None))
                  .limit(FUZZY_BLOCK_CANDIDATE_LIMIT)
                  .all())

    best, best_score = None, 0
    for cand in candidates:
        name_score = fuzz.token_sort_ratio(record.name, cand.name) / 100.0
        addr_score = fuzz.token_sort_ratio(record.address, cand.address) / 100.0
        score = (name_score * 0.6) + (addr_score * 0.4)
        if score > best_score:
            best, best_score = cand, score
    if best and best_score >= 0.85:
        return (best, "name+address_fuzzy", record.name, round(best_score, 2))
    return None


# Ordered by confidence / specificity. Add new rules here without touching
# the code that calls this list (see enrichment.py / ingestion.py).
MATCH_HIERARCHY = [
    match_exact_email,
    match_exact_phone,
    match_username,
    match_member_id,
    match_fuzzy_name_address,
]

MIN_AUTO_MATCH_CONFIDENCE = 0.85


def find_matching_entity(session, record):
    """Runs the hierarchy in order, returns the first (highest-priority) match."""
    for matcher in MATCH_HIERARCHY:
        result = matcher(session, record)
        if result and result[0] is not None and result[3] >= MIN_AUTO_MATCH_CONFIDENCE:
            return result  # (entity, matched_field, matched_value, confidence)
    return None
