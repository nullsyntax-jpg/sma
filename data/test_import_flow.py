import requests, json, time, sys

BASE = "http://localhost:8833/api"

def upload_and_process(source_id, filepath):
    with open(filepath, "rb") as f:
        resp = requests.post(f"{BASE}/sources/{source_id}/upload", files={"file": f}).json()
    batch_id = resp["batch_id"]
    mapping = {col: resp["suggested_mapping"][col]["canonical_field"] for col in resp["columns"]}
    print(f"\n=== {filepath} -> batch {batch_id} ===")
    print("suggested mapping:", mapping)
    requests.post(f"{BASE}/batches/{batch_id}/mapping", data={"mapping": json.dumps(mapping)})
    requests.post(f"{BASE}/batches/{batch_id}/process")
    for _ in range(20):
        time.sleep(0.5)
        status = requests.get(f"{BASE}/batches/{batch_id}/status").json()
        if status["status"] in ("completed", "completed_with_errors", "failed"):
            break
    print("final status:", status)
    return status

if __name__ == "__main__":
    sid_a, sid_b, sid_c, sid_d = sys.argv[1:5]
    search_field = sys.argv[5] if len(sys.argv) > 5 else "email"
    search_value = sys.argv[6] if len(sys.argv) > 6 else "john@example.com"

    upload_and_process(sid_a, "database_a_hr.csv")
    upload_and_process(sid_b, "database_b_directory.csv")
    upload_and_process(sid_c, "database_c_contacts.csv")
    upload_and_process(sid_d, "database_d_membership.csv")

    print(f"\n=== SEARCH TEST: {search_field}={search_value} ===")
    r = requests.get(f"{BASE}/search", params={"field": search_field, "value": search_value}).json()
    print(json.dumps(r, indent=2))

    print("\n=== STATS ===")
    print(json.dumps(requests.get(f"{BASE}/stats").json(), indent=2))
