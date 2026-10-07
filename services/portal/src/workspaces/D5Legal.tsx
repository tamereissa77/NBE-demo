import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON, upload, type TraceStep } from "../api";
import { Md } from "../components/Md";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Modal, Panel, Spinner } from "./common";

interface Doc { file: string; kind: string; title: string }
interface Clause { type: string; article: number; summary: string; quote: string; quote_verified: boolean }
interface Change { aspect: string; template: string; contract: string }
interface DiffRow { article: number; title: string; status: string; severity: string; changes: Change[]; risk: string; template: string; contract: string | null }
interface Result {
  name: string; kind: string; total_ms: number; trace: TraceStep[];
  summary: { document_type: string; parties: string[]; key_points: string[]; outcome_or_obligations: string; amounts: string[] };
  clauses: Clause[]; diff: DiffRow[]; risk_flags: { article: number; title: string; severity: string; risk: string; changes: Change[] }[];
}
interface Golden { file: string; deviations: { clause: string; title: string; severity: string }[] }

const TYPE_AR: Record<string, string> = { governing_law: "القانون والاختصاص", late_payment: "التأخر في السداد", prepayment: "السداد المعجل",
  rate: "العائد", termination: "الإنهاء", liability: "المسؤولية", insurance: "التأمين", data: "سرية البيانات", security: "الضمانات" };
const SEVT = { high: "red", medium: "orange", low: "neutral", none: "green" } as const;
const L = {
  en: { pick: "Pick a document", upload: "Upload a contract or ruling", analyze: "Analyze", card: "Legal summary card", points: "Key points",
        clauses: "Clauses", flags: "Risk flags", diff: "Diff vs approved template", none: "Pick a contract or ruling and analyze it.",
        banner: "Shares D2's RAG pipeline · separate demo experience", working: "Map → reduce summary, clause extraction, template comparison…",
        verified: "quote verified in the document", unverified: "quote not found verbatim", planted: "Planted deviations found",
        same: "same as template", missing: "missing", parties: "Parties", outcome: "Outcome / obligations", validate: "NBE legal validates outputs before demo day." },
  ar: { pick: "اختر وثيقة", upload: "ارفع عقداً أو حكماً", analyze: "تحليل", card: "بطاقة الملخص القانوني", points: "أهم النقاط",
        clauses: "البنود", flags: "إشارات المخاطر", diff: "المقارنة بالنموذج المعتمد", none: "اختر عقداً أو حكماً لتحليله.",
        banner: "يشارك منظومة الاسترجاع مع D2 بتجربة مستقلة", working: "تلخيص على مراحل، واستخراج البنود، والمقارنة بالنموذج…",
        verified: "الاقتباس موجود حرفياً في الوثيقة", unverified: "الاقتباس غير موجود حرفياً", planted: "الانحرافات المزروعة المكتشفة",
        same: "مطابقة للنموذج", missing: "محذوفة", parties: "الأطراف", outcome: "المنطوق / الالتزامات", validate: "يراجع الفريق القانوني بالبنك المخرجات قبل يوم العرض." },
};

