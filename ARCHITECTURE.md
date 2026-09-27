# Architecture — Multi-Database Entity Resolution & Unified Data Repository

## 1. Overview

The system ingests CSV datasets with arbitrary, differing schemas, maps
their columns to a canonical schema (AI-assisted), normalizes the values,
matches records across sources into unified **master entities**, and
supports **progressive enrichment search**: starting from one identifier,
the system discovers new identifiers on matched records and cascades the
search across every remaining source until nothing new is found.

```
CSV upload -> raw_records (untouched)
           -> AI field-mapping suggestion -> user review/confirm
           -> normalization -> normalized_records (raw + clean, both kept)
           -> matching hierarchy -> master_entities (+ per-field provenance)
           -> search-time progressive enrichment traversal
```

## 2. Database Ingestion

Each upload creates a `Source` (if new) and an `ImportBatch`. The batch
tracks status through an explicit state machine (`uploaded ->
mapping_suggested -> mapping_confirmed -> cleaning -> indexing -> matching
-> completed / completed_with_errors / failed`), polled by the frontend so
progress survives a page refresh — the client never depends on a live
socket or an open tab.

Multi-part datasets (Database 1 - Part 1/2/3) are supported via the
`part_label` field on `ImportBatch`: parts share a `source_id`, so matching
naturally treats them as one logical dataset without special-casing.

## 3. Large-File / Large-Dataset Processing

- CSV is read with `pandas.read_csv(..., chunksize=BATCH_SIZE)` — the file
  is never loaded fully into memory. Each chunk is committed to
  `raw_records` and the connection is freed before the next chunk.
- Row-by-row normalization + matching happens in the same streaming style,
  with periodic commits every `BATCH_SIZE` rows rather than one giant
  transaction.
- Processing runs on a background thread per batch, decoupled from the
  HTTP request/response cycle, so the browser doesn't have to stay open.
- **At current implementation scale** (demo datasets, thousands of rows)
  a background thread + SQLite is sufficient and keeps the stack simple to
  run/deploy for evaluation.
- **At the assignment's target scale** (100k–2M+ rows) the same
  batch/streaming design is what you would lift into a proper job queue:
  - Swap the thread for Celery/RQ workers backed by Redis or a message
    broker, so imports run on separate worker processes/machines and
    survive an app-server restart.
  - Swap SQLite for Postgres, and add explicit indexes (already declared
    in the schema as `index=True` on `email`, `phone`, `username`,
    `member_id`) or a search-optimized store (Elasticsearch/OpenSearch) for
    the identifier lookups that drive matching and enrichment.
  - Partition/paginate the raw-record scan so a resumed job doesn't
    re-read already-processed rows — track a `last_processed_row_index`
    checkpoint per batch (straightforward extension of the current
    `processed_rows` counter).

## 4. Field Mapping

`field_mapping.py` sends the column names plus a few sample rows to an LLM
(Groq's free-tier `llama-3.1-8b-instant` by default; Gemini is a drop-in
alternative) and asks it to suggest a canonical field + confidence per
column. If no API key is configured, or the call fails for any reason, the
system falls back to a keyword-based heuristic (`KEYWORD_MAP`) so ingestion
is never blocked on external AI availability.

The user always reviews/edits the suggested mapping before processing
starts (`/api/batches/{id}/mapping`) — nothing is auto-committed without
that confirmation step, per the assignment's requirement.

## 5. Data Cleaning & Normalization

`normalization.py` holds one function per canonical field:
- **email**: lowercase, whitespace stripped, must contain `@`.
- **phone**: non-digit characters stripped; country-code / leading-zero
  variants (`+91 98765 43210`, `919876543210`, `09876543210`) are all
  normalized to the same 10-digit form so cross-source phone matches work
  despite formatting differences.
- **name/address/company/member_id**: whitespace collapsed, blank/null
  sentinel values (`"nan"`, `"n/a"`, `"-"`) treated as null.

