"""
Field normalization. Raw value is ALWAYS preserved elsewhere (raw_records /
normalized_records.raw_json) — these functions only produce the cleaned
version used for indexing and matching.
"""
import re


def normalize_email(value):
    if not value or not str(value).strip():
        return None
    v = str(value).strip().lower()
    v = re.sub(r"\s+", "", v)
    if "@" not in v:
        return None
    return v


def normalize_phone(value):
    if not value or not str(value).strip():
        return None
    v = str(value).strip()
    # keep leading + if present, strip everything else non-digit
    has_plus = v.startswith("+")
    digits = re.sub(r"\D", "", v)
    if not digits:
        return None
    # Normalize India-style numbers: drop leading 0 / 91 country code so
    # "9876543210", "919876543210", "+91 98765 43210", "0-9876543210" all match.
    if len(digits) > 10:
        digits = digits[-10:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) >= 7 else None  # discard obviously malformed


def normalize_text(value):
    if value is None:
        return None
    v = str(value).strip()
    v = re.sub(r"\s+", " ", v)
    if not v or v.lower() in ("nan", "none", "null", "n/a", "-"):
        return None
    return v


def normalize_name(value):
    v = normalize_text(value)
    return v.title() if v else None


def normalize_username(value):
    v = normalize_text(value)
    return v.lower().lstrip("@") if v else None


NORMALIZERS = {
    "email": normalize_email,
    "phone": normalize_phone,
    "name": normalize_name,
    "username": normalize_username,
    "member_id": normalize_text,
    "address": normalize_text,
    "company": normalize_text,
}


def normalize_field(canonical_field, raw_value):
    fn = NORMALIZERS.get(canonical_field, normalize_text)
    return fn(raw_value)
