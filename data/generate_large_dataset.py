"""
Generates a large CSV (default 150,000 rows) to demonstrate the ingestion
pipeline against the assignment's stated scale requirement (>100,000 rows,
architecture should support up to 1-2M+). This is separate from
generate_demo_data.py's small, hand-crafted files — those exist to make the
multi-hop enrichment trace clearly demoable in a video; this one exists to
prove the pipeline doesn't fall over or load everything into memory at
real scale.

Usage: python3 generate_large_dataset.py [num_rows]
"""
import csv, random, sys, os

random.seed(7)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 150_000
OUT = os.path.join(os.path.dirname(__file__), "database_e_large_scale.csv")

FIRST = ["Amit","Sara","Rahul","Neha","Vikram","Anjali","Karan","Divya","Rohan","Meera",
         "Arjun","Pooja","Sanjay","Kavya","Nikhil","Isha","Farhan","Ritu","Devansh","Simran"]
LAST = ["Sharma","Verma","Iyer","Reddy","Gupta","Nair","Kapoor","Mehta","Joshi","Chopra","Rao","Singh"]

with open(OUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["full_name", "email", "mobile_number"])
    # thread the John Doe hero record in once so it's still matchable at scale
    w.writerow(["John Doe", "john@example.com", "9876543210"])
    for i in range(N - 1):
        fn, ln = random.choice(FIRST), random.choice(LAST)
        email = f"{fn.lower()}.{ln.lower()}{i}@mail.com"
        phone = f"9{random.randint(100000000,999999999)}"
        w.writerow([f"{fn} {ln}", email, phone])

size_mb = os.path.getsize(OUT) / (1024 * 1024)
print(f"wrote {OUT}: {N:,} rows, {size_mb:.1f} MB")
