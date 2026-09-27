"""
QUICK/TINY demo dataset (~27 rows/file) — for a fast local smoke-test only.

For the actual assignment demo and video, use generate_realistic_dataset.py
instead: it produces a proper 1,000-person population with realistic
messiness and a verifiable answer key. This script exists only for a
30-second sanity check that the pipeline runs end to end.

Generates 4 demo CSVs with DIFFERENT schemas (per the assignment's example
table) and deliberately overlapping entities, so progressive enrichment has
real multi-hop chains to demonstrate.

Database A: full_name, email, mobile_number            (overlap: email+phone)
Database B: name, email_id, contact_no, address         (overlap: email)
Database C: username, phone, company                    (overlap: phone)
Database D: member_id, email, username                   (overlap: email+username)

Two "hero" entities (John Doe, Priya Sharma) are threaded across all four
files with slightly different formatting per source (case, spacing, phone
formatting) to also exercise normalization. The rest are filler records with
no cross-source overlap, to prove the system doesn't over-merge.

Output filenames are prefixed "quickdemo_" so they never collide with
generate_realistic_dataset.py's output files.
"""
import csv
import os
import random

OUT_DIR = os.path.dirname(__file__)
random.seed(42)

FIRST_NAMES = ["Amit", "Sara", "Rahul", "Neha", "Vikram", "Anjali", "Karan", "Divya",
               "Rohan", "Meera", "Arjun", "Pooja", "Sanjay", "Kavya", "Nikhil", "Isha"]
LAST_NAMES = ["Sharma", "Verma", "Iyer", "Reddy", "Gupta", "Nair", "Kapoor", "Mehta",
              "Joshi", "Chopra", "Rao", "Singh"]
COMPANIES = ["ABC Pvt Ltd", "Nimbus Tech", "Vertex Solutions", "BlueWave Retail",
             "Orion Labs", "Skyline Ventures", "Redwood Systems", "Apex Traders"]
CITIES = ["Mumbai", "Delhi", "Bengaluru", "Pune", "Hyderabad", "Chennai", "Kolkata"]

def rand_phone():
    return f"9{random.randint(100000000, 999999999)}"

def rand_email(first, last):
    return f"{first.lower()}.{last.lower()}{random.randint(1,99)}@mail.com"

# ---- Hero entity 1: John Doe (4-source chain, exercises normalization) ----
JOHN_EMAIL = "john@example.com"
JOHN_PHONE = "9876543210"
JOHN_USERNAME = "johndoe99"
JOHN_MEMBER_ID = "MEM1042"

# ---- Hero entity 2: Priya Sharma (3-source chain) ----
PRIYA_EMAIL = "priya.sharma@mail.com"
PRIYA_PHONE = "9123456780"
PRIYA_USERNAME = "priyas"

def write_csv(filename, header, rows):
    path = os.path.join(OUT_DIR, filename)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def gen_database_a(n_filler=25):
    rows = [["John Doe", JOHN_EMAIL, JOHN_PHONE]]  # exact formatting
    rows.append(["Priya Sharma", PRIYA_EMAIL, PRIYA_PHONE])
    for _ in range(n_filler):
        f, l = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
        rows.append([f"{f} {l}", rand_email(f, l), rand_phone()])
    write_csv("quickdemo_a_hr.csv", ["full_name", "email", "mobile_number"], rows)


def gen_database_b(n_filler=25):
    rows = [
        ["John Doe", JOHN_EMAIL.upper(), "987-654-3210", "12 MG Road, Mumbai"],  # case + phone formatting differ
        ["Priya Sharma", PRIYA_EMAIL, "91-23456780", "45 Brigade Road, Bengaluru"],
    ]
    for _ in range(n_filler):
        f, l = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
        rows.append([f"{f} {l}", rand_email(f, l), rand_phone(), f"{random.randint(1,99)} Park St, {random.choice(CITIES)}"])
    write_csv("quickdemo_b_business_directory.csv",
              ["name", "email_id", "contact_no", "address"], rows)


def gen_database_c(n_filler=25):
    rows = [
        [JOHN_USERNAME, JOHN_PHONE, "ABC Pvt Ltd"],       # links via phone, no email at all
        [PRIYA_USERNAME, PRIYA_PHONE, "Nimbus Tech"],
    ]
    for _ in range(n_filler):
        rows.append([f"user{random.randint(1000,9999)}", rand_phone(), random.choice(COMPANIES)])
    write_csv("quickdemo_c_startup_directory.csv", ["username", "phone", "company"], rows)


def gen_database_d(n_filler=25):
    rows = [
        [JOHN_MEMBER_ID, JOHN_EMAIL, JOHN_USERNAME],   # links via email AND username
    ]
    for _ in range(n_filler):
        rows.append([f"MEM{random.randint(2000,9999)}", "", f"user{random.randint(1000,9999)}"])
    write_csv("quickdemo_d_contact_database.csv", ["member_id", "email", "username"], rows)


if __name__ == "__main__":
    gen_database_a()
    gen_database_b()
    gen_database_c()
    gen_database_d()
    print("\nQuick demo data ready (tiny, ~27 rows/file — for a fast sanity check only).")
    print("For the actual assignment demo/video, use generate_realistic_dataset.py instead.")
    print("Import order for the clearest quick demo:")
    print("  1. quickdemo_a_hr.csv                -> creates John Doe & Priya Sharma entities")
    print("  2. quickdemo_c_startup_directory.csv -> enriches via phone (no email present!)")
    print("  3. quickdemo_b_business_directory.csv -> enriches via email (different case/phone format)")
    print("  4. quickdemo_d_contact_database.csv   -> enriches via email + username, adds member_id")
    print("\nThen search email=john@example.com and watch it cascade through phone -> username -> member_id.")
