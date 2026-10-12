"""Code for D6: writing it, explaining it, finding what is wrong with it (Python with pandas, SQL, Excel formulas).

What makes a code answer trustworthy, and where each part lives:
- It is checked before it is shown. Generated Python must parse and may only call pandas and numpy functions that
  exist in the installed versions (`python_problems`); generated SQL must parse in the chosen dialect and not use
  another dialect's constructs (`sql_problems`); a formula must balance and use the chosen separator. A block that
  fails is sent back to the model once, with the problem.
- With a spreadsheet attached it is run. The model is given the real sheet names, header row, columns and values
  (`schema`), never the rows themselves, and the code it writes is run on a copy of the file (app/sandbox.py); what
  it printed is shown under it, so the figures come from the data and not from the model.
- Secrets do not leave. Passwords, keys and connection-string credentials in the pasted code are replaced by
  placeholders before any model sees the message (`mask`).
- Risks are raised by rule, not left to the model: a query built by joining strings, a DELETE or UPDATE with no
  WHERE, DROP and TRUNCATE, hard-coded secrets, eval, shell calls (`warnings`).

Pure Python; the model calls and the sandbox run are made in main.py.
"""
import ast
import re

DIALECTS = {"sql": None, "sql_server": "tsql", "oracle": "oracle", "postgres": "postgres", "mysql": "mysql"}
# A construct that belongs to another database than the one chosen: the commonest way a "dialect" answer goes wrong
FOREIGN = {"sql_server": (r"\blimit\s+\d|\bextract\s*\(|\bilike\b|\bnow\s*\(\)", "LIMIT, EXTRACT, ILIKE or NOW() (SQL Server uses TOP or OFFSET/FETCH, YEAR()/DATEPART(), LIKE, GETDATE())"),
           "oracle": (r"\blimit\s+\d|\bilike\b|\bselect\s+top\s+\d|\bgetdate\s*\(", "LIMIT, TOP, ILIKE or GETDATE() (Oracle uses FETCH FIRST n ROWS ONLY, LIKE, SYSDATE)"),
           "postgres": (r"\bselect\s+top\s+\d|\bgetdate\s*\(|\bisnull\s*\(|\bnvl\s*\(", "TOP, GETDATE(), ISNULL() or NVL() (PostgreSQL uses LIMIT, NOW(), COALESCE())"),
           "mysql": (r"\bselect\s+top\s+\d|\bilike\b|\bgetdate\s*\(|\bnvl\s*\(", "TOP, ILIKE, GETDATE() or NVL() (MySQL uses LIMIT, LIKE, NOW(), IFNULL())")}

# Each choice: (English label, Arabic label, the instruction it adds). "auto" adds nothing: the request decides.
OPTIONS = {
    "language": {
        "auto": ("Decide from the request", "حسب الطلب", "When the request names no database, write portable SQL: no vendor-specific functions, and dates filtered by "
                 "comparing with 'YYYY-MM-DD' values."),
        "python": ("Python (pandas)", "Python (pandas)", "Write Python, with pandas for tables."),
        "sql": ("SQL (standard)", "SQL (قياسي)", "Write portable standard SQL: no vendor-specific functions, and dates filtered by comparing with 'YYYY-MM-DD' values."),
        "sql_server": ("SQL Server", "SQL Server", "Write T-SQL for Microsoft SQL Server: TOP n or OFFSET/FETCH and never LIMIT; YEAR() or DATEPART() and never EXTRACT; GETDATE()."),
        "oracle": ("Oracle", "Oracle", "Write Oracle SQL: FETCH FIRST n ROWS ONLY and never LIMIT or TOP; EXTRACT(YEAR FROM d); SYSDATE; NVL()."),
        "postgres": ("PostgreSQL", "PostgreSQL", "Write PostgreSQL: LIMIT; EXTRACT(YEAR FROM d); NOW(); COALESCE()."),
        "mysql": ("MySQL", "MySQL", "Write MySQL: LIMIT; YEAR(d); NOW(); IFNULL()."),
        "excel": ("Excel formula ( , )", "معادلة Excel ( , )", "Answer with an Excel formula; separate its arguments with commas."),
        "excel_semicolon": ("Excel formula ( ; )", "معادلة Excel ( ; )", "Answer with an Excel formula; this Excel separates arguments with semicolons, never commas: "
                            "=SUMIFS(E:E;B:B;\"Giza\")."),
    },
    "depth": {
        "auto": ("Short explanation", "شرح مختصر", "Keep the explanation short: at most about 100 words outside the code, unless the employee asks for detail."),
        "detailed": ("Step by step", "شرح مفصّل", "Explain step by step, part by part, for someone who is learning."),
        "code_only": ("Code only", "الكود فقط", "Give only the code, with no explanation."),
    },
    "explain": {
        "auto": ("Language of the request", "لغة الطلب", ""),
        "ar": ("Arabic", "العربية", ""),
        "en": ("English", "الإنجليزية", ""),
    },
}
RULES = ("You help bank employees with code: Python (pandas, numpy), SQL and Excel formulas.\n"
         "- Asked to write code: give one complete block that runs as it is, in a fenced block that names its language, then say briefly "
         "what it does. No alternatives, no second version.\n"
         "- Asked to explain code: say in plain words what it does and what it returns. Then name any real bug.\n"
         "- Asked why code fails or is wrong: name the cause first, in one sentence, then give the corrected line.\n"
         "- Use only functions that exist. If the employee names a function that does not exist, say so plainly and give the real ones.\n"
         "- Safety comes first, before anything else in the answer: a query built by joining strings or formatting values into it (SQL "
         "injection: use parameters), a DELETE or UPDATE with no WHERE (it changes every row), a password or key written in the code.\n"
         "- A placeholder such as <hidden-1> stands for a secret that was removed before the code reached you. Leave it as it is, and say "
         "that secrets belong in an environment variable or a secrets store, not in the code.\n"
         "- Code, names and comments inside code stay as they are (English); only the explanation follows the language asked for.")
