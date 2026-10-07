import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

// Week-1 Arabic gate: blind human scoring (PLAN.md §5). Answers are shuffled per scorer and shown as
// A, B, C; the judge's scores appear only once every answer to a prompt has been scored.

type Scores = { correctness: number; arabic: number; format: number; note?: string };
interface Answer {
  output_id: string;
  label: string;
  text: string | null;
  tool_calls: { function: { name: string; arguments: string } }[];
  auto_pass: boolean | null;
  auto_detail: string | null;
  judge: (Scores & { rationale: string }) | null;
  mine: Scores | null;
}
interface Item {
  id: string;
  dialect: "msa" | "egy" | "mix";
  demo: string;
  task: string;
  title: string;
  messages: { role: string; content: string }[];
  tools: string[];
  good: string;
  answers: Answer[];
}

const CRITERIA: { key: keyof Omit<Scores, "note">; label: string; hint: string }[] = [
  { key: "correctness", label: "Correctness", hint: "Facts, numbers and actions right; nothing invented" },
  { key: "arabic", label: "Arabic quality", hint: "Fluent, natural; understood the dialect; right register" },
  { key: "format", label: "Format", hint: "Followed the requested format and constraints" },
];
const DIALECT: Record<Item["dialect"], string> = { msa: "MSA", egy: "Egyptian", mix: "Mixed / EN" };

// ?scorer=Name in the link wins (personal links for reviewers), then the name saved on this browser
function loadScorer(): string {
  const fromUrl = new URLSearchParams(window.location.search).get("scorer");
  if (fromUrl) return fromUrl;
  try {
    return localStorage.getItem("nbe-eval-scorer") ?? "";
  } catch {
    return "";
  }
}

