# EntityResolve — Multi-Database Entity Resolution & Unified Data Repository

A web platform that ingests CSVs with different schemas, uses AI-assisted
field mapping, cleans/normalizes the data, matches records across sources
into unified master entities, and — the core feature — **progressively
enriches search results** by cascading from one identifier to every other
identifier it discovers, across every source, until nothing new is found.

See `ARCHITECTURE.md` for the full technical write-up.

## Pages

| Page | What it shows |
|---|---|
| **Dashboard** | Processing statistics, quick links, recent import batches |
| **Sources** | List of all sources; create a new one here |
| **Source Detail** | One source's batches, upload a new CSV under it, review/confirm AI-suggested field mapping, live processing status |
| **Search** | Search by email/phone/username/member_id; entity-oriented result with the progressive enrichment trace |
| **Entity Detail** | Full master entity, per-field provenance (which source contributed each value), and match/enrichment history — reached from a Search result or from clicking through a source's records |

## Quick Start (local)

```bash
cd backend
pip install -r requirements.txt

# Optional but recommended: enables AI-assisted field mapping via Groq
# (free tier: https://console.groq.com/keys). Without this, the system
# automatically falls back to a keyword-based heuristic mapping.
export GROQ_API_KEY=your_key_here

uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** — the frontend is served directly by the
same FastAPI app (no separate build/deploy step needed).

## Demo Data

Two generators are included. **Use the realistic one for your actual demo
and video** — the tiny one is only for a fast local sanity check.

### Primary: realistic dataset (use this for the video)

```bash
cd data
python3 generate_realistic_dataset.py
```

Generates a base population of 1,000 people (via Faker), split into 4
CSVs with **different schemas**, **different coverage** (not everyone
appears in every source — mirrors real messy data), and realistic
messiness:

| File | Columns | Coverage | Quirks |
|---|---|---|---|
| `database_a_hr.csv` | full_name, email, mobile_number | ~900/1000 | phone as `84841-00337` or plain digits |
| `database_b_directory.csv` | name, email_id, contact_no, address | ~700/1000 | **UPPERCASE emails**, padded whitespace, some blank phones, `+91 xxxxx xxxxx` / leading-zero formats |
| `database_c_contacts.csv` | username, phone, company | ~600/1000 | **no email column at all** — only reachable via phone/username |
| `database_d_membership.csv` | member_id, email, username | ~500/1000 | sparse — ~30% of emails blank |

Database C having no email at all is deliberate: a search starting from
an email can only ever reach it through genuine progressive enrichment
(discovering a phone or username first), so the demo can't fake the
"winning feature" with a lucky single lookup.

The script also writes `answer_key.json` — ground truth of who's who
across all 4 files, **never imported into the app**, used only to verify
the matching engine reconnects the right people. Keep it out of your demo
video. It prints a ready-to-use example at the end, e.g.:
```
Person #2: Chavvi Dhar — search email = chavvi.dhar458@mail.com
```

**Recommended import order** (via Sources → pick a source → upload):
1. `database_a_hr.csv`
2. `database_c_contacts.csv` — the no-email source; proves enrichment, not luck
3. `database_b_directory.csv` — exercises case/whitespace normalization
4. `database_d_membership.csv` — adds member_id, some blank emails

Then go to **Search**, search by email using a value the script printed
for you, and watch the trace panel show the cascade — pulling in data
from all 4 sources with full per-source, per-field attribution (visible
in more depth on the Entity Detail page).

**A note on entity counts**: after importing all 4 files you'll see
slightly more master entities than 1,000 (typically ~1,050). This is
expected, not a bug — by design, a small number of people only appear in
two sources that happen to share no populated identifier (e.g. only in
Directory + Membership, with their Membership email blank — Directory
never has a username field to fall back on). With zero shared evidence,
the system correctly creates two separate entities rather than guessing.
Worth mentioning in your video as a deliberate, honest design choice.

### Quick sanity check (tiny, not for the demo video)

```bash
cd data
python3 generate_demo_data.py
```

Produces four ~27-row CSVs (`quickdemo_*.csv`) with two hand-threaded
people (John Doe, Priya Sharma) for a 30-second local smoke test. Same
import flow as above, using `quickdemo_a_hr.csv` etc.

## Automated end-to-end test

`data/test_import_flow.py` drives the whole flow (create sources, upload
all 4 files, confirm AI-suggested mappings, process, run the progressive
search, print stats) purely via the HTTP API — useful for a quick sanity
check after any change:

```bash
python3 data/test_import_flow.py <source_id_a> <source_id_c> <source_id_b> <source_id_d>
```

## Deployment

Any Python host works (Render, Railway, Fly.io free tiers all support
this out of the box):
- Build command: `pip install -r backend/requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT` (run from
  the `backend/` directory, or adjust `FRONTEND_DIR` in `main.py` if you
  restructure)
- Set `GROQ_API_KEY` as an environment variable if you want AI-assisted
  mapping live in the hosted demo (optional — heuristic fallback works
  without it)
- No login/auth is required to access the UI, per the evaluation
  requirement — don't add one in front of it

## Technologies & Libraries

FastAPI, SQLAlchemy, SQLite, pandas, rapidfuzz, Groq API (optional),
vanilla HTML/CSS/JS frontend (no framework/build step).

## What's implemented vs. bonus

**Implemented:** multi-source CSV ingestion, AI-assisted field mapping
with user review, normalization with raw-value preservation, configurable
matching hierarchy, progressive multi-hop enrichment with full trace,
master entity repository with per-field source provenance, entity-oriented
search, background/async processing with live status, processing
statistics, incremental new-database ingestion without reprocessing.

**Not implemented (explicitly listed as bonus in the assignment):**
automatic FK/relationship discovery across multi-table SQL sources,
graph-based relationship visualization, Redis caching, distributed
workers. All are addressed as a scaling plan in `ARCHITECTURE.md` §14.
