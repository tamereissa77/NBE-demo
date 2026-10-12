"""Scanned-document corpus for D2: circulars and procedure guides that exist only as page scans.

The pages were read offline by a layout OCR model (nbe-working's extraction service) into typed
blocks, each with a pre-cut crop image. This module turns those blocks into retrieval passages and
keeps, for every passage, the list of blocks it was built from, so a citation can show the exact
crops of the scan beside the answer.

Passages, not blocks, are indexed: the median block is under 100 characters (a salutation, a clause
number), which is too little to retrieve or ground an answer on. A passage is the run of blocks under
one heading on one page, capped at MAX_CHARS; a table is always its own passage.

Pure Python, no service calls: the loader runs at startup and the output feeds /admin/ingest.
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

MAX_CHARS = 1000
MIN_TAIL = 250               # a remainder shorter than this joins the passage before it (same page, same heading)
# Letterheads and page counters repeated on every page; they are neither headings nor content.
BOILERPLATE = re.compile(r"^\s*(البنك المركزي المصري(\s+CENTRAL BANK OF EGYPT)?|(ال)?صفح[ةه](\s+[\d٠-٩]+\s+من\s+[\d٠-٩]+)?"
                         r"|page\s+\d+(\s+of\s+\d+)?)\s*$", re.I)

# Who may read what is set per document in the manifest (`roles`); these are the labels for the UI.
ROLES = [
    {"id": "teller", "ar": "موظف صراف", "en": "Teller", "scope_ar": "إجراءات التشغيل", "scope_en": "Operating procedures"},
    {"id": "legal_counsel", "ar": "مستشار قانوني", "en": "Legal counsel", "scope_ar": "التعميمات القانونية", "scope_en": "Legal circulars"},
    {"id": "manager", "ar": "مدير", "en": "Manager", "scope_ar": "جميع الوثائق", "scope_en": "All documents"},
]
ROLE_IDS = {r["id"] for r in ROLES}


class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            if not self.rows:
                self.rows.append([])
            self.rows[-1].append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def table_rows(html: str) -> list[list[str]]:
    p = _Table()
    p.feed(html)
    return [r for r in p.rows if any(r)]


def table_text(rows: list[list[str]]) -> str:
    """One line per row, for embedding and for the prompt."""
    return "\n".join(" | ".join(r) for r in rows)


def table_markdown(rows: list[list[str]]) -> str:
    """GFM table for the citation panel's text view (the portal renders Markdown, not HTML)."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    line = lambda r: "| " + " | ".join(c.replace("|", "\\|") for c in r + [""] * (width - len(r))) + " |"  # noqa: E731
    return "\n".join([line(rows[0]), "|" + " --- |" * width, *(line(r) for r in rows[1:])])


def build_passages(doc: dict, pages: list[dict]) -> list[dict]:
    """Merge one document's OCR blocks into passages. Each passage: page, heading, text, display, blocks."""
    out: list[dict] = []
    heading = ""                 # last real section heading; carries across pages like a running title
    pending: list[dict] = []     # heading blocks not yet attached to a passage (their crops open the next one)
    cur: dict | None = None

    def ref(b: dict, page: int) -> dict:
        return {"id": b["block_id"], "page": page, "type": b["block_type"]}

    def emit(p: dict) -> None:
        p["heading"] = re.sub(r"\s+", " ", p["heading"]).strip()
        prev = out[-1] if out else None
        # A short remainder left by the size cap ("effective from 17 August") is useless without the text
        # before it: keep it with the passage it continues instead of indexing it alone
        if (prev and prev["block_type"] == p["block_type"] == "text" and prev["page"] == p["page"]
                and prev["heading"] == p["heading"] and len(p["text"]) < MIN_TAIL):
            prev["text"] += "\n" + p["text"]
            prev["display"] += "\n\n" + p["display"]
            prev["blocks"] += p["blocks"]
        elif p["block_type"] == "table" or len(f"{p['heading']} {p['text']}".split()) >= 3:
            p["id"] = f"{doc['doc_id']}_s{len(out):03d}"
            out.append(p)

    def flush() -> None:
        nonlocal cur
        if cur:
            cur["text"] = "\n".join(cur.pop("parts"))
            cur["display"] = cur["text"].replace("\n", "\n\n")
            emit(cur)
            cur = None

    def start(page: int, block_type: str) -> dict:
        nonlocal pending
        p = {"page": page, "heading": " — ".join(h["text"].strip() for h, _ in pending) or heading, "block_type": block_type,
             "blocks": [ref(h, pg) for h, pg in pending]}
        pending = []
        return p

    for page in sorted(pages, key=lambda p: p["page_num"]):
        flush()
        n = page["page_num"]
        for b in page["blocks"]:
            text, kind = (b.get("text") or "").strip(), b["block_type"]
            if kind == "footer" or (kind != "table" and (not text or BOILERPLATE.match(text))):
                continue
            if kind == "header":
                flush()
                heading = text
                pending.append((b, n))
            elif kind == "table" and b.get("table_data"):
                flush()
                rows = table_rows(b["table_data"])
                p = start(n, "table")
                p["blocks"].append(ref(b, n))
                emit({**p, "text": table_text(rows), "display": table_markdown(rows)})
            elif text:
                if cur and sum(map(len, cur["parts"])) + len(text) > MAX_CHARS:
                    flush()
                if cur is None:
                    cur = {**start(n, "text"), "parts": []}
                cur["parts"].append(text)
                cur["blocks"].append(ref(b, n))
    flush()
    if pending:                  # trailing headings with nothing under them (a cover page)
        p = start(pending[0][1], "text")
        emit({**p, "text": "", "display": ""})
    return out


def load(root: Path) -> dict | None:
    """{docs, passages, crops} for the corpus under `root`, or None when it is not installed."""
    if not (root / "manifest.json").exists():
        return None
    docs = {d["doc_id"]: d for d in json.loads((root / "manifest.json").read_text(encoding="utf-8"))}
    passages, crops = [], {}
    for doc_id, doc in docs.items():
        pages = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((root / "extractions" / doc_id).glob("page_*.json"))]
        for page in pages:
            for b in page["blocks"]:
                if b.get("crop_path"):       # a block the OCR gave no usable box has no crop image
                    crops[b["block_id"]] = (doc_id, root / b["crop_path"])
        for p in build_passages(doc, pages):
            # Same shape as D2's procedure sections: title line, heading line, then the body
            passages.append({**p, "doc_id": doc_id, "embed": f"{doc['title_ar']}\n{p['heading']}\n{p['text']}"})
        doc["passages"] = sum(1 for p in passages if p["doc_id"] == doc_id)
    return {"docs": docs, "passages": passages, "crops": crops}


def load_all(roots: list[Path]) -> dict | None:
    """The corpora under several roots as one (the seed corpus, then documents added by app/intake.py).
    A document id found again in a later root replaces the earlier one."""
    out: dict | None = None
    for root in roots:
        part = load(root)
        if not part:
            continue
        if out is None:
            out = part
            continue
        again = set(part["docs"]) & set(out["docs"])
        out["passages"] = [p for p in out["passages"] if p["doc_id"] not in again] + part["passages"]
        out["crops"] = {k: v for k, v in out["crops"].items() if v[0] not in again} | part["crops"]
        out["docs"] = {k: v for k, v in out["docs"].items() if k not in again} | part["docs"]
    return out