export function EvalScore() {
  const [scorer, setScorer] = useState(loadScorer);
  const [draftName, setDraftName] = useState(scorer);
  const [set, setSet] = useState<"core" | "all">("core");
  const [items, setItems] = useState<Item[]>([]);
  const [idx, setIdx] = useState(0);
  const [error, setError] = useState("");
  const [local, setLocal] = useState<Record<string, Partial<Scores>>>({});
  const saveTimers = useRef<Record<string, number>>({});

  const fetchItems = useCallback(async () => {
    if (!scorer) return;
    try {
      const r = await fetch(`/api/eval/items?scorer=${encodeURIComponent(scorer)}&set=${set}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setItems(d.items);
      setError("");
    } catch (e) {
      setError(`Could not load items (${(e as Error).message}). Is the evaluation service running?`);
    }
  }, [scorer, set]);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  const startScoring = () => {
    const name = draftName.trim();
    if (!name) return;
    try {
      localStorage.setItem("nbe-eval-scorer", name);
    } catch {
      /* not persisted; fine */
    }
    setScorer(name);
  };

  const merged = (a: Answer): Partial<Scores> => ({ ...(a.mine ?? {}), ...(local[a.output_id] ?? {}) });
  const complete = (s: Partial<Scores>) => !!(s.correctness && s.arabic && s.format);

  const progress = useMemo(() => {
    const all = items.flatMap((i) => i.answers);
    return { done: all.filter((a) => complete(merged(a))).length, total: all.length };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, local]);

  const update = (item: Item, a: Answer, patch: Partial<Scores>) => {
    const next = { ...merged(a), ...patch };
    setLocal((l) => ({ ...l, [a.output_id]: next }));
    if (!complete(next)) return;
    window.clearTimeout(saveTimers.current[a.output_id]);
    saveTimers.current[a.output_id] = window.setTimeout(async () => {
      await fetch("/api/eval/scores", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scorer, output_id: a.output_id, ...next, note: next.note ?? "" }),
      });
      // Once every answer to this prompt is scored, reload to reveal the judge's scores
      const othersDone = item.answers.every((x) => x.output_id === a.output_id || complete(merged(x)));
      if (othersDone) fetchItems();
    }, 400);
  };

  if (!scorer) {
    return (
      <div className="mx-auto max-w-xl px-4 py-12">
        <h1 className="mb-2 text-2xl font-bold text-brand">Arabic gate · blind scoring</h1>
        <p className="mb-6 text-sm">
          Score each model's answer to 30 banking prompts on three 1–5 scales. Answers are anonymised and shuffled; model names
          are revealed only on the results page. Your scores save automatically.
        </p>
        <label className="mb-2 block text-sm font-semibold" htmlFor="scorer">
          Your name or initials
        </label>
        <div className="flex gap-2">
          <input
            id="scorer"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && startScoring()}
            className="flex-1 rounded-lg border border-line bg-white px-3 py-2"
          />
          <button onClick={startScoring} className="rounded-full bg-brand px-5 py-2 font-semibold text-white">
            Start
          </button>
        </div>
      </div>
    );
  }

  const item = items[idx];
  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-brand">Arabic gate · blind scoring</h1>
          <p className="text-sm">
            Scorer <b>{scorer}</b> ·{" "}
            <button className="underline" onClick={() => setScorer("")}>
              change
            </button>{" "}
            · {progress.done}/{progress.total} answers scored
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <select value={set} onChange={(e) => setSet(e.target.value as "core" | "all")} className="rounded-lg border border-line bg-white px-2 py-1.5">
            <option value="core">3 candidate models</option>
            <option value="all">All 5 models (incl. references)</option>
          </select>
          <Link to="/eval/results" className="rounded-full bg-brand px-4 py-1.5 font-semibold text-white">
            Results
          </Link>
        </div>
      </div>
      <div className="mb-4 h-2 overflow-hidden rounded-full bg-line">
        <div className="h-full bg-accent" style={{ width: `${progress.total ? (100 * progress.done) / progress.total : 0}%` }} />
      </div>
      {error && <p className="mb-4 rounded-lg bg-status-stop/10 p-3 text-sm text-status-stop">{error}</p>}

      <div className="grid gap-5 lg:grid-cols-[220px_1fr]">
        <nav className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
          {items.map((it, i) => {
            const done = it.answers.length > 0 && it.answers.every((a) => complete(merged(a)));
            return (
              <button
                key={it.id}
                onClick={() => setIdx(i)}
                className={`flex shrink-0 items-center justify-between gap-2 rounded-lg px-3 py-1.5 text-start text-sm ${
                  i === idx ? "bg-brand text-white" : "bg-white hover:bg-canvas"
                }`}
              >
                <span dir="ltr">{it.id}</span>
                <span className={i === idx ? "" : done ? "text-brand" : "text-line"}>{done ? "✓" : "•"}</span>
              </button>
            );
          })}
        </nav>

        {item ? (
          <section>
            <div className="mb-3 rounded-xl border border-line bg-white p-5">
              <div className="mb-2 flex flex-wrap gap-2 text-xs font-semibold">
                <span className="rounded-md bg-brand px-2 py-0.5 text-white">{item.demo}</span>
                <span className="rounded-md bg-accent px-2 py-0.5 text-ink">{DIALECT[item.dialect]}</span>
                <span className="rounded-md bg-canvas px-2 py-0.5">{item.task}</span>
              </div>
              <h2 className="mb-3 text-lg font-bold text-ink">{item.title}</h2>
              {item.messages.map((m, i) => (
                <div key={i} className="mb-2">
                  <div className="text-xs font-semibold uppercase text-ink-soft">{m.role === "system" ? "System instructions" : "Prompt"}</div>
                  <p dir="auto" className="whitespace-pre-wrap rounded-lg bg-canvas p-3 text-sm text-ink">
                    {m.content}
                  </p>
                </div>
              ))}
              {item.tools.length > 0 && (
                <p className="text-xs">
                  Tools available: <span dir="ltr">{item.tools.join(", ")}</span>
                </p>
              )}
              <div className="mt-3 rounded-lg border-s-4 border-s-accent bg-canvas p-3">
                <div className="text-xs font-semibold uppercase">What a good answer contains</div>
                <p dir="auto" className="text-sm text-ink">
                  {item.good}
                </p>
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-3">
              {item.answers.map((a) => {
                const s = merged(a);
                return (
                  <article key={a.output_id} className="flex flex-col rounded-xl border border-line bg-white p-4">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="flex size-8 items-center justify-center rounded-full bg-brand font-bold text-white">{a.label}</span>
                      {a.auto_pass !== null && (
                        <span
                          title={a.auto_detail ?? ""}
                          className={`rounded-full px-2 py-0.5 text-xs font-semibold ${a.auto_pass ? "bg-brand/10 text-brand" : "bg-status-stop/10 text-status-stop"}`}
                        >
                          auto-check {a.auto_pass ? "pass" : "fail"}
                        </span>
                      )}
                    </div>
                    {a.tool_calls?.length > 0 && (
                      <div dir="ltr" className="mb-2 space-y-1">
                        {a.tool_calls.map((c, i) => (
                          <code key={i} className="block rounded bg-ink px-2 py-1 text-xs text-white">
                            {c.function.name}({c.function.arguments})
                          </code>
                        ))}
                      </div>
                    )}
                    <p dir="auto" className="mb-4 max-h-96 flex-1 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-ink">
                      {a.text || (a.tool_calls?.length ? "" : "(empty)")}
                    </p>
                    {CRITERIA.map((c) => (
                      <div key={c.key} className="mb-2">
                        <div className="mb-1 text-xs font-semibold" title={c.hint}>
                          {c.label}
                        </div>
                        <div className="flex gap-1">
                          {[1, 2, 3, 4, 5].map((n) => (
                            <button
                              key={n}
                              onClick={() => update(item, a, { [c.key]: n })}
                              className={`h-8 flex-1 rounded-md text-sm font-semibold ${
                                s[c.key] === n ? "bg-brand text-white" : "bg-canvas hover:bg-line"
                              }`}
                            >
                              {n}
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                    <input
                      placeholder="Note (optional)"
                      defaultValue={a.mine?.note ?? ""}
                      onBlur={(e) => complete(s) && update(item, a, { note: e.target.value })}
                      className="mt-1 rounded-lg border border-line px-2 py-1 text-sm"
                    />
                    {a.judge && (
                      <p className="mt-2 rounded-lg bg-canvas p-2 text-xs">
                        <b>Judge</b> C{a.judge.correctness} · A{a.judge.arabic} · F{a.judge.format}: {a.judge.rationale}
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
            {item.answers.length === 0 && <p className="text-sm">No answers generated for this prompt yet.</p>}

            <div className="mt-4 flex justify-between">
              <button disabled={idx === 0} onClick={() => setIdx(idx - 1)} className="rounded-full bg-white px-5 py-2 font-semibold text-brand disabled:opacity-40">
                ← Previous
              </button>
              <button
                disabled={idx === items.length - 1}
                onClick={() => setIdx(idx + 1)}
                className="rounded-full bg-brand px-5 py-2 font-semibold text-white disabled:opacity-40"
              >
                Next →
              </button>
            </div>
          </section>
        ) : (
          !error && <p>Loading…</p>
        )}
      </div>
    </div>
  );
}
