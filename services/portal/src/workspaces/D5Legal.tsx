import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON, upload, type TraceStep } from "../api";
import { Md } from "../components/Md";
import { BRAND } from "../brand";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Modal, Panel, Spinner } from "./common";

interface Doc { file: string; kind: string; title: string }
interface Clause { type: string; article: number; summary: string; quote: string; quote_verified: boolean }
interface Change { aspect: string; template: string; contract: string }
interface DiffRow { article: number; title: string; status: string; severity: string; changes: Change[]; risk: string; template: string; contract: string | null }
interface Split { party: string; role: string; beneficiary?: string; amount: string; share: string }
interface Flag { article: number; articles?: number[]; compound?: boolean; title: string; severity: string; risk: string; changes: Change[] }
interface Result {
  name: string; kind: string; total_ms: number; trace: TraceStep[];
  summary: { document_type: string; parties: string[]; key_points: string[]; outcome_or_obligations: string; amounts: string[];
             court?: string | null; outcome?: string | null; award_split?: Split[] | null };
  clauses: Clause[]; diff: DiffRow[]; risk_flags: Flag[];
}
interface Golden { file: string; deviations: { clause: string; title: string; severity: string }[] }

const TYPES = {
  en: { governing_law: "Law & jurisdiction", late_payment: "Late payment", prepayment: "Prepayment", rate: "Rate", termination: "Termination",
        liability: "Liability", insurance: "Insurance", data: "Data confidentiality", security: "Security" },
  ar: { governing_law: "القانون والاختصاص", late_payment: "التأخر في السداد", prepayment: "السداد المعجل", rate: "العائد", termination: "الإنهاء",
        liability: "المسؤولية", insurance: "التأمين", data: "سرية البيانات", security: "الضمانات" },
} as Record<"en" | "ar", Record<string, string>>;
const SEVT = { high: "red", medium: "orange", low: "neutral", none: "green" } as const;
const SEV = {
  en: { high: "High", medium: "Medium", low: "Low" },
  ar: { high: "مرتفعة", medium: "متوسطة", low: "منخفضة" },
} as Record<"en" | "ar", Record<string, string>>;
const L = {
  en: { pick: "Pick a document", upload: "Upload a contract or ruling", analyze: "Analyze", rerun: "Re-analyze", card: "Legal summary card", points: "Key points",
        clauses: "Clauses", flags: "Risk flags", diff: "Diff vs approved template", none: "Pick a contract or ruling and analyze it.",
        banner: "Shares D2's RAG pipeline · separate demo experience", working: "Map → reduce summary, clause extraction, template comparison…",
        verified: "quote verified in the document", unverified: "quote not found verbatim", planted: "Planted deviations found",
        same: "same as template", missing: "missing", unchecked: "not checked", parties: "Parties", outcome: "Outcome / obligations",
        validate: `${BRAND.short} legal validates outputs before demo day.`, article: "Article", amounts: "Amounts", ruling: "Ruling", court: "Court",
        award: "Who bears what", party: "Party", role: "Role", beneficiary: "To", amount: "Amount", share: "Share", pays: "Pays", bears: "Bears the loss",
        aspect: "Aspect", template: "Approved template", contract: "Contract",
        uncheckedNote: (n: number) => `${n} article(s) could not be compared automatically. Review them by hand.`,
        uncheckedRisk: "The model's comparison for this article was unusable, so it was not judged. Compare the two texts below by hand." },
  ar: { pick: "اختر وثيقة", upload: "ارفع عقداً أو حكماً", analyze: "تحليل", rerun: "إعادة التحليل", card: "بطاقة الملخص القانوني", points: "أهم النقاط",
        clauses: "البنود", flags: "إشارات المخاطر", diff: "المقارنة بالنموذج المعتمد", none: "اختر عقداً أو حكماً لتحليله.",
        banner: "يشارك منظومة الاسترجاع مع D2 بتجربة مستقلة", working: "تلخيص على مراحل، واستخراج البنود، والمقارنة بالنموذج…",
        verified: "الاقتباس موجود حرفياً في الوثيقة", unverified: "الاقتباس غير موجود حرفياً", planted: "الانحرافات المزروعة المكتشفة",
        same: "مطابقة للنموذج", missing: "محذوفة", unchecked: "لم تُفحص", parties: "الأطراف", outcome: "المنطوق / الالتزامات",
        validate: "يراجع الفريق القانوني بالبنك المخرجات قبل يوم العرض.", article: "المادة", amounts: "المبالغ", ruling: "الحكم", court: "المحكمة",
        award: "من يتحمل ماذا", party: "الطرف", role: "الدور", beneficiary: "لصالح", amount: "المبلغ", share: "النسبة", pays: "يدفع", bears: "يتحمل الخسارة",
        aspect: "الجانب", template: "النموذج المعتمد", contract: "العقد",
        uncheckedNote: (n: number) => `تعذّرت المقارنة الآلية لعدد ${n} من المواد. تُراجع يدوياً.`,
        uncheckedRisk: "لم تكن مقارنة النموذج لهذه المادة صالحة، فلم يُحكم عليها. قارن النصين أدناه يدوياً." },
};

