"""Spreadsheets for D6 file chat: Excel workbooks (.xlsx, .xlsm) and delimited text (.csv, .tsv).

Each sheet becomes one part of the file: a Markdown table the model can read row by row, preceded by figures
computed here from ALL rows (sums, averages, counts per category, totals per category). A language model reads
a table well but adds up a column badly (in testing it was off on every total over 40 rows), and a manager's
first questions about a sheet are totals and counts, so those are given to it exactly rather than left to it.

Pure Python on openpyxl and the standard library; no service calls.
"""
import csv
import io
import re
from datetime import date, datetime, time

from openpyxl import load_workbook

TYPES = (".xlsx", ".xlsm", ".csv", ".tsv")
MAX_ROWS = 300            # rows written out per sheet; the computed figures always cover every row
MAX_GROUPS = 12           # a text column with at most this many distinct values is treated as a category
ID_HEADER = re.compile(r"\b(id|no|number|code|ref|year)\b|رقم|كود|مسلسل|سنة", re.I)
RATE_HEADER = re.compile(r"%|\b(rate|ratio|percent|price|score)\b|نسبة|نسبه|معدل|سعر", re.I)     # averaged, never added up
NUMBER = re.compile(r"^-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")


class SheetError(ValueError):
    """The file cannot be read as a spreadsheet; the message is safe to show to the user."""


