import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

// Week-1 Arabic gate results: model names revealed. Human scores lead; the LLM judge is a
// pre-score shown alongside, and the recommendation says which one it used.

interface Row {
  alias: string;
  name?: string;
  model: string;
  answers: number;
  tok_s: number | null;
  latency_ms: number | null;
  auto_pass: number;
  auto_total: number;
  j_correct: number | null;
  j_arabic: number | null;
  j_format: number | null;
  h_correct: number | null;
  h_arabic: number | null;
  h_format: number | null;
  human_scored: number;
  human_mean?: number | null;
  judge_mean?: number | null;
}
interface Results {
  models: Row[];
  by_dialect: Record<"msa" | "egy" | "mix", Row[]>;
  legal: Row[];
  scorers: string[];
  recommendation: { source: string; workhorse: string | null; workhorse_model: string | null; keep_quality: boolean | null; notes: string[] } | null;
}

const fmt = (v: number | string | null | undefined) => (v === null || v === undefined ? "–" : Number(v).toFixed(2));
const mean3 = (r: Row, p: "h" | "j") => {
  const v = [r[`${p}_correct`], r[`${p}_arabic`], r[`${p}_format`]];
  return v.every((x) => x !== null) ? v.reduce((a, b) => a + Number(b), 0) / 3 : null;
};

export function EvalResults() {
  const [data, setData] = useState<Results | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/eval/results")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="mx-auto max-w-7xl px-4 py-8 text-status-stop">Could not load results: {error}</p>;
  if (!data) return <p className="mx-auto max-w-7xl px-4 py-8">Loading…</p>;

  const names = Object.fromEntries(data.models.map((m) => [m.alias, m.name ?? m.alias]));
  const rec = data.recommendation;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-brand">Arabic gate · results</h1>
        <div className="flex gap-2 text-sm">
          <Link to="/eval" className="rounded-full bg-white px-4 py-1.5 font-semibold text-brand">
            Back to scoring
          </Link>
          <a href="/api/eval/export.csv" className="rounded-full bg-brand px-4 py-1.5 font-semibold text-white">
            Download CSV
          </a>
        </div>
      </div>

      {rec && (
        <section className="mb-6 rounded-xl border-s-4 border-s-accent bg-white p-5">
          <h2 className="mb-2 font-bold text-brand">Recommendation{rec.source !== "none" && ` (${rec.source} scores)`}</h2>
          {rec.workhorse_model && (
            <p className="mb-2 text-ink">
              Workhorse: <b>{rec.workhorse_model}</b> · Quality model (Gemma 4 31B): <b>{rec.keep_quality ? "keep" : "drop"}</b> · Hero: gpt-oss-120b
            </p>
          )}
          <ul className="list-disc ps-5 text-sm">
            {rec.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="mb-6 overflow-x-auto rounded-xl border border-line bg-white">
        <table className="w-full text-sm">
          <thead className="bg-brand text-white">
            <tr>
              {["Model", "tok/s", "Latency", "Auto-checks", "Judge C / A / F", "Judge mean", "Human C / A / F", "Human mean", "Human coverage"].map((h) => (
                <th key={h} className="px-3 py-2 text-start font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.models.map((r) => (
              <tr key={r.alias} className="border-t border-line">
                <td className="px-3 py-2 font-semibold text-ink">{r.name}</td>
                <td className="px-3 py-2">{r.tok_s ?? "–"}</td>
                <td className="px-3 py-2">{r.latency_ms ? `${(Number(r.latency_ms) / 1000).toFixed(1)} s` : "–"}</td>
                <td className="px-3 py-2">
                  {r.auto_pass}/{r.auto_total}
                </td>
                <td className="px-3 py-2">
                  {fmt(r.j_correct)} / {fmt(r.j_arabic)} / {fmt(r.j_format)}
                </td>
                <td className="px-3 py-2 font-semibold">{fmt(r.judge_mean)}</td>
                <td className="px-3 py-2">
                  {fmt(r.h_correct)} / {fmt(r.h_arabic)} / {fmt(r.h_format)}
                </td>
                <td className="px-3 py-2 font-semibold">{fmt(r.human_mean)}</td>
                <td className="px-3 py-2">
                  {r.human_scored}/{r.answers}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="mb-6 grid gap-4 md:grid-cols-3">
        {(["msa", "egy", "mix"] as const).map((d) => (
          <div key={d} className="rounded-xl border border-line bg-white p-4">
            <h3 className="mb-2 font-bold text-brand">{{ msa: "Modern Standard Arabic (15)", egy: "Egyptian dialect (10)", mix: "Mixed / English (5)" }[d]}</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-ink-soft">
                  <th className="text-start">Model</th>
                  <th className="text-end">Judge</th>
                  <th className="text-end">Human</th>
                </tr>
              </thead>
              <tbody>
                {data.by_dialect[d].map((r) => (
                  <tr key={r.alias} className="border-t border-line">
                    <td className="py-1">{names[r.alias] ?? r.alias}</td>
                    <td className="py-1 text-end">{fmt(mean3(r, "j"))}</td>
                    <td className="py-1 text-end">{fmt(mean3(r, "h"))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </section>

      <p className="text-xs">
        C = correctness, A = Arabic quality, F = format (1–5). Judge: gpt-oss-120b pre-score; it also judges its own answers, so treat its row with care.
        Scorers so far: {data.scorers.length ? data.scorers.join(", ") : "none"}. Speeds are single-user on one GB10.
      </p>
    </div>
  );
}