Both the **raw** value (`raw_records.data_json`, and again per-field in
`normalized_records.raw_json`) and the **normalized** value are stored —
never one without the other — satisfying the traceability requirement.

## 6. Matching Engine

`matching.py` defines `MATCH_HIERARCHY` as an **ordered list of
independent functions**, not one hardcoded SQL query:

1. Exact email match (confidence 1.0)
2. Exact normalized phone match (0.97)
3. Username match (0.9)
4. Member/customer ID match (0.9)
5. Fuzzy name+address match, via `rapidfuzz` token-sort ratio (variable,
   accepted only ≥ 0.85)

`find_matching_entity()` walks the list in order and returns the first
rule that clears `MIN_AUTO_MATCH_CONFIDENCE`. Adding a new identifier rule
(e.g. a national ID number) means writing one function and appending it to
the list — the calling code in `ingestion.py` and `enrichment.py` needs no
changes.

## 7. Master Entity Repository & Source Traceability

`entity_repo.py` creates a `MasterEntity` on first sight of a record, or
enriches an existing one. Every value that lands on a master entity is
also written to `MasterEntityField` (field name, value, `source_id`,
`normalized_record_id`) — so for any field on any entity, the UI can
answer "which source said this, and which raw row was it?". A
`MatchLog` row records every matching decision (which field matched, at
what confidence, on which enrichment hop) as an audit trail.

Conflict resolution rule (documented, deliberately simple for this
scope): **first-seen value wins** for the entity's primary field, but
every subsequent value from another source is still recorded via
`MasterEntityField` rather than discarded — so a human reviewer can see
disagreements between sources even though the system picks one
automatically. A natural extension: weight sources by trust/recency and
let the "winning" value be re-computed rather than fixed at first-seen.

## 8. Progressive Entity Enrichment (core feature)

`enrichment.py` implements the traversal described in the assignment
exactly: given a seed identifier, it performs a breadth-first search over
the "identifier graph" —

1. Query all `normalized_records` matching the current identifier.
2. Fold each matched record into the entity (creating it on first match).
3. Extract every other identifier field present on those records.
4. Any identifier not already searched is queued for the next hop.
5. Repeat until a hop produces no new identifiers, or `MAX_HOPS` (6) is
   hit as a safety net against pathological/cyclic data.

The function returns a **step-by-step trace** (`hop`, field searched,
records found, new identifiers discovered) which the frontend renders
directly — this is what makes the "system connecting the dots" visible
rather than a black box, and is the centerpiece of the demo video.

This is a live, search-time traversal — distinct from (and complementary
to) the import-time matching in `ingestion.py`, which links records into
entities as data arrives. Running both means: entities are already mostly
connected by the time you search, and the search still re-verifies and
can pull in anything import-time matching missed (e.g. if a source was
imported before another that would have linked it).

## 9. New Database / Incremental Processing

Adding a new source doesn't reprocess existing sources: `ingestion.py`
only touches the new batch's `raw_records`. Import-time matching
(`find_matching_entity`) checks the new records against **existing**
`MasterEntity` rows, so:
- A match enriches an existing entity (`enrich_entity_with_record`).
- No match creates a new entity, marked `status="newly_created"` — never
  discarded (see below), and available for future sources to match
  against.

## 10. No-Match / Unresolved Records

Every normalized record either attaches to a master entity or becomes one
itself — none are dropped. `MasterEntity.status` distinguishes
`newly_created` (insufficient corroboration yet) from `active` (matched
by later sources), so the `/api/stats` unresolved-record count reflects
records that haven't found a second source yet, without ever losing data.

## 11. Background Processing & Status Visibility

Each batch's pipeline runs on its own thread; `ImportBatch.status` is the
single source of truth for progress and is polled by the frontend every 2s
(`GET /api/batches/{id}/status`), so a browser refresh mid-import shows
the correct current state rather than resetting.

