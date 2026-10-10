import { useEffect, useState } from "react";
import { getJSON, postJSON, type TraceStep } from "../api";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Modal, Panel, Spinner } from "./common";
import D1Cases from "./D1Cases";

interface Pack { id: string; name_ar: string; name_en: string; loan_amount_egp: number; documents: string[]; decision: Decision | null; verified: boolean }
interface Decision { decision: string; note: string; reviewer: string; decided_at: string }
interface Flag { source: string; rule: string; severity: string; documents: string[]; detail_ar: string; detail_en: string; evidence: Record<string, unknown> }
interface Doc {
  file: string; kind: string; kind_ar: string; fields: Record<string, unknown>; flags: string[]; thumb: string; ela_heatmap: string;
  forensics: { noise: { regions: { bbox: number[] }[]; page_noise: number }; stamps: { duplicate: boolean; boxes: number[][] | null; similarity: number };
               metadata: { software: string | null }; ela_score: number; image_size: number[] };
}
interface Result { applicant: { id: string; name_ar: string; name_en: string; loan_amount_egp: number }; verdict: string; risk: string; flags: Flag[];
                   documents: Doc[]; summary: { ar: string; en: string }; decision: Decision | null; trace: TraceStep[]; total_ms: number }

const SEVT = { high: "red", medium: "orange", low: "neutral" } as const;
const L = {
  en: { packs: "Loan packs", verify: "Verify pack", panel: "Review decision panel", banner: "Flags for review: a human decides, never fraud-proof",
        flagged: "Flagged for review", clean: "No issues found", working: "Extracting fields, running forensics and cross-checks…", flags: "Evidence",
        approve: "Documents OK", more: "Request more documents", reject: "Reject documents", note: "Reviewer note (optional)", decided: "Decision recorded",
        original: "Original with evidence", ela: "ELA heatmap", fields: "Extracted fields", pick: "Pick a loan pack and verify it.", egp: "EGP",
        none: "The synthetic packs have not been generated on this machine yet (make data)." },
  ar: { packs: "ملفات القروض", verify: "تحقق من الملف", panel: "لوحة قرار المراجعة", banner: "إشارات للمراجعة فقط: القرار للإنسان",
        flagged: "محال للمراجعة", clean: "لا توجد مؤشرات", working: "استخراج البيانات وفحص الصور والمطابقة بين المستندات…", flags: "الأدلة",
        approve: "المستندات سليمة", more: "طلب مستندات إضافية", reject: "رفض المستندات", note: "ملاحظة المراجع (اختياري)", decided: "تم تسجيل القرار",
        original: "الأصل مع الأدلة", ela: "خريطة مستوى الخطأ", fields: "البيانات المستخرجة", pick: "اختر ملف قرض للتحقق منه.", egp: "جنيه",
        none: "لم تُولَّد الملفات التجريبية على هذا الجهاز بعد (make data)." },
};
const DECISION: Record<string, { en: string; ar: string; tone: "green" | "orange" | "red" }> = {
  approve_docs: { en: "Documents OK", ar: "المستندات سليمة", tone: "green" }, request_more: { en: "More documents requested", ar: "طُلبت مستندات إضافية", tone: "orange" },
  reject_docs: { en: "Documents rejected", ar: "رُفضت المستندات", tone: "red" },
};

function Evidence({ doc }: { doc: Doc }) {
  const [w, h] = doc.forensics.image_size;
  const boxes = [
    ...doc.forensics.noise.regions.map((r) => ({ b: r.bbox, c: "border-status-stop", t: "noise" })),
    ...(doc.forensics.stamps.duplicate && doc.forensics.stamps.boxes ? doc.forensics.stamps.boxes.map((b) => ({ b, c: "border-nbe-orange", t: "stamp" })) : []),
  ];
  return (
    <div className="relative">
      <img src={`/api/d1/doc/${doc.file}`} alt={doc.file} className="w-full rounded-lg border border-nbe-border" />
      {boxes.map((x, i) => (
        <div key={i} title={x.t} className={`absolute rounded border-4 ${x.c}`}
             style={{ left: `${(100 * x.b[0]) / w}%`, top: `${(100 * x.b[1]) / h}%`, width: `${(100 * (x.b[2] - x.b[0])) / w}%`, height: `${(100 * (x.b[3] - x.b[1])) / h}%` }} />
      ))}
    </div>
  );
}

