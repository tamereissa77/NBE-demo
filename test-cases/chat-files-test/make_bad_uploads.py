"""Generates the upload-validation test files for D6 into bad-uploads/ (next to this script).

    python make_bad_uploads.py        (needs pypdf, cryptography, msoffcrypto-tool, python-docx, openpyxl)

Files that must be refused (too large, wrong or disguised type, password-protected, damaged, empty, old format)
and a few that must still be accepted. Expectations are in bad-uploads/uploads.json. Everything is synthetic.
"""
import io
import os
import random
from pathlib import Path

import msoffcrypto
from docx import Document
from openpyxl import Workbook
from pypdf import PdfReader, PdfWriter

here = Path(__file__).parent
out = here / "bad-uploads"
out.mkdir(exist_ok=True)
rnd = random.Random(7)
junk = lambda n: bytes(rnd.getrandbits(8) for _ in range(n))  # noqa: E731
real_pdf = (here / "Reg_circular.pdf").read_bytes()
MZ = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + junk(4000)          # Windows program header
OLE = bytes.fromhex("d0cf11e0a1b11ae1") + junk(4000)                                          # Word/Excel 97-2003 container


def pdf_with_password(user: str, owner: str) -> bytes:
    w = PdfWriter()
    for page in PdfReader(io.BytesIO(real_pdf)).pages:
        w.add_page(page)
    w.encrypt(user_password=user, owner_password=owner, algorithm="AES-256")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def office_with_password(plain: bytes) -> bytes:
    buf = io.BytesIO()
    msoffcrypto.OfficeFile(io.BytesIO(plain)).encrypt("secret", buf)
    return buf.getvalue()


doc = Document()
doc.add_heading("Branch opening hours", 1)
doc.add_paragraph("All branches open from 8:30 to 15:00, Sunday to Thursday. The Cairo Main branch also opens on Saturday from 10:00 to 14:00.")
buf = io.BytesIO()
doc.save(buf)
docx = buf.getvalue()

wb = Workbook()
wb.active.append(["Branch", "Staff"])
wb.active.append(["Giza", 28])
buf = io.BytesIO()
wb.save(buf)
xlsx = buf.getvalue()

files = {
    # --- must be refused
    "too_big.pdf": real_pdf + b"\n%" + b"0" * (25 * 1024 * 1024),          # a valid PDF padded to 25 MB
    "program.exe": MZ,
    "archive.zip": b"PK\x03\x04" + junk(2000),
    "video.mp4": b"\x00\x00\x00\x18ftypmp42" + junk(3000),
    "disguised_program.pdf": MZ,                                           # a program renamed to .pdf
    "disguised_program.docx": MZ,
    "binary_named.txt": junk(3000),
    "protected.pdf": pdf_with_password("secret", "owner"),
    "protected.docx": office_with_password(docx),
    "protected.xlsx": office_with_password(xlsx),
    "damaged.pdf": b"%PDF-1.7\n" + junk(6000),
    "cut_in_half.docx": docx[: len(docx) // 2],
    "damaged.xlsx": b"PK\x03\x04" + junk(5000),
    "damaged.png": b"\x89PNG\r\n\x1a\n" + junk(3000),
    "excel_renamed.docx": xlsx,                                            # a real workbook with the wrong extension
    "empty.pdf": b"",
    "empty.txt": b"",
    "old_word.doc": OLE,
    "old_excel.xls": OLE,
    "no_extension": b"some text without a file extension",
    # --- must still be accepted
    "ok_opens_without_password.pdf": pdf_with_password("", "owner"),       # printing restricted, but anyone can open it
    "ok_small.docx": docx,
    "ok_small.xlsx": xlsx,
    "OK_UPPERCASE.PDF": real_pdf,
    "ok_arabic_ملاحظات.txt": "مواعيد العمل من 8:30 صباحاً إلى 3:00 عصراً من الأحد إلى الخميس.".encode("utf-8"),
}
for name, data in files.items():
    (out / name).write_bytes(data)
    print(f"{len(data):>10,}  {name}")