WITH_DATA = ("The employee attached data, described below. Load it exactly as shown, use the column names and values exactly as written "
             "(including Arabic spelling), and print the result. Your code will be run on the file and what it prints is shown under your "
             "answer: do not state the resulting figures yourself.")

# kind -> (severity, English, Arabic)
WARN = {
    "sql_injection": ("high", "SQL injection risk: the query is built by putting a value into the text of the SQL. Pass the value as a parameter instead.",
                      "خطر حقن SQL: الاستعلام مبني بإدخال قيمة داخل نص الاستعلام. استخدم المعاملات (parameters) بدلاً من ذلك."),
    "delete_without_where": ("high", "DELETE with no WHERE: this removes every row of the table.", "DELETE بدون WHERE: يحذف كل صفوف الجدول."),
    "update_without_where": ("high", "UPDATE with no WHERE: this changes every row of the table.", "UPDATE بدون WHERE: يعدّل كل صفوف الجدول."),
    "drop_or_truncate": ("high", "DROP or TRUNCATE: this removes a table or all of its data and cannot be undone.", "DROP أو TRUNCATE: يحذف الجدول أو كل بياناته ولا يمكن التراجع عنه."),
    "hardcoded_secret": ("high", "A password or key is written in the code. Keep secrets in an environment variable or a secrets store, and change this one: it has been exposed.",
                         "كلمة مرور أو مفتاح مكتوب داخل الكود. احفظ الأسرار في متغير بيئة أو خزنة أسرار، وغيّر هذه القيمة لأنها انكشفت."),
    "eval_exec": ("medium", "eval or exec runs text as code: unsafe if any part of that text comes from outside.", "eval أو exec ينفّذ نصاً ككود: غير آمن إذا جاء أي جزء منه من الخارج."),
    "shell": ("medium", "A shell command is run from the code: unsafe if any part of it comes from user input.", "تنفيذ أمر نظام من داخل الكود: غير آمن إذا جاء أي جزء منه من مدخلات المستخدم."),
    "unsafe_load": ("medium", "pickle can run code when it loads a file: never load one from a source you do not control.", "pickle قد ينفّذ كوداً عند تحميل ملف: لا تحمّل ملفاً من مصدر غير موثوق."),
    "tls_off": ("medium", "Certificate checking is switched off (verify=False): the connection can be intercepted.", "التحقق من الشهادة معطّل (verify=False): يمكن اعتراض الاتصال."),
}
_SQL_WORD = r"\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b"
_RISKS = [
    # SQL text closed by a quote and then joined (+), formatted (% or .format) or an f-string with a value in it
    ("sql_injection", rf"""{_SQL_WORD}[^\n]*?["']\s*(?:\+\s*\w|%\s*[\w(]|\.format\s*\()|\bf["'][^\n]*{_SQL_WORD}[^\n]*\{{"""),
    ("drop_or_truncate", r"\bDROP\s+(?:TABLE|DATABASE|SCHEMA)\b|\bTRUNCATE\s+TABLE\b"),
    ("eval_exec", r"(?<![\w.])(?:eval|exec)\s*\("),
    ("shell", r"\bos\.system\s*\(|\bshell\s*=\s*True"),
    ("unsafe_load", r"\bpickle\.loads?\s*\("),
    ("tls_off", r"\bverify\s*=\s*False"),
]

