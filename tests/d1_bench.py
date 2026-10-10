"""D1's upload flow on the benchmark files: are the planted forgeries flagged, what else is flagged, how long does a file take.
The files come from scripts/d1_bench_docs.py (invented applicants; 10 forgeries and one false positive planted on purpose).
Needs the running service and its document reader:
    docker run --rm --network nbe-core -v ./tests:/tests:ro -v ./data/generated/d1_bench:/bench:ro nbe-d1 python /tests/d1_bench.py

Each loan file is opened with what the applicant declared, its documents are uploaded under their true types,
read and checked, and the file is deleted again. A document counts as flagged when a finding names it, raised
or waiting for a reading to be confirmed; a missing document or a missing type is not a finding.
"""
import collections
import json
import os
import sys
import time
from pathlib import Path

import httpx

BENCH = Path(sys.argv[1] if len(sys.argv) > 1 else "/bench")
API = os.getenv("D1_URL", "http://nbe-d1:8000")
NOT_FINDINGS = ("missing_document", "type_needed")


def main() -> None:
    manifest = json.loads((BENCH / "manifest.json").read_text(encoding="utf-8"))
    rows, times, per_page = [], [], []
    with httpx.Client(base_url=API, timeout=1800) as api:
        for pack in manifest["packs"]:
            cid = api.post("/cases", json=pack["form"]).json()["id"]
            try:
                ids = {}
                for doc in pack["documents"]:
                    r = api.post(f"/cases/{cid}/documents", data={"doc_type": doc["doc_type"]}, files={"file": ("upload", (BENCH / doc["file"]).read_bytes())})
                    r.raise_for_status()
                    ids[r.json()["documents"][-1]["id"]] = doc
                t = time.time()
                case = api.post(f"/cases/{cid}/verify").json()
                times.append(time.time() - t)
                per_page += [d["ms"] / 1000 for d in case["documents"] if d["ms"]]
                found = collections.defaultdict(list)
                for flag in case["result"]["flags"]:
                    if flag["rule"] not in NOT_FINDINGS:
                        for did in flag["documents"]:
                            found[did].append(flag["rule"] + ("?" if flag["status"] == "needs_confirmation" else ""))
                for did, doc in ids.items():
                    rows.append({**doc, "pack": pack["id"], "rules": sorted(set(found[did])),
                                 "unread": next(d["error"] for d in case["documents"] if d["id"] == did)})
                print(f"  {pack['id']}: {len(pack['documents'])} documents, {times[-1]:.0f} s, {case['result']['verdict']}", flush=True)
            finally:
                api.delete(f"/cases/{cid}")

    forged = [r for r in rows if r["forged"]]
    genuine = [r for r in rows if not r["forged"]]
    caught = [r for r in forged if r["rules"]]
    print(f"\nPlanted forgeries flagged: {len(caught)} of {len(forged)}   (documents: {len(rows)}; a rule followed by ? waits for a reading to be confirmed)")
    for r in forged:
        print(f"   {'caught' if r['rules'] else 'MISSED':<7} {r['file']:<28} {r['manipulation']:<28} {', '.join(r['rules'])}")
    flagged = [r for r in genuine if r["rules"]]
    forged_packs = {(r["pack"]) for r in forged}
    partner = [r for r in flagged if r["pack"] in forged_packs and not r.get("planned_false_positive")]
    planned = [r for r in flagged if r.get("planned_false_positive")]
    other = [r for r in flagged if r not in partner and r not in planned]
    print(f"\nGenuine documents flagged: {len(flagged)} of {len(genuine)}")
    print(f"   {len(partner)} in a file that holds a forgery (the other side of a mismatch, or a flag of their own):")
    for r in partner:
        print(f"      {r['file']:<28} {', '.join(r['rules'])}")
    print(f"   {len(planned)} planted false positive: " + ", ".join(f"{r['file']} ({', '.join(r['rules'])})" for r in planned))
    print(f"   {len(other)} in a clean file: " + ", ".join(f"{r['file']} ({', '.join(r['rules'])})" for r in other))
    unread = [r["file"] for r in rows if r["unread"]]
    print(f"\nDocuments the reader could not read: {len(unread)} {unread or ''}")
    print(f"Time per file: mean {sum(times) / len(times):.0f} s, longest {max(times):.0f} s; per document: mean {sum(per_page) / len(per_page):.1f} s")
    sys.exit(0 if len(caught) == len(forged) else 1)


if __name__ == "__main__":
    main()