def _value(v):
    """A cell as the value it means: numbers stay numbers (for the computed figures), the rest becomes clean text."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else round(v, 6)
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == time(0) else v.isoformat(sep=" ", timespec="minutes")
    if isinstance(v, (date, time)):
        return v.isoformat()
    return re.sub(r"\s+", " ", str(v)).strip()


def _number(text: str):
    """Text from a CSV cell as a number when it is written as one ("1,250,000", "7.5", Arabic-Indic digits)."""
    t = text.translate(ARABIC_DIGITS)
    if not NUMBER.match(t):
        return text
    n = float(t.replace(",", ""))
    return int(n) if n.is_integer() else n


def _fmt(v) -> str:
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


def _shape(name: str, grid: list[list]) -> dict | None:
    """Raw rows -> {name, title, header, rows}. Bank reports put a title (and blank rows) above the header row:
    the header is the first row that is at least 60% as wide as the widest row; anything above it is the title."""
    at = [i for i, r in enumerate(grid) if any(c != "" for c in r)]       # where each kept row sits in the file
    grid = [grid[i] for i in at]
    if not grid:
        return None
    width = max(max((i + 1 for i, c in enumerate(r) if c != ""), default=0) for r in grid)
    grid = [list(r[:width]) + [""] * (width - len(r)) for r in grid]
    filled = [sum(c != "" for c in r) for r in grid]
    head = next(i for i, n in enumerate(filled) if n >= max(1, 0.6 * max(filled)))
    header = [str(c) if c != "" else f"Column {i + 1}" for i, c in enumerate(grid[head])]
    title = " / ".join(str(c) for r in grid[:head] for c in r if c != "")
    # header_row: the header's position in the file (0 = first line), which is what pandas needs as `header=`
    # header_kept: the same, not counting blank lines, which is how pandas counts in a CSV
    return {"name": name, "title": title, "header": header, "rows": grid[head + 1:], "header_row": at[head], "header_kept": head}


def _columns(header: list[str], rows: list[list]) -> list[dict]:
    """Each column as a programmer needs it: its kind, and its values when it is a category."""
    out = []
    for i, name in enumerate(header):
        vals = [r[i] for r in rows if r[i] != ""]
        kind = ("number" if vals and all(isinstance(v, (int, float)) for v in vals) else
                "date" if vals and all(isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v) for v in vals) else "text")
        col = {"name": name, "kind": kind}
        distinct = list(dict.fromkeys(vals))
        if kind == "text" and 0 < len(distinct) <= MAX_GROUPS:
            col["values"] = distinct
        out.append(col)
    return out


def _profile(header: list[str], rows: list[list]) -> list[str]:
    """Exact figures over all rows: per numeric column, per category column, and each numeric total per category."""
    cols = list(zip(*rows)) if rows else []
    numeric, category = [], []
    for name, col in zip(header, cols):
        vals = [v for v in col if v != ""]
        nums = [v for v in vals if isinstance(v, (int, float))]
        if len(nums) >= 2 and len(nums) >= 0.9 * len(vals):
            if not (ID_HEADER.search(name) and all(isinstance(v, int) for v in nums)):       # an account number is not a quantity
                numeric.append((name, col))
        elif vals and len(set(vals)) <= min(MAX_GROUPS, max(1, len(vals) // 2)):
            category.append((name, col))
    out = []
    for name, col in numeric:
        nums = [v for v in col if isinstance(v, (int, float))]
        total = "" if RATE_HEADER.search(name) else f"sum {_fmt(sum(nums))}; "
        out.append(f"- {name}: {total}average {_fmt(round(sum(nums) / len(nums), 2))}; "
                   f"minimum {_fmt(min(nums))}; maximum {_fmt(max(nums))}; {len(nums)} values")
    for name, col in category[:4]:
        counts: dict = {}
        for v in col:
            if v != "":
                counts[v] = counts.get(v, 0) + 1
        out.append(f"- Rows per {name}: " + "; ".join(f"{k} {n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])))
        for num_name, num_col in numeric[:4]:
            totals: dict = {}
            for k, v in zip(col, num_col):
                if k != "" and isinstance(v, (int, float)):
                    totals.setdefault(k, []).append(v)
            rate = bool(RATE_HEADER.search(num_name))
            figures = {k: round(sum(v) / len(v), 2) if rate else round(sum(v), 2) for k, v in totals.items()}
            out.append(f"- {'Average' if rate else 'Total'} {num_name} per {name}: " +
                       "; ".join(f"{k} {_fmt(t)}" for k, t in sorted(figures.items(), key=lambda kv: -kv[1])))
    return out


def _text(sheet: dict) -> str:
    header, rows = sheet["header"], sheet["rows"]
    esc = lambda v: _fmt(v).replace("|", "\\|") if not isinstance(v, str) else v.replace("|", "\\|")  # noqa: E731
    lines = [f"{len(rows)} data rows, {len(header)} columns: {', '.join(header)}"]
    if sheet["title"]:
        lines.insert(0, f"Title: {sheet['title']}")
    figures = _profile(header, rows)
    if figures:
        lines += ["", f"Figures computed exactly from all {len(rows)} rows:", *figures]
    shown = rows[:MAX_ROWS]
    if len(rows) > MAX_ROWS:
        lines += ["", f"The table below shows the first {MAX_ROWS} of {len(rows)} rows; the figures above cover all of them."]
    lines += ["", "| " + " | ".join(header) + " |", "|" + " --- |" * len(header), *("| " + " | ".join(esc(v) for v in r) + " |" for r in shown)]
    return "\n".join(lines)


def _csv_grid(data: bytes, tab: bool) -> tuple[list[list], str, str]:
    for enc in ("utf-8-sig", "cp1256", "latin-1"):          # Excel on an Arabic Windows saves CSV as cp1256
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if tab:
        delim = "\t"
    else:
        try:
            delim = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
    return [[_number(c.strip()) for c in row] for row in csv.reader(io.StringIO(text), delimiter=delim)], enc, delim


def read(name: str, data: bytes) -> dict:
    """{parts, how, sheets, hidden} for an uploaded spreadsheet. A part: {page, label, text}."""
    suffix = name[name.rfind("."):].lower()
    hidden, how_read = 0, {}
    if suffix in (".csv", ".tsv"):
        grid, enc, delim = _csv_grid(data, suffix == ".tsv")
        shaped, how_read = [_shape(name, grid)], {"encoding": enc, "delimiter": delim}
    else:
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)       # data_only: a formula's last result
        except Exception as exc:  # noqa: BLE001 - a password-protected or damaged workbook is the user's to fix
            raise SheetError(f"This workbook could not be opened ({type(exc).__name__}). Is it password-protected or damaged?") from exc
        shaped = []
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                hidden += 1
                continue
            shaped.append(_shape(ws.title, [[_value(c) for c in row] for row in ws.iter_rows(values_only=True)]))
    sheets = [s for s in shaped if s]
    if not sheets:
        raise SheetError("No data was found in this spreadsheet.")
    parts = [{"page": i, "label": f"Sheet: {s['name']}", "text": _text(s)} for i, s in enumerate(sheets, start=1)]
    how = f"spreadsheet reader ({len(sheets)} sheet(s), {sum(len(s['rows']) for s in sheets):,} rows)" + (f"; {hidden} hidden sheet(s) skipped" if hidden else "")
    return {"parts": parts, "how": how, "sheets": [{"name": s["name"], "rows": len(s["rows"]), "columns": len(s["header"]), "header": s["header"], "header_row": s["header_row"],
                        "header_kept": s["header_kept"], "columns": _columns(s["header"], s["rows"]), "sample": s["rows"][:3], **how_read} for s in sheets]}