## 12. Caching

Not implemented in this build (dataset sizes don't need it to stay
responsive), but the design point is explicit: `MasterEntity` lookups by
`email`/`phone`/`username`/`member_id` are the hot path for both matching
and search, and those columns are already indexed. At production scale,
a Redis layer in front of `/api/search` (keyed by `field:value`, short TTL
or invalidated on new writes to that identifier) would remove repeated-
identifier lookups from the DB entirely without changing the API surface.

## 13. Error Handling

Per-row exceptions during processing are caught, logged into
`ImportBatch.error_log`, and counted in `error_rows` — a batch finishes as
`completed_with_errors` rather than aborting the whole import. Fatal
errors (e.g. a corrupt file) mark the batch `failed` with the exception
recorded, visible via `/api/batches/{id}/status`.

## 13.5 What Large-Scale Testing Actually Found

The claims above weren't left untested. A 150,000-row CSV
(`data/generate_large_dataset.py`) was ingested and processed end to end
against the running system, and this surfaced two real issues worth
documenting honestly rather than glossing over:

**Bug found and fixed: the fuzzy name+address fallback rule over-matched.**
With only a small pool of common first/last names, unrelated people
collide on *name alone* far more often than genuine duplicates occur —
the first version of this rule matched ~98% of a dataset of entirely
unrelated people. Fixed by (a) requiring a second corroborating field
(address) to be present before the rule can fire at all — name similarity
alone is not accepted as evidence — and (b) blocking: candidates are now
restricted to those sharing the same 3-character name prefix (an indexed
`LIKE 'abc%'` query) before the expensive fuzzy comparison runs, rather
than scanning every existing master entity. Re-running the same 150k-row
test after the fix produced `matched_rows: 1` — correctly, only the one
deliberately-planted duplicate — confirming the fix.

**Known limitation: current per-row processing is not yet fast enough
for the assignment's upper bound (1-2M+ rows).** Sustained throughput in
testing was ~170 rows/second, driven by two things: (1) each row runs up
to 5 sequential indexed lookups through the matching hierarchy via the
SQLAlchemy ORM, which carries more overhead than a bulk query would, and
(2) `_process_batch_sync` currently loads all of a batch's `raw_records`
with a single `.all()` call rather than paginating that read — fine up to
roughly hundreds of thousands of rows on modest hardware, but it should be
chunked for the assignment's stated 1-2M+ ceiling. Both are direct,
well-understood fixes (batch the raw-record read in pages; resolve exact-
match rules — email/phone/username/member_id — as bulk SQL joins instead
of one Python loop per row, falling back to per-row handling only for the
fuzzy rule) rather than open design questions, and are called out here
rather than silently left for the evaluator to discover.

## 14. Scaling Story (summary)

| Concern | Current implementation | Production-scale upgrade |
|---|---|---|
| Storage | SQLite | Postgres |
| Background jobs | Python thread per batch | Celery/RQ + Redis, multiple workers |
| Search/lookup | Indexed SQL columns | Redis cache in front of hot lookups; Elasticsearch for fuzzy/full-text at scale |
| File reading | `pandas` chunked reads | Same approach, plus S3/object-storage streaming for very large files |
| Resumability | `processed_rows` counter | Per-row checkpointing so a restarted worker resumes mid-batch |
| Relationship discovery | Not implemented (bonus) | FK/shared-identifier inference across multi-table SQL sources |

## 15. Technology Stack

- **Backend**: Python, FastAPI, SQLAlchemy, SQLite
- **Matching**: rapidfuzz (fuzzy string similarity)
- **AI**: Groq API (`llama-3.1-8b-instant`) for field-mapping suggestions,
  with a heuristic fallback
- **Frontend**: single-page vanilla HTML/CSS/JS (no build step, easy to
  deploy alongside the API)
- **Data processing**: pandas (chunked CSV reads)
