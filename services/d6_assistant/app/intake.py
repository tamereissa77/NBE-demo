"""Upload checks for D6 file chat: refuse a bad file at the door, with a reason the employee can act on.

Checked before any conversion or model call, in this order: size, type (by extension), then the content itself
(is it really that type, is it password-protected, is it damaged). The extension is never trusted on its own: a
program renamed to .pdf is refused as "not a PDF". Every refusal carries a stable `code` for the portal and the
tests and a message in the user's language.

Pure Python plus pypdfium2 and Pillow; no service calls.
"""
import io
import os
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

MAX_MB = float(os.getenv("D6_MAX_UPLOAD_MB", "20"))
MAX_FILES = int(os.getenv("D6_MAX_FILES", "5"))            # files attached to one conversation at a time
IMAGES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
SHEETS = (".xlsx", ".xlsm", ".csv", ".tsv")
TEXT = (".txt", ".md", ".html", ".htm", ".csv", ".tsv")
# Office Open XML files are ZIP archives; this is the part each kind must contain
OFFICE = {".docx": "word/document.xml", ".pptx": "ppt/presentation.xml", ".xlsx": "xl/workbook.xml", ".xlsm": "xl/workbook.xml"}
ACCEPTED = (".pdf", *OFFICE, ".html", ".htm", ".md", ".txt", ".csv", ".tsv", *IMAGES)
OLD_OFFICE = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx"}
OLE = bytes.fromhex("d0cf11e0a1b11ae1")                    # Office 97-2003 container; also wraps a password-protected .docx/.xlsx
ENCRYPTED = "EncryptedPackage".encode("utf-16-le")         # the stream a password-protected Office file keeps its content in
NAMES = {".pdf": ("PDF", "PDF"), ".docx": ("Word document", "مستند Word"), ".pptx": ("PowerPoint presentation", "عرض PowerPoint"),
         ".xlsx": ("Excel workbook", "مصنف Excel"), ".xlsm": ("Excel workbook", "مصنف Excel"), "image": ("image", "صورة"),
         "text": ("text file", "ملف نصي")}
SUPPORTED = {"en": "PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV, images (PNG, JPG), HTML, Markdown and text",
             "ar": "PDF و Word (.docx) و PowerPoint (.pptx) و Excel (.xlsx) و CSV والصور (PNG, JPG) و HTML و Markdown والملفات النصية"}

MESSAGES = {
    "too_large": ("This file is {size} MB. The largest file you can attach is {limit} MB.",
                  "حجم هذا الملف {size} ميجابايت. أقصى حجم يمكن إرفاقه هو {limit} ميجابايت."),
    "empty": ("This file is empty (0 bytes).", "هذا الملف فارغ (0 بايت)."),
    "unsupported_type": ("Files of type {ext} cannot be attached. Supported: {supported}.",
                         "لا يمكن إرفاق ملفات من نوع {ext}. الأنواع المدعومة: {supported}."),
    "old_format": ("The old Office format ({ext}) is not supported. Open the file and save it as {new}, then attach it again.",
                   "صيغة Office القديمة ({ext}) غير مدعومة. افتح الملف واحفظه بصيغة {new} ثم أرفقه من جديد."),
    "wrong_content": ("This file is named {ext} but its content is not a valid {kind}. Check that you picked the right file.",
                      "اسم هذا الملف ينتهي بـ {ext} لكن محتواه ليس {kind} صالحاً. تأكد من اختيار الملف الصحيح."),
    "password_protected": ("This {kind} is protected with a password, so it cannot be read. Remove the password and attach it again.",
                           "هذا الملف ({kind}) محمي بكلمة مرور ولا يمكن قراءته. أزل كلمة المرور ثم أرفقه من جديد."),
    "damaged": ("This {kind} is damaged or incomplete and cannot be opened. Try exporting or downloading it again.",
                "هذا الملف ({kind}) تالف أو غير مكتمل ولا يمكن فتحه. حاول تصديره أو تنزيله من جديد."),
    "too_many_files": ("You can attach up to {limit} files at a time. Remove one before adding another.",
                       "يمكن إرفاق {limit} ملفات كحد أقصى في المرة الواحدة. احذف ملفاً قبل إضافة آخر."),
    "no_text": ("No readable text was found in this file.", "لم يُعثر على نص مقروء في هذا الملف."),
    "unreadable": ("This file could not be read. It may be damaged or in an unusual format.",
                   "تعذّرت قراءة هذا الملف. قد يكون تالفاً أو بصيغة غير معتادة."),
}
STATUS = {"too_large": 413, "unsupported_type": 415, "old_format": 415}        # everything else: 422


