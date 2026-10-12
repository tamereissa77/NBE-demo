"""Import the scanned corpus of the nbe-working repository into D2's seed data.

    python3 services/d2_chatdoc/tools/import_nbe_working.py --source ~/projects/nbe-working

Reads the page-level extraction JSON (Chandra OCR blocks) and the pre-cut crop images from the two
places nbe-working keeps them, and writes data/seed/d2/circulars/:

    manifest.json                         one entry per document: titles, type, pages, roles
    extractions/<doc_id>/page_NNN.json    normalised page JSON (blocks in reading order)
    crops/<doc_id>/page_NNN/<block>.png   one crop per block, the image shown beside a citation

Normalisation only, no content change: document ids use underscores everywhere (nbe-working mixes
`legal_circular_3` and `legal-circular_4`), the document type is corrected (circulars 3 to 5 were
typed SOP), and the machine-specific page_image_path is dropped (page images are not shipped: the
citation panel shows crops). Passage building happens at ingest time in app/scans.py.

Standard library only. Runs on the host, not in a container; D2 itself never needs nbe-working.
"""
import argparse
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
# Later roots win when a document appears in both (the orchestrator output is the newer extraction).
SOURCE_ROOTS = ("data/legacy/pipeline_output", "pipeline_output")
ALL_ROLES = ["teller", "legal_counsel", "manager"]
# Same access rule as nbe-working's role_doc_filter: the teller sees the RTGS guide only.
DOCS = {
    "rtgs": {"type": "sop", "roles": ALL_ROLES,
             "title_ar": "دليل إجراءات نظام التسوية اللحظية متعدد العملات (RTGS)",
             "title_en": "Multi-currency RTGS procedures guide"},
}


def doc_entry(doc_id: str) -> dict:
    if doc_id in DOCS:
        return DOCS[doc_id]
    n = doc_id.rsplit("_", 1)[-1]
    return {"type": "legal_circular", "roles": ["legal_counsel", "manager"],
            "title_ar": f"تعميم قانوني رقم {n}", "title_en": f"Legal circular no. {n}"}


def norm(name: str) -> str:
    return name.replace("-", "_")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, type=Path, help="path to the nbe-working checkout")
    ap.add_argument("--out", type=Path, default=REPO / "data/seed/d2/circulars")
    args = ap.parse_args()
    source = args.source.expanduser()

    pages: dict[str, dict[int, tuple[Path, Path]]] = {}       # doc_id -> page_num -> (page json, its root)
    for root in SOURCE_ROOTS:
        for f in sorted((source / root / "extractions").glob("*/page_*.json")):
            pages.setdefault(norm(f.parent.name), {})[int(f.stem.split("_")[1])] = (f, source / root)
    if not pages:
        raise SystemExit(f"no extraction JSON found under {source} ({', '.join(SOURCE_ROOTS)})")

    for sub in ("extractions", "crops"):
        shutil.rmtree(args.out / sub, ignore_errors=True)
    manifest, n_blocks = [], 0
    for doc_id in sorted(pages):
        entry, blocks_in_doc = doc_entry(doc_id), 0
        for page_num, (f, root) in sorted(pages[doc_id].items()):
            page = json.loads(f.read_text(encoding="utf-8"))
            blocks = []
            for b in page["blocks"]:
                crop_src = root / b["crop_path"]
                crop_rel = Path("crops") / doc_id / f"page_{page_num:03d}" / norm(crop_src.name)
                (args.out / crop_rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(crop_src, args.out / crop_rel)
                blocks.append({"block_id": norm(b["block_id"]), "block_type": b["block_type"], "text": b.get("text") or "",
                               "table_data": b.get("table_data"), "bbox": b.get("bbox"), "crop_path": crop_rel.as_posix()})
            out = args.out / "extractions" / doc_id / f"page_{page_num:03d}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"doc_id": doc_id, "page_num": page_num, "original_size": page.get("original_size"),
                                       "inference_size": page.get("inference_size", page.get("original_size")),
                                       "blocks": blocks}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            blocks_in_doc += len(blocks)
            source_name = page.get("doc_name", "")
        manifest.append({"doc_id": doc_id, "source_name": source_name, **entry, "lang": "ar",
                         "pages": len(pages[doc_id]), "blocks": blocks_in_doc})
        n_blocks += blocks_in_doc
        print(f"  {doc_id:<18} {len(pages[doc_id]):>3} pages  {blocks_in_doc:>4} blocks")
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(manifest)} documents, {sum(m['pages'] for m in manifest)} pages, {n_blocks} blocks -> {args.out}")


if __name__ == "__main__":
    main()