// The synthetic packs: generated documents with planted forgeries and a ground-truth manifest.
function Packs({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [packs, setPacks] = useState<Pack[]>([]);
  const [sel, setSel] = useState("A01");
  const [res, setRes] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Doc | null>(null);
  const [tab, setTab] = useState<"original" | "ela" | "fields">("original");
  const [note, setNote] = useState("");

  const loadPacks = () => getJSON<Pack[]>("/api/d1/packs").then(setPacks).catch((e) => setError(String(e)));
  useEffect(() => { loadPacks(); }, []);

  const verify = async () => {
    setBusy(true); setError(""); setRes(null);
    try { const r = await postJSON<Result>(`/api/d1/verify/${sel}`); setRes(r); onTrace(r.trace); loadPacks(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const decide = async (decision: string) => {
    const d = await postJSON<Decision>(`/api/d1/decision/${sel}`, { decision, note, reviewer: "loan officer" });
    setRes((r) => (r ? { ...r, decision: d } : r));
    loadPacks();
  };
  const pick = (id: string) => { setSel(id); setRes(null); setNote(""); };

  return (
    <div className="grid gap-5 lg:grid-cols-[220px_1fr_340px]">
      <nav className="flex gap-2 overflow-x-auto lg:flex-col">
        <div className="hidden text-xs font-semibold uppercase text-nbe-text lg:block">{l.packs}</div>
        {packs.map((p) => (
          <button key={p.id} data-test="pack" onClick={() => pick(p.id)}
                  className={`shrink-0 rounded-xl border px-3 py-2 text-start text-sm ${sel === p.id ? "border-nbe-green bg-nbe-green text-white" : "border-nbe-border bg-white hover:bg-nbe-bg"}`}>
            <div className="font-bold">{p.id}</div>
            <div dir="auto" className="text-xs opacity-90">{lang === "ar" ? p.name_ar : p.name_en}</div>
            <div className="text-xs opacity-75">{p.loan_amount_egp.toLocaleString()} {l.egp} · {p.documents.length} docs</div>
            {p.decision && <div className="mt-1"><Chip tone={DECISION[p.decision.decision].tone}>{DECISION[p.decision.decision][lang]}</Chip></div>}
          </button>
        ))}
      </nav>

      <section className="space-y-4">
        <div className="flex items-center gap-3 rounded-xl border border-nbe-border bg-white p-4">
          <span className="font-bold text-nbe-green">{sel}</span>
          <span dir="auto" className="text-sm">{packs.find((p) => p.id === sel)?.[lang === "ar" ? "name_ar" : "name_en"]}</span>
          <span className="ms-auto"><Button test="verify" onClick={verify} disabled={busy || packs.length === 0}>{l.verify}</Button></span>
        </div>
        {packs.length === 0 && !error && <p className="text-sm text-nbe-text">{l.none}</p>}
        <ErrorNote error={error} />
        {busy && <Spinner label={l.working} />}
        {res && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            {res.documents.map((d) => (
              <button key={d.file} onClick={() => { setOpen(d); setTab("original"); }}
                      className={`overflow-hidden rounded-xl border-2 bg-white text-start ${d.flags.length ? "border-status-stop/60" : "border-nbe-border"}`}>
                <img src={`data:image/png;base64,${d.thumb}`} alt={d.kind} className="h-44 w-full object-cover object-top" />
                <div className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="text-sm font-semibold" dir="auto">{lang === "ar" ? d.kind_ar : d.kind.replace("_", " ")}</span>
                  {d.flags.length > 0 ? <Chip tone="red">⚑ {d.flags.length}</Chip> : <Chip tone="green">✓</Chip>}
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <Panel title={l.panel} banner={l.banner} tone="review">
        {!res && !busy && <p className="text-sm">{l.pick}</p>}
        {res && (
          <>
            <div data-test="verdict" className="flex flex-wrap items-center gap-2">
              <Chip tone={res.verdict === "flagged_for_review" ? "orange" : "green"}>{res.verdict === "flagged_for_review" ? l.flagged : l.clean}</Chip>
              <Chip tone={res.risk === "high" ? "red" : res.risk === "medium" ? "orange" : "green"}>risk: {res.risk}</Chip>
              <Chip>{(res.total_ms / 1000).toFixed(0)} s</Chip>
            </div>
            <p dir="auto" className="text-sm leading-relaxed text-nbe-strong">{lang === "ar" ? res.summary.ar : res.summary.en || res.summary.ar}</p>
            {res.flags.length > 0 && (
              <Block label={l.flags} accent="orange">
                {res.flags.map((f, i) => (
                  <div key={i} className="mb-2">
                    <div className="flex flex-wrap items-center gap-1"><Chip tone={SEVT[f.severity as keyof typeof SEVT]}>{f.severity}</Chip><Chip>{f.source === "forensics" ? "🔬" : "🔗"} {f.rule}</Chip></div>
                    <div dir="auto" className="mt-1 text-xs">{lang === "ar" ? f.detail_ar : f.detail_en}</div>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {f.documents.map((file) => (
                        <button key={file} className="text-xs text-nbe-green underline" onClick={() => { const d = res.documents.find((x) => x.file === file); if (d) { setOpen(d); setTab("original"); } }}>{file}</button>
                      ))}
                    </div>
                  </div>
                ))}
              </Block>
            )}
            {res.decision ? (
              <Block label={l.decided} accent="green">
                <Chip tone={DECISION[res.decision.decision].tone}>{DECISION[res.decision.decision][lang]}</Chip>
                {res.decision.note && <p dir="auto" className="mt-1 text-xs">{res.decision.note}</p>}
              </Block>
            ) : (
              <div className="space-y-2">
                <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={l.note} dir="auto" rows={2} className="w-full rounded-lg border border-nbe-border p-2 text-sm" />
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => decide("approve_docs")}>{l.approve}</Button>
                  <Button variant="ghost" onClick={() => decide("request_more")}>{l.more}</Button>
                  <Button variant="danger" onClick={() => decide("reject_docs")}>{l.reject}</Button>
                </div>
              </div>
            )}
          </>
        )}
      </Panel>

      {open && (
        <Modal title={`${open.file} · ${lang === "ar" ? open.kind_ar : open.kind}`} onClose={() => setOpen(null)}>
          <div className="mb-3 flex gap-2">
            {(["original", "ela", "fields"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={`rounded-full px-3 py-1 text-sm ${tab === t ? "bg-nbe-green text-white" : "bg-nbe-bg"}`}>{l[t]}</button>
            ))}
          </div>
          {tab === "original" && <Evidence doc={open} />}
          {tab === "ela" && (
            <div>
              <img src={`data:image/png;base64,${open.ela_heatmap}`} alt="ELA" className="mx-auto rounded-lg" />
              <p className="mt-2 text-xs">Error-level analysis: bright regions recompress differently from the rest of the page. A visual aid only; flags come from the checks listed in the panel.</p>
            </div>
          )}
          {tab === "fields" && (
            <table className="w-full text-sm">
              <tbody>
                {Object.entries(open.fields).map(([k, v]) => (
                  <tr key={k} className="border-t border-nbe-border align-top">
                    <td className="py-1.5 pe-3 font-semibold">{k}</td>
                    <td className="py-1.5" dir="auto">{typeof v === "object" ? <pre className="text-xs">{JSON.stringify(v, null, 1)}</pre> : String(v)}</td>
                  </tr>
                ))}
                <tr className="border-t border-nbe-border"><td className="py-1.5 pe-3 font-semibold">software</td><td>{open.forensics.metadata.software ?? "—"}</td></tr>
              </tbody>
            </table>
          )}
        </Modal>
      )}
    </div>
  );
}

const MODES = {
  en: { files: "Uploaded documents", packs: "Demo packs (synthetic)" },
  ar: { files: "مستندات مرفوعة", packs: "ملفات تجريبية (مولَّدة)" },
};

// Two ways in: an applicant's own documents, uploaded and read on this machine, or the synthetic packs.
export default function D1DocVerify(props: WorkspaceProps) {
  const { lang } = useI18n();
  const [mode, setMode] = useState<"files" | "packs">("files");
  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {(["files", "packs"] as const).map((m) => (
          <button key={m} data-test={`mode-${m}`} onClick={() => { setMode(m); props.onTrace([]); }}
                  className={`rounded-full px-4 py-1.5 text-sm font-semibold ${mode === m ? "bg-nbe-green text-white" : "bg-white text-nbe-green ring-1 ring-nbe-border"}`}>
            {MODES[lang][m]}
          </button>
        ))}
      </div>
      {mode === "files" ? <D1Cases {...props} /> : <Packs {...props} />}
    </div>
  );
}