class Rejected(Exception):
    """A refused upload: `status` for HTTP, `detail` = {code, message} for the portal."""

    def __init__(self, code: str, lang: str = "en", **facts) -> None:
        en, ar = MESSAGES[code]
        self.status = STATUS.get(code, 422)
        self.detail = {"code": code, "message": (ar if lang == "ar" else en).format(**facts)}
        super().__init__(self.detail["message"])


def limits(lang: str = "en") -> dict:
    return {"max_mb": MAX_MB, "max_files": MAX_FILES, "types": list(ACCEPTED), "supported": SUPPORTED["ar" if lang == "ar" else "en"]}


def check(name: str, data: bytes, lang: str = "en") -> None:
    """Raise Rejected unless the file is something file chat can read."""
    lang = "ar" if lang == "ar" else "en"
    kind = lambda key: NAMES[key][lang == "ar"]  # noqa: E731
    ext = Path(name).suffix.lower()
    if len(data) > MAX_MB * 1024 * 1024:
        raise Rejected("too_large", lang, size=f"{len(data) / 1024 / 1024:.1f}", limit=f"{MAX_MB:g}")
    if ext in OLD_OFFICE:
        raise Rejected("old_format", lang, ext=ext, new=OLD_OFFICE[ext])
    if ext not in ACCEPTED:
        raise Rejected("unsupported_type", lang, ext=ext or ("بدون امتداد" if lang == "ar" else "with no extension"), supported=SUPPORTED[lang])
    if not data:
        raise Rejected("empty", lang)

    if ext == ".pdf":
        if b"%PDF-" not in data[:1024]:
            raise Rejected("wrong_content", lang, ext=ext, kind=kind(ext))
        try:
            pdf = pdfium.PdfDocument(data)
            if len(pdf) == 0:
                raise Rejected("damaged", lang, kind=kind(ext))
        except pdfium.PdfiumError as exc:
            # A PDF that only restricts printing or copying opens normally; this is one that needs a password to open
            raise Rejected("password_protected" if "password" in str(exc).lower() else "damaged", lang, kind=kind(ext)) from exc
    elif ext in OFFICE:
        if data[:8] == OLE:
            # Either a password-protected file or an old-format file saved under the new extension
            raise Rejected("password_protected" if ENCRYPTED in data else "wrong_content", lang, ext=ext, kind=kind(ext))
        if data[:2] != b"PK":
            raise Rejected("wrong_content", lang, ext=ext, kind=kind(ext))
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if z.testzip() is not None:
                    raise Rejected("damaged", lang, kind=kind(ext))
        except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
            raise Rejected("damaged", lang, kind=kind(ext)) from exc
        if OFFICE[ext] not in names:                         # a valid Office file of another kind, or some other ZIP
            raise Rejected("wrong_content", lang, ext=ext, kind=kind(ext))
    elif ext in IMAGES:
        try:
            Image.open(io.BytesIO(data)).verify()
        except Exception as exc:  # noqa: BLE001 - Pillow raises many types for a broken image
            head_ok = data[:3] in (b"\x89PN", b"\xff\xd8\xff", b"RIF", b"BM\x00", b"II*", b"MM\x00") or data[:2] == b"BM"
            raise Rejected("damaged" if head_ok else "wrong_content", lang, ext=ext, kind=kind("image")) from exc
    elif ext in TEXT:
        if b"\x00" in data[:8192] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):       # NUL bytes: binary, unless UTF-16
            raise Rejected("wrong_content", lang, ext=ext, kind=kind("text"))
