"""Runs model-written Python on a copy of the employee's files, to show what the code really produces.

The code runs in a separate process, in a temporary folder that holds only copies of the attached files:
- no secrets: the process gets an empty environment (no keys, no service addresses);
- no network, no other programs: an audit hook installed before the code starts refuses sockets, subprocesses,
  process control and dynamic libraries, and refuses to open files outside its own folder and Python's libraries;
- bounded: CPU seconds, memory, output size and wall-clock time are capped, and the folder is deleted afterwards.

This is containment for a demo, not a hardened sandbox: the process shares the container's kernel and user. A
production deployment should run it in its own container or virtual machine with no network at all.
"""
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WALL_SECONDS = 20
CPU_SECONDS = 15
MEMORY_BYTES = 2 * 1024 ** 3
OUTPUT_CHARS = 6000

RUNNER = r'''
import io, os, sys
import numpy as np, pandas as pd                 # loaded before the lock: their own start-up opens libraries
import openpyxl                                   # noqa: F401 - pandas needs it for .xlsx
pd.set_option("display.width", 160); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 60)
HERE = os.getcwd() + os.sep
LIBS = tuple(p for p in (sys.prefix, sys.base_prefix, "/usr/lib", "/usr/share/zoneinfo") if p)
DENIED = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty", "os.kill", "os.chown",
          "os.chmod", "ctypes.", "urllib.", "http.", "ftplib.", "smtplib.", "webbrowser.", "pty.", "shutil.", "os.putenv", "sys.addaudithook")

def guard(event, args):
    if event.startswith(DENIED):
        raise PermissionError(f"not allowed here: {event.split('.')[0]}")
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.path.abspath(os.fsdecode(args[0]))
        writing = any(c in str(args[1] or "r") for c in "wax+")
        if not (path.startswith(HERE) or (not writing and path.startswith(LIBS))):
            raise PermissionError("only the attached files can be opened here")

code = open("__code__.py", encoding="utf-8").read()
os.remove("__code__.py")
sys.addaudithook(guard)
scope = {"__name__": "__main__", "pd": pd, "np": np}
exec(compile(code, "code", "exec"), scope)
if scope.get("result") is not None and not sys.stdout.tell_printed:
    print(scope["result"])
'''
# sys.stdout has no "printed anything yet" flag: a thin wrapper gives it one, so `result` is shown only when nothing was printed
PRELUDE = r'''
import sys
class _Out:
    def __init__(self, real): self.real, self.tell_printed = real, False
    def write(self, s):
        if s.strip(): self.tell_printed = True
        return self.real.write(s)
    def __getattr__(self, name): return getattr(self.real, name)
sys.stdout = _Out(sys.stdout)
'''


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (20 * 1024 ** 2, 20 * 1024 ** 2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()


def run(code: str, files: dict[str, bytes]) -> dict:
    """{ok, output, error, seconds, files}: what the code printed (or its `result`), or the last line of its error."""
    t = time.time()
    with tempfile.TemporaryDirectory(prefix="d6run-") as tmp:
        for name, data in files.items():
            (Path(tmp) / Path(name).name).write_bytes(data)
        (Path(tmp) / "__code__.py").write_text(code, encoding="utf-8")
        try:
            done = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", PRELUDE + RUNNER], cwd=tmp, capture_output=True, timeout=WALL_SECONDS,
                                  env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": tmp, "LANG": "C.UTF-8", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
                                  preexec_fn=_limits)
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": "", "error": f"stopped after {WALL_SECONDS} seconds", "seconds": round(time.time() - t, 1), "files": list(files)}
    out, err = done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")
    if len(out) > OUTPUT_CHARS:
        out = out[:OUTPUT_CHARS] + "\n... (output cut)"
    # The last lines of a traceback say what went wrong; the frames above them are the runner's own
    lines = [ln for ln in err.strip().splitlines() if ln.strip()]
    error = "" if done.returncode == 0 else "stopped: it used up its time or memory allowance" if done.returncode < 0 else (lines[-1] if lines else f"exit code {done.returncode}")
    return {"ok": done.returncode == 0, "output": out.rstrip(), "error": error, "seconds": round(time.time() - t, 1), "files": list(files)}