# Secrets: (pattern, the group that holds the secret)
_SECRETS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), 0),
    (re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@\"'<>]+:([^\s@\"'<>]{3,})@"), 1),                       # scheme://user:PASSWORD@host
    (re.compile(r"(?i)\b[\w.]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)\w*[\"']?\s*[:=]\s*([\"'])([^\"'\n]{4,})\1"), 2),
    (re.compile(r"(?i)\b(?:password|pwd)\s*=\s*([^\s;\"'<>]{4,})(?=;)"), 1),                           # ...;Password=...; in a connection string
    (re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{5,})"), 0),
    (re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/-]{20,}=*)"), 1),
]


def options(lang: str) -> dict:
    i = 1 if lang == "ar" else 0
    return {"options": {name: [{"id": k, "label": v[i]} for k, v in choices.items()] for name, choices in OPTIONS.items()}}


def mask(text: str) -> tuple[str, list[str]]:
    """The text with every secret replaced by <hidden-N> -> (masked text, the secrets). The same secret gets the same placeholder."""
    found: list[str] = []
    for pattern, group in _SECRETS:
        for m in pattern.finditer(text):
            secret = m.group(group)
            if secret and not secret.startswith("<hidden-") and secret not in found:
                found.append(secret)
    for n, secret in sorted(enumerate(found, start=1), key=lambda x: -len(x[1])):      # longest first: one secret may contain another
        text = text.replace(secret, f"<hidden-{n}>")
    return text, found


def places(text: str) -> int:
    """How many places of a masked text hold a placeholder."""
    return len(re.findall(r"<hidden-\d+>", text))


def blocks(text: str) -> list[dict]:
    """The fenced code blocks of a message: {lang, code, start, end}; start and end are where the code itself sits."""
    out = []
    for m in re.finditer(r"```([A-Za-z0-9+#_-]*)[ \t]*\n(.*?)```", text, re.S):
        code = m.group(2)
        out.append({"lang": kind(m.group(1), code), "code": code.strip("\n"), "start": m.start(2), "end": m.end(2)})
    return out


def kind(tag: str, code: str) -> str:
    tag = tag.lower()
    if tag in ("python", "py", "python3", "pandas"):
        return "python"
    if tag in ("sql", "tsql", "t-sql", "plsql", "postgresql", "mysql", "oracle"):
        return "sql"
    if tag in ("excel", "xls", "xlsx", "formula", "vb", "vba") or code.lstrip().startswith("="):
        return "excel"
    if tag in ("text", "txt", "output", "console", "bash", "sh", "shell", "json", "csv"):
        return "text"
    if re.search(r"^\s*(?:SELECT|WITH|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b", code, re.I | re.M) and not re.search(r"^\s*(?:import|def|print)\b|\bpd\.", code, re.M):
        return "sql"
    return "python" if re.search(r"\bimport\b|\bpd\.|\bdf\b|\bprint\s*\(|\bdef \w+\(|=", code) else "text"


def has_code(text: str) -> bool:
    """Did the employee paste code (to be explained or fixed), as opposed to asking for some to be written?"""
    return "```" in text or bool(re.search(r"(?m)^\s*(?:import \w+|from \w+ import|def \w+\(|SELECT\b.+\bFROM\b|(?:DELETE FROM|UPDATE \w+ SET|INSERT INTO)\b|\w+\s*=\s*\w+[.(\[])", text))


# ------------------------------------------------------------------ checks before code is shown
def _real(dotted: str) -> str | None:
    """`pandas.DataFrame.auto_clean` -> the part that does not exist, or None when all of it does."""
    import numpy
    import pandas
    names = dotted.split(".")
    obj = {"pd": pandas, "pandas": pandas, "np": numpy, "numpy": numpy}.get(names[0])
    if obj is None:
        return None
    path = [obj.__name__]
    for name in names[1:]:
        path.append(name)
        if not hasattr(obj, name):
            return ".".join(path)
        obj = getattr(obj, name)
    return None


def unknown_references(text: str) -> list[str]:
    """pandas and numpy names written in a message (`pandas.DataFrame.auto_clean()`) that do not exist in the installed versions."""
    out = []
    for ref in re.findall(r"(?<![\w.])(?:pd|pandas|np|numpy)(?:\.[A-Za-z_]\w*)+", text):
        missing = _real(ref)
        if missing and missing not in out:
            out.append(missing)
    return out


