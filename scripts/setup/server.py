#!/usr/bin/env python3
"""The customer setup page:   make setup   ->   http://<host>:8210

Upload a bank's logo, fill in its names and country, see the colours picked from the logo (and override them), then
save the profile to customers/<folder>/ and launch the demos with it: a running stack is switched to it
(scripts/switch_customer.sh, the same as `make customer`), a stopped one is started with it (`make up`). /launch is the
page that follows the launch and opens the portal once every demo is up. Only the Python standard library and Pillow are needed, like apply_customer.py.

    SETUP_PORT=8210   SETUP_BIND=0.0.0.0   (set SETUP_BIND=127.0.0.1 to keep it on this machine)
"""
import base64
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
spec = importlib.util.spec_from_file_location("apply_customer", ROOT / "scripts" / "apply_customer.py")
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)

FOLDER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
TOKENS = ["brand", "brand-dark", "accent", "accent-light", "accent-deep", "on-accent", "canvas", "ink", "ink-soft",
          "line", "status-review", "status-stop", "status-ok"]
BILINGUAL = ("assistant", "appTitle", "agentName", "heroTitle")
MAX_IMAGE = 15 * 1024 * 1024


class Bad(Exception):
    """A request the page should show as a message (HTTP 400)."""


# ------------------------------------------------------------------ the one background job (apply or start)
class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.kind = self.target = None
        self.log: list[str] = []
        self.rc: int | None = None
        self.started = self.ended = None

    def running(self) -> bool:
        return self.started is not None and self.ended is None

    def start(self, kind: str, target: str, cmd: list[str]) -> None:
        with self.lock:
            if self.running():
                raise Bad(f"{self.kind} is still running")
            self.kind, self.target, self.log, self.rc = kind, target, [f"$ {' '.join(cmd)}"], None
            self.started, self.ended = time.time(), None
        threading.Thread(target=self._run, args=(cmd,), daemon=True).start()

    def _run(self, cmd: list[str]) -> None:
        try:
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    bufsize=1, env={**os.environ, "TERM": "dumb"})
            for line in proc.stdout:
                self.log.append(line.rstrip("\n"))
                del self.log[:-2000]
            self.rc = proc.wait()
        except Exception as e:                       # noqa: BLE001 - shown to the user in the log
            self.log.append(f"failed to run: {e}")
            self.rc = 1
        self.ended = time.time()

    def state(self, since: int = 0) -> dict:
        return {"kind": self.kind, "target": self.target, "running": self.running(), "rc": self.rc,
                "started": self.started, "ended": self.ended, "total": len(self.log), "lines": self.log[since:]}


JOB = Job()


# ------------------------------------------------------------------ reading state
def countries() -> list[dict]:
    out = []
    for path in sorted(ac.COUNTRIES.glob("[a-z][a-z].py")):
        code = path.stem.upper()
        c = ac.country_portal(code)
        p = c["portal"]
        out.append({"code": code, "name": p["country"], "currency": p["currency"], "nationalId": p["nationalId"],
                    "dialect": {"en": p["dialect"]["en"], "ar": p["dialect"]["ar"]}, "tz": c["tz"],
                    "corpus": ac.has_corpus(code)})
    return out


def active_id() -> str | None:
    f = ROOT / "data" / "customer.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("id")
    except (OSError, ValueError):
        return None


def customers() -> list[dict]:
    current = active_id()
    out = []
    for f in sorted(ac.CUSTOMERS.glob("*/customer.json")):
        folder = f.parent.name
        if folder.startswith("_"):
            continue
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out.append({"folder": folder, "id": c.get("id", folder), "short": c.get("short", folder),
                    "name": c.get("name", {}), "country": c.get("country", "").upper(),
                    "logo": (f.parent / c.get("logo", "logo.png")).exists(),
                    "active": c.get("id", folder) == current, "mtime": f.stat().st_mtime})
    return out


