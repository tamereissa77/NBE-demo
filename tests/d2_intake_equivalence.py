"""D2 intake gives the seed corpus back: every document of data/seed/d2/circulars, taken from
nbe-working's extraction output through app/intake.py, must come out identical to the seed copy
(manifest entry, page JSON byte for byte, crop images byte for byte, and the passages built from them).

This is the check that a document added through POST /upload is stored and cited exactly like the six
that were imported. It needs no GPU and no running service: the OCR output is the input.

    docker run --rm -v "$(pwd)/tests:/tests:ro" -v "$(pwd)/data:/data:ro" -v ~/projects/nbe-working:/src:ro \
      nbe-d2:latest python /tests/d2_intake_equivalence.py
"""
import filecmp
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/srv")
from app import intake, scans  # noqa: E402

SEED = Path("/data/seed/d2/circulars")
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/src")
ROOTS = ("data/legacy/pipeline_output", "pipeline_output")     # later wins, as in tools/import_nbe_working.py

seed_manifest = json.loads((SEED / "manifest.json").read_text(encoding="utf-8"))
out = Path(tempfile.mkdtemp())
entries, failures = [], []
for doc in seed_manifest:
    raw = None
    for root in ROOTS:
        for d in (SRC / root / "extractions").glob("*"):
            if intake.norm(d.name) == doc["doc_id"]:
                raw = (SRC / root, d.name)
    if not raw:
        failures.append(f"{doc['doc_id']}: no extraction found in nbe-working")
        continue
    entry = intake.normalise(raw[0], raw[1], out, {k: doc[k] for k in ("type", "roles", "title_ar", "title_en")})
    entries.append(entry)
    if entry != doc:
        failures.append(f"{doc['doc_id']}: manifest entry differs: {entry} != {doc}")
    for sub in ("extractions", "crops"):
        a, b = SEED / sub / doc["doc_id"], out / sub / doc["doc_id"]
        fa, fb = (sorted(p.relative_to(x).as_posix() for p in x.rglob("*") if p.is_file()) for x in (a, b))
        if fa != fb:
            failures.append(f"{doc['doc_id']}: {sub} file lists differ ({len(fa)} seed, {len(fb)} intake)")
            continue
        _, mismatch, errors = filecmp.cmpfiles(a, b, fa, shallow=False)
        if mismatch or errors:
            failures.append(f"{doc['doc_id']}: {len(mismatch) + len(errors)} of {len(fa)} {sub} files differ")
    print(f"  {doc['doc_id']:<18} {entry['pages']:>3} pages {entry['blocks']:>4} blocks")

(out / "manifest.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
seed_passages, intake_passages = scans.load(SEED)["passages"], scans.load(out)["passages"]
if seed_passages != intake_passages:
    failures.append(f"passages differ ({len(seed_passages)} seed, {len(intake_passages)} intake)")
print(f"{len(entries)} documents, {len(seed_passages)} seed passages, {len(intake_passages)} intake passages")
print("\n".join(["FAIL"] + failures) if failures else "PASS: intake output is identical to the seed corpus")
sys.exit(1 if failures else 0)
