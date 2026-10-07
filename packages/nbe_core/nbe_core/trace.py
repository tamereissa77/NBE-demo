"""Step-by-step trace returned with every demo response and shown in the portal's
"Show the work" drawer: what was retrieved, which model answered, tool calls, guardrails, timings."""
import time
from contextlib import contextmanager
from typing import Any


class Trace:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self._t0 = time.time()

    def add(self, kind: str, label: str, detail: Any = None, ms: int | None = None, **extra: Any) -> dict:
        step = {"kind": kind, "label": label, "detail": detail, "ms": ms, "at_ms": int((time.time() - self._t0) * 1000), **extra}
        self.steps.append(step)
        return step

    @contextmanager
    def step(self, kind: str, label: str, **extra: Any):
        """with trace.step("retrieval", "Search procedures") as s: ...; s["detail"] = hits"""
        t = time.time()
        s = self.add(kind, label, **extra)
        try:
            yield s
        finally:
            s["ms"] = int((time.time() - t) * 1000)

    def llm(self, label: str, res: Any) -> None:
        """Record an nbe_core.llm.LLMResult."""
        self.add("llm", label, res.meta(), res.latency_ms)

    def total_ms(self) -> int:
        return int((time.time() - self._t0) * 1000)

    def to_list(self) -> list[dict]:
        return self.steps