const deviates = (r: DiffRow) => r.status === "deviates" || r.status === "missing";

export default function D5Legal({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const sev = (s: string) => SEV[lang][s] ?? s;
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

  // Diff rows carry the template's article title, and so do the planted deviations
  const planted = golden.find((g) => g.file === res?.name);
  const found = planted?.deviations.filter((d) => res?.diff.some((r) => deviates(r) && r.title.trim() === d.title.trim())) ?? [];
  const unchecked = res?.diff.filter((r) => r.status === "unchecked") ?? [];
  const ruling = res?.kind === "ruling";
  const split = res?.summary.award_split ?? [];

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <section className="space-y-4 lg:col-span-2">
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white p-4">
          <select value={sel} onChange={(e) => setSel(e.target.value)} dir="auto" className="min-w-64 flex-1 rounded-lg border border-line bg-white px-3 py-2 text-sm">
            {docs.map((d) => <option key={d.file} value={d.file}>{d.kind === "ruling" ? "⚖️" : d.kind === "template" ? "📘" : "📄"} {d.title}</option>)}
          </select>
          <Button test="analyze" onClick={() => go(() => postJSON<Result>("/api/d5/analyze", { file: sel }))} disabled={busy}>{l.analyze}</Button>
          {res?.name === sel && <Button variant="ghost" onClick={() => go(() => postJSON<Result>("/api/d5/analyze/refresh", { file: sel }))} disabled={busy}>↻ {l.rerun}</Button>}
          <input ref={fileInput} type="file" className="hidden" accept=".pdf,.docx,.md,.html,.txt"
                 onChange={(e) => {
                   const f = e.target.files?.[0];
                   e.target.value = "";          // so picking the same file again fires onChange
                   if (f) go(() => upload<Result>("/api/d5/upload", f));
                 }} />
          <Button variant="ghost" onClick={() => fileInput.current?.click()} disabled={busy}>⬆ {l.upload}</Button>
        </div>
        <ErrorNote error={error} />
        {busy && <Spinner label={l.working} />}

        {res && ruling && (
          <div data-test="ruling" className="space-y-3 rounded-xl border border-line bg-white p-5">
            <h3 className="font-bold text-brand">{l.ruling}</h3>
            {res.summary.court && <Block label={l.court}><div dir="auto">{res.summary.court}</div></Block>}
            {res.summary.outcome && res.summary.outcome !== res.summary.outcome_or_obligations && (
              <Block label={l.outcome}><div dir="auto">{res.summary.outcome}</div></Block>
            )}
            {res.summary.amounts.length > 0 && (
              <Block label={l.amounts}>
                <div className="flex flex-wrap gap-1.5" dir="auto">{res.summary.amounts.map((a) => <Chip key={a}>{a}</Chip>)}</div>
              </Block>
            )}
            {split.length > 0 && (
              <div data-test="award-split">
                <h4 className="mb-2 text-xs font-semibold uppercase text-ink-soft">{l.award}</h4>
                <table className="w-full text-sm">
                  <thead><tr className="text-xs text-ink-soft">
                    <th className="pb-1 text-start">{l.party}</th><th className="pb-1 text-start">{l.role}</th><th className="pb-1 text-start">{l.beneficiary}</th>
                    <th className="pb-1 text-start">{l.amount}</th><th className="pb-1 text-start">{l.share}</th>
                  </tr></thead>
                  <tbody>
                    {split.map((s, i) => (
                      <tr key={i} className="border-t border-line align-top">
                        <td className="py-2 pe-3 font-semibold"><span dir="auto">{s.party}</span></td>
                        <td className="py-2 pe-3"><Chip tone={s.role === "pays" ? "red" : "orange"}>{s.role === "pays" ? l.pays : l.bears}</Chip></td>
                        <td className="py-2 pe-3"><span dir="auto">{s.beneficiary || "—"}</span></td>
                        <td className="py-2 pe-3 whitespace-nowrap"><span dir="auto">{s.amount}</span></td>
                        <td className="py-2">
                          <div className="flex items-center gap-2">
                            <div className="h-2 w-24 overflow-hidden rounded-full bg-canvas">
                              <div className={`h-full ${s.role === "pays" ? "bg-status-stop" : "bg-accent"}`} style={{ width: `${Math.min(parseFloat(s.share) || 0, 100)}%` }} />
                            </div>
                            <span dir="ltr">{s.share}</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {res && res.clauses.length > 0 && (
          <div className="rounded-xl border border-line bg-white p-5">
            <h3 className="mb-3 font-bold text-brand">{l.clauses}</h3>
            <table className="w-full text-sm">
              <tbody>
                {res.clauses.map((c, i) => (
                  <tr key={i} className="border-t border-line align-top">
                    <td className="py-2 pe-3 font-semibold whitespace-nowrap">{TYPES[lang][c.type] ?? c.type}<div className="text-xs font-normal text-ink-soft">{l.article} {c.article}</div></td>
                    <td className="py-2" dir="auto">
                      {c.summary}
                      <div className="mt-1 rounded bg-canvas p-2 text-xs italic">
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
          <div className="rounded-xl border border-line bg-white p-5">
            <h3 className="mb-3 font-bold text-brand">{l.diff}</h3>
            {unchecked.length > 0 && <p data-test="unchecked-note" className="mb-3 rounded-lg bg-accent/20 p-3 text-sm text-ink">⚠ {l.uncheckedNote(unchecked.length)}</p>}
            <div className="grid gap-2 sm:grid-cols-2">
              {res.diff.map((r) => (
                <button key={r.article} onClick={() => r.status !== "same" && setViewer(r)} className={`text-start ${r.status === "same" ? "cursor-default" : ""}`}>
                  <Block accent={r.status === "same" ? "green" : r.status === "unchecked" ? "neutral" : r.severity === "high" ? "red" : "orange"}>
                    <div className="flex items-center justify-between gap-2">
                      <span dir="auto" className="font-semibold">{r.article}. {r.title}</span>
                      <Chip tone={SEVT[r.severity as keyof typeof SEVT] ?? "neutral"}>
                        {r.status === "same" ? l.same : r.status === "missing" ? l.missing : r.status === "unchecked" ? l.unchecked : sev(r.severity)}
                      </Chip>
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
            {!ruling && res.summary.amounts.length > 0 && (
              <Block label={l.amounts}>
                <ul className="list-disc space-y-1 ps-4" dir="auto">{res.summary.amounts.map((a) => <li key={a}>{a}</li>)}</ul>
              </Block>
            )}
            {res.risk_flags.length > 0 && (
              <div data-test="risk-flags"><Block label={l.flags} accent="red">
                {res.risk_flags.map((f, i) => (
                  // Compound flags span several articles and reuse the first one's number, so the index is the key
                  <div key={i} className="mb-1.5" dir="auto">
                    <Chip tone={SEVT[f.severity as keyof typeof SEVT] ?? "neutral"}>{sev(f.severity)}</Chip> <b>{f.compound || !f.article ? f.title : `${f.article}. ${f.title}`}</b>
                    <div className="text-xs">{f.risk}</div>
                  </div>
                ))}
              </Block></div>
            )}
            {planted && (
              <p className="text-xs">{l.planted}: <b>{found.length}/{planted.deviations.length}</b></p>
            )}
            <p className="text-xs text-ink-soft">{l.validate}</p>
          </>
        )}
      </Panel>

      {viewer && (
        <Modal title={`${viewer.article}. ${viewer.title}`} onClose={() => setViewer(null)}>
          {viewer.changes.length > 0 && (
            <table className="mb-3 w-full text-sm">
              <thead><tr className="text-xs text-ink-soft"><th className="text-start">{l.aspect}</th><th className="text-start">{l.template}</th><th className="text-start">{l.contract}</th></tr></thead>
              <tbody>{viewer.changes.map((c) => <tr key={c.aspect} className="border-t border-line align-top"><td className="py-1 pe-3 font-semibold" dir="auto">{c.aspect}</td><td className="py-1 pe-3" dir="auto">{c.template}</td><td className="py-1 text-status-stop" dir="auto">{c.contract}</td></tr>)}</tbody>
            </table>
          )}
          <p dir="auto" className="mb-3 text-sm font-semibold">{viewer.status === "unchecked" ? l.uncheckedRisk : viewer.risk}</p>
          <div className="grid gap-3 md:grid-cols-2">
            <Block label={l.template}><Md text={viewer.template} /></Block>
            <Block label={l.contract} accent={viewer.status === "unchecked" ? "neutral" : "red"}>{viewer.contract ? <Md text={viewer.contract} /> : <p>—</p>}</Block>
          </div>
        </Modal>
      )}
    </div>
  );
}