def stack() -> dict:
    try:
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True,
                               timeout=10).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return {"running": False, "error": "docker is not reachable"}
    if "nbe-gateway" not in names:
        return {"running": False, "containers": len([n for n in names if n.startswith("nbe-")])}
    project = subprocess.run(["docker", "inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}',
                              "nbe-gateway"], capture_output=True, text=True, timeout=10).stdout.strip()
    env = dict(re.findall(r"^([A-Z_]+)=(.*)$", (ROOT / ".env").read_text(encoding="utf-8"), re.M)) \
        if (ROOT / ".env").exists() else {}
    mine = env.get("COMPOSE_PROJECT_NAME", "nbe").strip('"')
    return {"running": True, "project": project, "mine": project == mine,
            "containers": len([n for n in names if n.startswith("nbe-")]), "port": env.get("NBE_PORT", "8200")}


def ready() -> dict:
    """Everything is up: the portal answers, and no demo container is still starting or unhealthy."""
    try:
        rows = subprocess.run(["docker", "ps", "--filter", "name=nbe-", "--format", "{{.Names}} {{.Status}}"],
                              capture_output=True, text=True, timeout=10).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        rows = []
    waiting = [r.split()[0] for r in rows if "(health: starting)" in r or "(unhealthy)" in r]
    names = {r.split()[0] for r in rows}
    port = env_port()
    try:
        code = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).status
    except Exception:                                # noqa: BLE001
        code = 0
    up = {"nbe-portal", "nbe-gateway"} <= names
    return {"ready": up and code == 200 and not waiting, "portal": code, "port": port, "waiting": waiting,
            "containers": len(names)}


def launch_cmd(folder: str, replace_other: bool) -> tuple[str, list[str]]:
    """How to get the demos showing <folder>, from whatever is running now."""
    st = stack()
    if st.get("error"):
        raise Bad(st["error"])
    switch = 'scripts/switch_customer.sh "$1"'
    if st["running"] and st["mine"]:
        return "switch", ["bash", "-c", switch, "_", folder]
    if st["running"]:
        if not replace_other:
            raise Bad(f"OTHER:{st['project']}")
        mine = re.search(r"^COMPOSE_PROJECT_NAME=(\S+)", (ROOT / ".env").read_text(encoding="utf-8"), re.M)
        return "start", ["bash", "-c", f'scripts/stop_demo.sh "$2" && {switch} && make up', "_", folder,
                         mine.group(1).strip('"') if mine else "nbe"]
    return "start", ["bash", "-c", f"{switch} && make up", "_", folder]


def env_port() -> str:
    env = ROOT / ".env"
    m = re.search(r"^NBE_PORT=(\d+)", env.read_text(encoding="utf-8"), re.M) if env.exists() else None
    return m.group(1) if m else "8200"


# ------------------------------------------------------------------ images and colours
def decode_image(data_url: str) -> Image.Image:
    """A data: URL from the page -> a Pillow image (PNG, JPEG, WebP or GIF; SVG is not supported)."""
    m = re.match(r"^data:image/([a-z0-9.+-]+);base64,(.*)$", data_url or "", re.S)
    if not m:
        raise Bad("the logo must be an image file (PNG, JPEG or WebP)")
    if "svg" in m.group(1):
        raise Bad("SVG logos are not supported: export it as a PNG (transparent background, about 1000 px wide)")
    raw = base64.b64decode(m.group(2))
    if len(raw) > MAX_IMAGE:
        raise Bad("the image is larger than 15 MB")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:                           # noqa: BLE001
        raise Bad(f"could not read the image: {e}") from None
    return img.convert("RGBA")


def clean_colors(colors) -> dict:
    out = {}
    for k, v in (colors or {}).items():
        if k not in TOKENS:
            raise Bad(f"unknown colour '{k}'")
        if not HEX_RE.match(str(v)):
            raise Bad(f"colour {k} must look like #1a2b3c")
        out[k] = v.lower()
    return out


