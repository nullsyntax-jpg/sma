"""
Suggests canonical field mappings for a source's columns.

Tries an LLM (Groq free tier by default — fast + generous free quota) and
falls back to a keyword heuristic if no API key is configured or the call
fails, so the pipeline never blocks on external AI availability.

Set GROQ_API_KEY (or GEMINI_API_KEY) as an environment variable to enable
the AI path. Without a key, the heuristic path still produces sensible
mappings for the demo datasets.
"""
import os
import json
import requests
from database import CANONICAL_FIELDS

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- Heuristic fallback -----------------------------------------------
KEYWORD_MAP = {
    "email": ["email", "email_id", "email_address", "e_mail", "mail"],
    "phone": ["phone", "mobile", "mobile_number", "contact_no", "contact_number",
              "phone_number", "cell", "tel"],
    "name": ["name", "full_name", "fullname", "customer_name", "contact_name", "person_name"],
    "username": ["username", "user_name", "handle", "login"],
    "member_id": ["member_id", "customer_id", "user_id", "id_number", "employee_id", "emp_id"],
    "address": ["address", "location", "city", "addr"],
    "company": ["company", "organisation", "organization", "employer", "business_name"],
}


def heuristic_mapping(columns):
    mapping = {}
    for col in columns:
        col_l = col.strip().lower()
        best_field, best_score = "ignore", 0
        for field, keywords in KEYWORD_MAP.items():
            for kw in keywords:
                if kw == col_l:
                    best_field, best_score = field, 1.0
                    break
                elif kw in col_l:
                    score = len(kw) / max(len(col_l), 1)
                    if score > best_score:
                        best_field, best_score = field, score
            if best_score == 1.0:
                break
        mapping[col] = {
            "canonical_field": best_field if best_score > 0 else "ignore",
            "confidence": round(best_score, 2),
            "suggested_by": "heuristic",
        }
    return mapping


# --- AI path (Groq) -----------------------------------------------------
def ai_mapping_groq(columns, sample_rows):
    prompt = f"""You are mapping spreadsheet columns to a canonical schema for an
entity-resolution system. Canonical fields available: {CANONICAL_FIELDS} (use
"ignore" if a column matches none of them).

Columns: {columns}
Sample rows (first few, as JSON): {json.dumps(sample_rows[:3], default=str)}

Return ONLY a JSON object mapping each source column name to an object with
"canonical_field" and "confidence" (0-1). No prose, no markdown fences.
Example: {{"email_id": {{"canonical_field": "email", "confidence": 0.97}}}}"""

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=20,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()
    text = text.strip("`").replace("json\n", "").strip()
    parsed = json.loads(text)
    for col, info in parsed.items():
        info["suggested_by"] = "ai"
    return parsed


def suggest_mapping(columns, sample_rows):
    """Public entry point. Tries AI, falls back to heuristic on any failure."""
    if GROQ_API_KEY:
        try:
            return ai_mapping_groq(columns, sample_rows)
        except Exception as e:
            print(f"[field_mapping] AI mapping failed, falling back to heuristic: {e}")
    return heuristic_mapping(columns)