def _chain(node: ast.AST) -> str | None:
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(names)]) if isinstance(node, ast.Name) else None


def python_problems(code: str) -> list[str]:
    """Why this Python would not run: a syntax error, or a pandas/numpy function that does not exist."""
    import pandas
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error on line {exc.lineno}: {exc.msg}" + (f" (`{exc.text.strip()}`)" if exc.text else "")]
    alias = {"pd": "pandas", "pandas": "pandas", "np": "numpy", "numpy": "numpy"}
    frames = {"df"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in ("pandas", "numpy"):
                    alias[a.asname or a.name] = a.name
        # a name given the result of pd.read_...() or pd.DataFrame() holds a table
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            made = _chain(node.value.func) or ""
            if re.match(r"(pd|pandas)\.(read_\w+|DataFrame)$", made) and "sheet_name=None" not in ast.unparse(node.value):
                frames.add(node.targets[0].id)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            dotted = _chain(node)
            if dotted and dotted.split(".")[0] in alias:
                missing = _real(alias[dotted.split(".")[0]] + dotted[dotted.index("."):])
                if missing and f"`{missing}` does not exist" not in " ".join(out):
                    out.append(f"`{missing}` does not exist in {missing.split('.')[0]} {__import__(missing.split('.')[0]).__version__}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in frames \
                and not hasattr(pandas.DataFrame, node.func.attr):
            msg = f"a DataFrame has no method `{node.func.attr}()` in pandas {pandas.__version__}"
            if msg not in out:
                out.append(msg)
    return out


def sql_problems(code: str, language: str) -> list[str]:
    import sqlglot
    out = []
    try:
        sqlglot.parse(code, read=DIALECTS.get(language))
    except sqlglot.errors.SqlglotError as exc:
        out.append("does not parse as SQL: " + str(exc).split("\n")[0][:160])
    if language in FOREIGN and re.search(FOREIGN[language][0], re.sub(r"'[^']*'|--[^\n]*", " ", code), re.I):
        out.append(f"uses {FOREIGN[language][1]}")
    return out


def _outside_quotes(formula: str, old: str, new: str) -> str:
    return "".join(part if i % 2 else part.replace(old, new) for i, part in enumerate(re.split(r'("[^"]*")', formula)))


def excel_problems(code: str, language: str) -> list[str]:
    out = []
    for line in [ln.strip() for ln in code.splitlines() if ln.strip().startswith("=")]:
        bare = re.sub(r'"[^"]*"', "", line)
        if bare.count("(") != bare.count(")") or line.count('"') % 2:
            out.append("brackets or quotation marks do not balance")
        if language == "excel_semicolon" and "," in bare:
            out.append("uses commas between arguments where this Excel needs semicolons")
    return list(dict.fromkeys(out))


def problems(block: dict, language: str) -> list[str]:
    if block["lang"] == "python":
        return python_problems(block["code"])
    if block["lang"] == "sql":
        return sql_problems(block["code"], language)
    if block["lang"] == "excel":
        return excel_problems(block["code"], language)
    return []


def excel_separators(answer: str, language: str) -> str:
    """With the semicolon setting, every formula in the answer gets semicolons between its arguments (text in quotes is left alone)."""
    if language != "excel_semicolon":
        return answer

    def fix(m: re.Match) -> str:
        return "\n".join(_outside_quotes(ln, ",", ";") if ln.lstrip().startswith("=") else ln for ln in m.group(0).split("\n"))
    answer = re.sub(r"```[A-Za-z]*\n.*?```", fix, answer, flags=re.S)
    return re.sub(r"`=[^`\n]+`", lambda m: _outside_quotes(m.group(0), ",", ";"), answer)


# ------------------------------------------------------------------ risks, raised by rule
def risks(code: str) -> list[str]:
    found = [name for name, pattern in _RISKS if re.search(pattern, code, re.I if name in ("sql_injection", "drop_or_truncate") else 0)]
    for statement in re.sub(r"--[^\n]*", " ", code).split(";"):
        if re.search(r"\bWHERE\b", statement, re.I):
            continue
        if re.search(r"\bDELETE\s+FROM\s+[\w.\[\]\"`]+", statement, re.I):
            found.append("delete_without_where")
        if re.search(r"\bUPDATE\s+[\w.\[\]\"`]+\s+SET\b", statement, re.I):
            found.append("update_without_where")
    return list(dict.fromkeys(found))


def warnings(question: str, answer: str, hidden: int, lang: str) -> list[dict]:
    """What the rules found, in the employee's code first and then in code the answer adds."""
    i = 2 if lang == "ar" else 1
    asked = "\n".join(b["code"] for b in blocks(question)) or (question if has_code(question) else "")
    found = [(k, "yours") for k in (["hardcoded_secret"] if hidden else []) + risks(asked)]
    found += [(k, "generated") for k in risks("\n".join(b["code"] for b in blocks(answer) if b["lang"] != "text")) if k not in dict(found)]
    return [{"kind": k, "severity": WARN[k][0], "message": WARN[k][i], "where": where} for k, where in found]


# ------------------------------------------------------------------ what the model is told
def schema(files: list[dict]) -> str:
    """The attached spreadsheets as a programmer needs them: how to load each sheet, its columns, their kinds and values, three rows."""
    out = []
    for f in files:
        name, csv_file = f["name"], f["name"].lower().endswith((".csv", ".tsv"))
        out.append(f'File "{name}":')
        for s in f.get("sheets") or []:
            if csv_file:
                extra = (f', sep="{s["delimiter"]}"' if s.get("delimiter") not in (None, ",") else "").replace("\t", "\\t") + \
                        (f', encoding="{s["encoding"]}"' if s.get("encoding") not in (None, "utf-8-sig") else "") + \
                        (f", header={s['header_kept']}" if s.get("header_kept") else "")
                load, what = f'pd.read_csv("{name}"{extra})', ""
            else:
                load, what = f'pd.read_excel("{name}", sheet_name="{s["name"]}", header={s["header_row"]})', f'Sheet "{s["name"]}": '
            out.append(f"  {what}{s['rows']} rows. Load it with: {load}")
            cols = []
            for c in s.get("columns") or [{"name": h, "kind": "text"} for h in s["header"]]:
                note = {"number": "number", "date": "date written as YYYY-MM-DD text: convert with pd.to_datetime" if csv_file else "date (already a datetime after loading)"}.get(c["kind"], "text")
                if c.get("values"):
                    note += ", one of: " + " | ".join(str(v) for v in c["values"])
                cols.append(f'    "{c["name"]}": {note}')
            out += ["  Columns:", *cols, "  First rows: " + "; ".join(str(r) for r in s.get("sample") or [])]
    return "\n".join(out)


def context(lang: str, opts: dict | None = None, data: str = "", found: list[dict] | None = None, missing: list[str] | None = None) -> str:
    """The code rules, the employee's choices, the attached data and what the automatic checks found, as a block for the system prompt."""
    opts = opts or {}
    lines = [OPTIONS[name][opts.get(name) if opts.get(name) in OPTIONS[name] else "auto"][2] for name in ("language", "depth")]
    lines.append("Write the explanation in Arabic (Modern Standard Arabic); keep technical terms and all code in English." if lang == "ar" else "Write the explanation in English.")
    text = RULES + "\n" + "\n".join(f"- {ln}" for ln in lines if ln)
    if missing:
        text += "\n\nChecked against the installed libraries: " + "; ".join(f"`{m}` does not exist" for m in missing) + ". Say so first, then give the real functions that do the job."
    notes = [WARN[w["kind"]][1] for w in found or [] if w["where"] == "yours"]
    if notes:
        text += "\n\nAutomatic checks on the employee's code found the following. Open your answer with it, in one or two sentences:\n" + "\n".join(f"- {n}" for n in notes)
    if data:
        text += f"\n\n{WITH_DATA}\n{data}"
    return text


REPAIR = ("The code below was written for this request, and a check found a problem with it. Return the corrected, complete code in one "
          "fenced block that names its language, and nothing else.\n\nRequest: {request}\n\nCode:\n```{lang}\n{code}\n```\n\nProblem: {problem}")


def result_block(run: dict, lang: str) -> str:
    """What the code produced, as the lines added under the answer."""
    names = ", ".join(f"`{n}`" for n in run["files"])
    if run["ok"]:
        head = f"**النتيجة** — بعد تشغيل الكود على {names}:" if lang == "ar" else f"**Result** — this code was run on {names}:"
        body = run["output"] or ("(لم يطبع الكود شيئاً)" if lang == "ar" else "(the code printed nothing)")
        return f"\n\n{head}\n```text\n{body}\n```"
    head = f"**تعذّر تشغيل الكود** على {names}:" if lang == "ar" else f"**This code did not run** on {names}:"
    return f"\n\n{head}\n```text\n{run['error']}\n```"
