"""
Generates a more realistic demo dataset than generate_demo_data.py:
a single base population of N people (via Faker), split into 4 databases
with DIFFERENT schemas, DIFFERENT coverage (not everyone appears in every
source), and realistic messiness (case differences, padded whitespace,
varied phone formatting, blank fields) — while keeping a private answer
key so the matching engine's output can be checked against ground truth.

Design (mirrors the assignment's own example table in Section 24):

  Database A - HR              email, full_name, mobile_number      (~90% coverage)
  Database B - Directory       email_id, name, contact_no, address  (~70% coverage, messy)
  Database C - Contacts        username, phone, company             (~60% coverage, NO email)
  Database D - Membership      member_id, email, username           (~50% coverage, sparse)

Database C deliberately has no email column at all, so a search that
starts from an email can only ever reach C via progressive enrichment
(discovering a phone or username first) — this is what forces the demo
to actually exercise multi-hop enrichment rather than a single lookup.

The answer key (answer_key.json) is NEVER imported into the app — it's
only for verifying the matching/enrichment engine reconnects the right
people. Keep it out of your demo video; it would give the game away.
"""
import csv
import json
import os
import random
from faker import Faker

random.seed(11)
fake = Faker("en_IN")
Faker.seed(11)

OUT_DIR = os.path.dirname(__file__)
N_PEOPLE = 1000

COMPANIES = ["ABC Pvt Ltd", "Nimbus Tech", "Vertex Solutions", "BlueWave Retail",
             "Orion Labs", "Skyline Ventures", "Redwood Systems", "Apex Traders",
             "Lumen Analytics", "Cobalt Systems"]


def make_person(pid):
    first = fake.first_name()
    last = fake.last_name()
    full_name = f"{first} {last}"
    email = f"{first.lower()}.{last.lower()}{random.randint(1,999)}@mail.com"
    # canonical 10-digit Indian mobile
    phone = f"{random.choice([6,7,8,9])}{random.randint(100000000,999999999)}"
    username = f"{first.lower()}{last.lower()}{random.randint(10,99)}"
    member_id = f"MEM{1000+pid}"
    company = random.choice(COMPANIES)
    address = f"{random.randint(1,199)} {fake.street_name()}, {fake.city()}"
    return {
        "id": pid, "first": first, "last": last, "full_name": full_name,
        "email": email, "phone": phone, "username": username,
        "member_id": member_id, "company": company, "address": address,
    }


def fmt_phone_variant(phone, style):
    if style == "plain":
        return phone
    if style == "hyphen":
        return f"{phone[:5]}-{phone[5:]}"
    if style == "intl":
        return f"+91 {phone[:5]} {phone[5:]}"
    if style == "leading_zero":
        return f"0{phone}"
    return phone


def build_population():
    return [make_person(i) for i in range(N_PEOPLE)]


def write_csv(filename, header, rows):
    path = os.path.join(OUT_DIR, filename)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def gen_database_a(people, coverage=0.90):
    sample = random.sample(people, int(len(people) * coverage))
    rows = []
    for p in sample:
        style = random.choice(["plain", "hyphen"])
        rows.append([p["full_name"], p["email"], fmt_phone_variant(p["phone"], style)])
    write_csv("database_a_hr.csv", ["full_name", "email", "mobile_number"], rows)
    return {p["id"] for p in sample}


def gen_database_b(people, coverage=0.70):
    sample = random.sample(people, int(len(people) * coverage))
    rows = []
    for p in sample:
        # UPPERCASE email, padded whitespace in name, varied/blank phone
        email = f"  {p['email'].upper()}  "
        name = f"  {p['full_name']}  "
        style = random.choice(["intl", "leading_zero", "blank"])
        phone = "" if style == "blank" else fmt_phone_variant(p["phone"], style)
        rows.append([name, email, phone, p["address"]])
    write_csv("database_b_directory.csv", ["name", "email_id", "contact_no", "address"], rows)
    return {p["id"] for p in sample}


def gen_database_c(people, coverage=0.60):
    """No email column at all — reachable only via phone/username enrichment."""
    sample = random.sample(people, int(len(people) * coverage))
    rows = [[p["username"], p["phone"], p["company"]] for p in sample]
    write_csv("database_c_contacts.csv", ["username", "phone", "company"], rows)
    return {p["id"] for p in sample}


def gen_database_d(people, coverage=0.50):
    sample = random.sample(people, int(len(people) * coverage))
    rows = []
    for p in sample:
        # sparse: sometimes email is missing, relying on member_id/username to link
        email = p["email"] if random.random() > 0.3 else ""
        rows.append([p["member_id"], email, p["username"]])
    write_csv("database_d_membership.csv", ["member_id", "email", "username"], rows)
    return {p["id"] for p in sample}


if __name__ == "__main__":
    people = build_population()
    ids_a = gen_database_a(people)
    ids_b = gen_database_b(people)
    ids_c = gen_database_c(people)
    ids_d = gen_database_d(people)

    fully_linkable = ids_a & ids_b & ids_c & ids_d
    in_at_least_two = {}
    for p in people:
        n = sum(p["id"] in s for s in (ids_a, ids_b, ids_c, ids_d))
        in_at_least_two[p["id"]] = n

    # Private ground-truth answer key — DO NOT import this into the app.
    answer_key = {
        "note": "Ground truth for verifying the matching engine. Never import this file.",
        "total_people": N_PEOPLE,
        "coverage": {"database_a": len(ids_a), "database_b": len(ids_b),
                     "database_c": len(ids_c), "database_d": len(ids_d)},
        "fully_linkable_across_all_4": sorted(fully_linkable),
        "fully_linkable_count": len(fully_linkable),
        "people": {
            str(p["id"]): {
                "full_name": p["full_name"], "email": p["email"], "phone": p["phone"],
                "username": p["username"], "member_id": p["member_id"],
                "in_sources": sorted([
                    n for n, s in [("A", ids_a), ("B", ids_b), ("C", ids_c), ("D", ids_d)]
                    if p["id"] in s
                ]),
            } for p in people
        },
    }
    with open(os.path.join(OUT_DIR, "answer_key.json"), "w") as f:
        json.dump(answer_key, f, indent=2)

    print(f"\nFully linkable across all 4 sources: {len(fully_linkable)} people")
    print(f"answer_key.json written (private — do not import, do not show in the demo video)")
    print("\nPick any id from fully_linkable_across_all_4 to demo, e.g.:")
    sample_id = sorted(fully_linkable)[0]
    p = [x for x in people if x["id"] == sample_id][0]
    print(f"  Person #{sample_id}: {p['full_name']} — search email = {p['email']}")
    print(f"  (Note: Database C has NO email column, so this person is only reachable")
    print(f"   there via progressive enrichment through phone or username.)")