def theme_for(logo: Path, colors: dict) -> dict:
    found = ac.logo_colors(logo)
    theme = ac.pick_colors(logo, colors)
    for k, default in (("canvas", "#f8f8f8"), ("ink-soft", "#4a4a4a"), ("line", "#d6d6d6"), ("status-stop", "#c62828")):
        theme.setdefault(k, default)
    return {"found": [{"hex": ac.hex_of(c), "share": round(s, 3)} for c, s in found],
            "theme": theme, "palette": f"{ac.color_word(theme['brand'])} and {ac.color_word(theme['accent'])} colour palette"}


def preview_colors(body: dict) -> dict:
    colors = clean_colors(body.get("colors"))
    if body.get("logo"):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            decode_image(body["logo"]).save(tmp.name)
            return theme_for(Path(tmp.name), colors)
    folder = body.get("folder", "")
    if FOLDER_RE.match(folder):
        c = read_customer(folder)
        logo = ac.CUSTOMERS / folder / c.get("logo", "logo.png")
        if logo.exists():
            return theme_for(logo, colors)
    raise Bad("upload a logo first")


# ------------------------------------------------------------------ writing a profile
def read_customer(folder: str) -> dict:
    f = ac.CUSTOMERS / folder / "customer.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def save(body: dict) -> dict:
    folder = str(body.get("folder", "")).strip().lower()
    if not FOLDER_RE.match(folder):
        raise Bad("the folder name must be lowercase letters, digits and dashes (e.g. emirates-nbd)")
    c = body.get("customer") or {}
    short = str(c.get("short", "")).strip()
    name = {k: str((c.get("name") or {}).get(k, "")).strip() for k in ("en", "ar")}
    code = str(c.get("country", "")).upper()
    if not short or not name["en"] or not name["ar"]:
        raise Bad("the short name and the full name in English and Arabic are all needed")
    if code not in {x["code"] for x in countries()}:
        raise Bad(f"unknown country {code}")
    font = c.get("font", "cairo")
    if font not in ac.FONTS:
        raise Bad(f"font must be one of {', '.join(ac.FONTS)}")

    path = ac.CUSTOMERS / folder
    existed = (path / "customer.json").exists()
    if body.get("isNew") and existed:
        raise Bad(f"customers/{folder} already exists: pick another folder name, or open it from the list")
    if not existed and not body.get("logo"):
        raise Bad("upload the bank's logo")
    logo_img = decode_image(body["logo"]) if body.get("logo") else None
    mark_img = decode_image(body["mark"]) if body.get("mark") else None

    out = read_customer(folder)                      # keep any field the page does not show (note, ...)
    out.update({"id": str(c.get("id") or out.get("id") or folder.replace("-", "")).strip().lower(),
                "short": short, "country": code, "name": name, "website": str(c.get("website", "")).strip(),
                "logo": "logo.png", "font": font, "colors": clean_colors(c.get("colors"))})
    if not re.match(r"^[a-z0-9-]{1,40}$", out["id"]):
        raise Bad("the id must be lowercase letters, digits and dashes")
    clash = next((x for x in customers() if x["id"] == out["id"] and x["folder"] != folder), None)
    if clash:
        raise Bad(f"customers/{clash['folder']} already uses the id '{out['id']}'")
    for key in BILINGUAL:
        v = c.get(key) or {}
        if str(v.get("en", "")).strip() and str(v.get("ar", "")).strip():
            out[key] = {"en": v["en"].strip(), "ar": v["ar"].strip()}
        else:
            out.pop(key, None)                       # empty: apply_customer.py writes the default from the name
    if c.get("heroChips") is False:
        out["heroChips"] = False
    else:
        out.pop("heroChips", None)
    palette = str(c.get("bannerPalette", "")).strip()
    if palette:
        out["bannerPalette"] = palette
    else:
        out.pop("bannerPalette", None)
    out["facts"] = [{"label": str(f.get("label", "")).strip(), "value": str(f.get("value", "")).strip()}
                    for f in c.get("facts") or [] if str(f.get("value", "")).strip()]
    out.setdefault("note", "Created with the setup page (make setup).")

    path.mkdir(parents=True, exist_ok=True)
    if logo_img:
        logo_img.save(path / "logo.png")
    if mark_img:
        mark_img.save(path / "mark.png")
    elif body.get("removeMark") and (path / "mark.png").exists():
        (path / "mark.png").unlink()
    tmp = path / "customer.json.tmp"
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path / "customer.json")
    return {"folder": folder, "customer": out}


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "bank-demo-setup"

    def log_message(self, fmt, *args):               # keep the terminal quiet: one line per change only
        if self.command != "GET":
            sys.stderr.write(f"{time.strftime('%H:%M:%S')} {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")

    def send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code: int = 200) -> None:
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 3 * MAX_IMAGE:
            raise Bad("request too large")
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise Bad("bad request") from None

    def handle_errors(fn):
        def wrapped(self):
            try:
                fn(self)
            except Bad as e:
                self.json({"error": str(e)}, 400)
            except SystemExit:                       # apply_customer.die()
                self.json({"error": "apply_customer.py stopped: see the terminal running make setup"}, 400)
            except BrokenPipeError:
                pass
            except Exception as e:                   # noqa: BLE001
                self.json({"error": f"{type(e).__name__}: {e}"}, 500)
        return wrapped

    @handle_errors
    def do_GET(self):
        url = urlparse(self.path)
        p = unquote(url.path)
        if p in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if p == "/launch":
            return self.send(200, (HERE / "launch.html").read_bytes(), "text/html; charset=utf-8")
        if p == "/api/ready":
            return self.json(ready())
        if p == "/api/state":
            return self.json({"customers": customers(), "countries": countries(), "active": active_id(),
                              "stack": stack(), "job": JOB.state(10**9), "portalPort": env_port(),
                              "fonts": list(ac.FONTS), "tokens": TOKENS})
        if p == "/api/job":
            since = int((url.query.partition("since=")[2] or "0").split("&")[0] or 0)
            return self.json(JOB.state(since))
        m = re.match(r"^/api/customer/([a-z0-9-]+)$", p)
        if m and FOLDER_RE.match(m.group(1)):
            c = read_customer(m.group(1))
            if not c:
                return self.json({"error": "not found"}, 404)
            return self.json({"folder": m.group(1), "customer": c,
                              "mark": (ac.CUSTOMERS / m.group(1) / "mark.png").exists()})
        m = re.match(r"^/customers/([a-z0-9-]+)/(logo|mark)\.png$", p)
        if m and FOLDER_RE.match(m.group(1)):
            f = ac.CUSTOMERS / m.group(1) / f"{m.group(2)}.png"
            if f.exists():
                return self.send(200, f.read_bytes(), "image/png")
        self.json({"error": "not found"}, 404)

    @handle_errors
    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/colors":
            return self.json(preview_colors(self.body()))
        if p == "/api/save":
            return self.json(save(self.body()))
        if p == "/api/launch":
            body = self.body()
            folder = body.get("folder", "")
            if not FOLDER_RE.match(folder) or not (ac.CUSTOMERS / folder / "customer.json").exists():
                raise Bad("save the profile first")
            if JOB.running():
                raise Bad(f"{JOB.kind} is still running")
            try:
                kind, cmd = launch_cmd(folder, bool(body.get("replaceOther")))
            except Bad as e:
                if str(e).startswith("OTHER:"):
                    return self.json({"error": "another stack is running", "other": str(e)[6:]}, 409)
                raise
            JOB.start(kind, folder, cmd)
            return self.json(JOB.state())
        if p == "/api/stop":
            JOB.start("stop", "", ["make", "down"])
            return self.json(JOB.state())
        self.json({"error": "not found"}, 404)


def main() -> None:
    port = int(os.environ.get("SETUP_PORT", "8210"))
    bind = os.environ.get("SETUP_BIND", "0.0.0.0")
    srv = ThreadingHTTPServer((bind, port), Handler)
    print(f"Customer setup page: http://{'localhost' if bind in ('0.0.0.0', '127.0.0.1') else bind}:{port}"
          f"   (Ctrl-C to stop; it changes nothing until you press Save or Apply)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