export default function D5Legal({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [docs, setDocs] = useState<Doc[]>([]);
  const [sel, setSel] = useState("C01.md");
  const [res, setRes] = useState<Result | null>(null);
  const [golden, setGolden] = useState<Golden[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [viewer, setViewer] = useState<DiffRow | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getJSON<Doc[]>("/api/d5/documents").then(setDocs).catch((e) => setError(String(e)));
    getJSON<Golden[]>("/api/d5/golden").then(setGolden).catch(() => {});
  }, []);

  const go = async (fn: () => Promise<Result>) => {
    setBusy(true); setError(""); setRes(null);
    try { const r = await fn(); setRes(r); onTrace(r.trace); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const planted = golden.find((g) => g.file === res?.name);
  const found = planted?.deviations.filter((d) => res?.diff.some((r) => r.status !== "same" && r.title.includes(d.title.split(" ")[0]))) ?? [];

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <section className="space-y-4 lg:col-span-2">
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-nbe-border bg-white p-4">
          <select value={sel} onChange={(e) => setSel(e.target.value)} dir="auto" className="min-w-64 flex-1 rounded-lg border border-nbe-border bg-white px-3 py-2 text-sm">
            {docs.map((d) => <option key={d.file} value={d.file}>{d.kind === "ruling" ? "⚖️" : d.kind === "template" ? "📘" : "📄"} {d.title}</option>)}
          </select>
          <Button test="analyze" onClick={() => go(() => postJSON<Result>("/api/d5/analyze", { file: sel }))} disabled={busy}>{l.analyze}</Button>
          <input ref={fileInput} type="file" className="hidden" accept=".pdf,.docx,.md,.html,.txt"
                 onChange={(e) => e.target.files?.[0] && go(() => upload<Result>("/api/d5/upload", e.target.files![0]))} />
          <Button variant="ghost" onClick={() => fileInput.current?.click()} disabled={busy}>⬆ {l.upload}</Button>
        </div>
        <ErrorNote error={error} />
        {busy && <Spinner label={l.working} />}

        {res && res.clauses.length > 0 && (
          <div className="rounded-xl border border-nbe-border bg-white p-5">
            <h3 className="mb-3 font-bold text-nbe-green">{l.clauses}</h3>
            <table className="w-full text-sm">
              <tbody>
                {res.clauses.map((c, i) => (
                  <tr key={i} className="border-t border-nbe-border align-top">
                    <td className="py-2 pe-3 font-semibold whitespace-nowrap">{TYPE_AR[c.type] ?? c.type}<div className="text-xs font-normal text-nbe-text">المادة {c.article}</div></td>
                    <td className="py-2" dir="auto">
                      {c.summary}
                      <div className="mt-1 rounded bg-nbe-bg p-2 text-xs italic">
                        «{c.quote}» <span title={c.quote_verified ? l.verified : l.unverified}>{c.quote_verified ? "✓" : "⚠"}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {res && res.diff.length > 0 && (
          <div className="rounded-xl border border-nbe-border bg-white p-5">
            <h3 className="mb-3 font-bold text-nbe-green">{l.diff}</h3>
            <div className="grid gap-2 sm:grid-cols-2">
              {res.diff.map((r) => (
                <button key={r.article} onClick={() => r.status !== "same" && setViewer(r)} className="text-start">
                  <Block accent={r.status === "same" ? "green" : r.severity === "high" ? "red" : "orange"}>
                    <div className="flex items-center justify-between gap-2">
                      <span dir="auto" className="font-semibold">{r.article}. {r.title}</span>
                      <Chip tone={SEVT[r.severity as keyof typeof SEVT] ?? "neutral"}>{r.status === "same" ? l.same : r.status === "missing" ? l.missing : r.severity}</Chip>
                    </div>
                    {r.changes.slice(0, 2).map((c) => <div key={c.aspect} dir="auto" className="mt-1 text-xs">• {c.aspect}: <s className="opacity-60">{c.template}</s> ← <b>{c.contract}</b></div>)}
                  </Block>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      <Panel title={l.card} banner={l.banner}>
        {!res && !busy && <p className="text-sm">{l.none}</p>}
        {res && (
          <>
            <div className="flex flex-wrap gap-1.5">
              <Chip tone="green">{res.summary.document_type}</Chip>
              <Chip>{(res.total_ms / 1000).toFixed(1)} s</Chip>
            </div>
            <Block label={l.points}>
              <ul className="list-disc space-y-1 ps-4" dir="auto">{res.summary.key_points.map((p) => <li key={p}>{p}</li>)}</ul>
            </Block>
            <Block label={l.parties}><div dir="auto">{res.summary.parties.join(" · ")}</div></Block>
            <Block label={l.outcome}><Md text={res.summary.outcome_or_obligations} /></Block>
            {res.risk_flags.length > 0 && (
              <div data-test="risk-flags"><Block label={l.flags} accent="red">
                {res.risk_flags.map((f) => (
                  <div key={f.article} className="mb-1.5" dir="auto">
                    <Chip tone={SEVT[f.severity as keyof typeof SEVT] ?? "neutral"}>{f.severity}</Chip> <b>{f.article}. {f.title}</b>
                    <div className="text-xs">{f.risk}</div>
                  </div>
                ))}
              </Block></div>
            )}
            {planted && (
              <p className="text-xs">{l.planted}: <b>{found.length}/{planted.deviations.length}</b></p>
            )}
            <p className="text-xs text-nbe-text">{l.validate}</p>
          </>
        )}
      </Panel>

      {viewer && (
        <Modal title={`${viewer.article}. ${viewer.title}`} onClose={() => setViewer(null)}>
          <table className="mb-3 w-full text-sm" dir="rtl">
            <thead><tr className="text-xs text-nbe-text"><th className="text-start">الجانب</th><th className="text-start">النموذج المعتمد</th><th className="text-start">العقد</th></tr></thead>
            <tbody>{viewer.changes.map((c) => <tr key={c.aspect} className="border-t border-nbe-border"><td className="py-1 font-semibold">{c.aspect}</td><td className="py-1">{c.template}</td><td className="py-1 text-status-stop">{c.contract}</td></tr>)}</tbody>
          </table>
          <p dir="auto" className="mb-3 text-sm font-semibold">{viewer.risk}</p>
          <div className="grid gap-3 md:grid-cols-2">
            <Block label="النموذج المعتمد"><Md text={viewer.template} /></Block>
            <Block label="العقد" accent="red">{viewer.contract ? <Md text={viewer.contract} /> : <p>—</p>}</Block>
          </div>
        </Modal>
      )}
    </div>
  );
}
