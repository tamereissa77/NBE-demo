import { useEffect, useRef, useState } from "react";
import { ApiError, del, getJSON, postJSON, putJSON, upload } from "../api";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Modal, Panel, Spinner } from "./common";

// Loan files built from uploaded documents: read on this machine by the fine-tuned model, checked by rules.

interface Field { key: string; label_ar: string; label_en: string; value: string | boolean | null; read: string | boolean | null;
                  confidence: number | null; doubt: boolean; corrected: boolean; second_read: boolean; base: boolean }
interface Source { kind: string; pages: number; producer: string | null; creator: string | null; created: string | null; modified: string | null;
                   revisions: number }
interface Doc { id: string; doc_type: string; label_ar: string; label_en: string; thumb: string; read: boolean; error: string | null; ms: number | null;
                software: string | null; has_ela: boolean; fields: Field[]; needs_type: boolean; size: number[] | null; source: Source | null;
                boxes: { bbox: number[]; kind: string }[]; noise_checkable: boolean | null }
interface Flag { source: string; rule: string; severity: "high" | "medium" | "low"; status: "raised" | "needs_confirmation"; documents: string[];
                 confirm: { document: string; field: string }[]; detail_ar: string; detail_en: string }
interface Result { verdict: string; risk: string; flags: Flag[]; summary: { ar: string; en: string }; trace: WorkspaceTrace; total_ms: number }
type WorkspaceTrace = Parameters<WorkspaceProps["onTrace"]>[0];
interface Decision { decision: string; note: string; reviewer: string; decided_at: string }
interface FormData_ { applicant_name: string; national_id: string; monthly_salary: number | null; employer: string; address: string;
                      loan_amount: number | null; applicant_type: string }
interface Case { id: string; form: FormData_; documents: Doc[]; result: Result | null; stale: boolean; decision: Decision | null }
interface CaseRow { id: string; applicant_name: string | null; loan_amount: string | null; verdict: string | null; decision: string | null; documents: number }
interface Reader { configured: boolean; ready: boolean; doc_types: { id: string; ar: string; en: string }[] }

const EMPTY: FormData_ = { applicant_name: "", national_id: "", monthly_salary: null, employer: "", address: "", loan_amount: null, applicant_type: "employee" };
const SEVT = { high: "red", medium: "orange", low: "neutral" } as const;
const L = {
  en: { files: "Loan files", newFile: "New file", none: "No files yet. Open one to upload an applicant's documents.", declared: "What the applicant declared",
        name: "Applicant name", nid: "National ID number", salary: "Monthly salary (EGP)", employer: "Employer", address: "Address", amount: "Loan amount (EGP)", egp: "EGP", noAmount: "no amount", docCount: "documents",
        kind: "Applicant", employee: "Employee", business: "Business owner", save: "Save", open: "Open the file", docs: "Documents", add: "Add document",
        choose: "Choose image", verify: "Read and check", reverify: "Read new documents and check again", working: "Reading the documents on this machine and running the checks…",
        notRead: "not read yet", unreadable: "could not be read", panel: "Review decision panel", banner: "Flags for review: a human decides, never fraud-proof",
        pick: "Open a loan file, upload the applicant's documents and check them.", evidence: "Evidence", confirm: "confirm the reading first", stale: "Documents changed since the last check.",
        approve: "Documents OK", more: "Request more documents", reject: "Reject documents", note: "Reviewer note (optional)", decided: "Decision recorded",
        remove: "Remove", deleteFile: "Delete this file and its documents", sure: "Delete this loan file and its documents from this machine?",
        document: "Document", fields: "Extracted fields", ela: "ELA picture", unsure: "unsure", corrected: "set by officer", ok: "Confirm", reset: "Use the reading",
        yes: "Yes", no: "No", local: "Read on this machine by the fine-tuned model. Nothing is sent outside.",
        reread: "from a second reading", needType: "choose the type",
        chooseType: "Choose the type…", badImage: "This file cannot be read. Upload a JPEG, PNG or WebP photo of the document, or a PDF.",
        baseModel: "general reading", baseNote: "\"General reading\": a field the trained model does not return, read by the plain model. Check it against the page.",
        pdf: "PDF", pages: "pages, the first one is read", madeBy: "written by", saves: "saves",
        tooLarge: "The image is too large (12 MB at most).", needTypeFirst: "Choose the type of the documents first: open a document and pick its type.", type: "Document type", pickFirst: "Choose the document type, then add its image.",
        boxes: "Red: writing on a patch without the camera noise around it. Orange: a region that is an exact copy of another. Green: a region that missed the picture's first save.",
        uncheckable: "This image has too little camera noise for the patch and copy checks (a file made on a computer, or heavily compressed).",
        loading: "The document reader is still loading its model. Uploading works; checking will work in a minute.",
        absent: "The document reader is not part of this installation, so uploaded documents cannot be read here.",
        elaNote: "Error-level picture: bright regions recompress differently from the rest of the page. A visual aid only, not a finding.",
        verdicts: { flagged_for_review: "Flagged for review", no_issues_found: "No issues found", confirm_readings: "Confirm readings first", incomplete: "Incomplete file" } },
  ar: { files: "ملفات القروض", newFile: "ملف جديد", none: "لا توجد ملفات. افتح ملفاً لرفع مستندات العميل.", declared: "بيانات الطلب كما ذكرها العميل",
        name: "اسم العميل", nid: "الرقم القومي", salary: "الراتب الشهري (جنيه)", employer: "جهة العمل", address: "العنوان", amount: "مبلغ القرض (جنيه)", egp: "جنيه", noAmount: "بدون مبلغ", docCount: "مستندات",
        kind: "صفة العميل", employee: "موظف", business: "صاحب نشاط", save: "حفظ", open: "فتح الملف", docs: "المستندات", add: "إضافة مستند",
        choose: "اختر صورة", verify: "اقرأ وافحص", reverify: "اقرأ المستندات الجديدة وافحص من جديد", working: "قراءة المستندات على هذا الجهاز وإجراء الفحوص…",
        notRead: "لم يُقرأ بعد", unreadable: "تعذرت قراءته", panel: "لوحة قرار المراجعة", banner: "إشارات للمراجعة فقط: القرار للإنسان",
        pick: "افتح ملف قرض وارفع مستندات العميل ثم افحصها.", evidence: "الأدلة", confirm: "أكّد القراءة أولاً", stale: "تغيّرت المستندات منذ آخر فحص.",
        approve: "المستندات سليمة", more: "طلب مستندات إضافية", reject: "رفض المستندات", note: "ملاحظة المراجع (اختياري)", decided: "تم تسجيل القرار",
        remove: "حذف", deleteFile: "حذف هذا الملف ومستنداته", sure: "حذف ملف القرض ومستنداته من هذا الجهاز؟",
        document: "المستند", fields: "البيانات المستخرجة", ela: "صورة مستوى الخطأ", unsure: "غير مؤكد", corrected: "أدخله الموظف", ok: "تأكيد", reset: "العودة للقراءة",
        yes: "نعم", no: "لا", local: "تُقرأ على هذا الجهاز بالنموذج المدرَّب. لا يُرسل شيء للخارج.",
        reread: "من قراءة ثانية", needType: "اختر النوع",
        chooseType: "اختر النوع…", badImage: "تعذرت قراءة الملف. ارفع صورة للمستند بصيغة JPEG أو PNG أو WebP، أو ملف PDF.",
        baseModel: "قراءة عامة", baseNote: "«قراءة عامة»: حقل لا يُرجعه النموذج المدرَّب، قرأه النموذج العام. راجعه على الصفحة.",
        pdf: "PDF", pages: "صفحات، تُقرأ الأولى", madeBy: "أنشأه", saves: "مرات الحفظ",
        tooLarge: "الصورة أكبر من المسموح (12 ميجابايت كحد أقصى).", needTypeFirst: "حدّد نوع المستندات أولاً: افتح المستند واختر نوعه.", type: "نوع المستند", pickFirst: "اختر نوع المستند ثم أضف صورته.",
        boxes: "الأحمر: كتابة على مساحة بلا ضوضاء التصوير المحيطة بها. البرتقالي: منطقة مطابقة تماماً لمنطقة أخرى. الأخضر: منطقة لا تحمل أثر الحفظ الأول للصورة.",
        uncheckable: "ضوضاء التصوير في هذه الصورة أقل من أن تسمح بفحص اللصق والنسخ (ملف منشأ على الحاسب أو مضغوط بشدة).",
        loading: "قارئ المستندات ما زال يحمّل النموذج. يمكن الرفع الآن والفحص بعد دقيقة.",
        absent: "قارئ المستندات غير مثبت في هذا النظام، فلا يمكن قراءة المستندات المرفوعة هنا.",
        elaNote: "صورة مستوى الخطأ: المناطق المضيئة تنضغط بشكل مختلف عن بقية الصفحة. وسيلة بصرية فقط وليست نتيجة.",
        verdicts: { flagged_for_review: "محال للمراجعة", no_issues_found: "لا توجد مؤشرات", confirm_readings: "أكّد القراءات أولاً", incomplete: "ملف غير مكتمل" } },
};
const DECISION: Record<string, { en: string; ar: string; tone: "green" | "orange" | "red" }> = {
  approve_docs: { en: "Documents OK", ar: "المستندات سليمة", tone: "green" }, request_more: { en: "More documents requested", ar: "طُلبت مستندات إضافية", tone: "orange" },
  reject_docs: { en: "Documents rejected", ar: "رُفضت المستندات", tone: "red" },
};
const VTONE: Record<string, "green" | "orange" | "neutral"> = { flagged_for_review: "orange", no_issues_found: "green", confirm_readings: "orange", incomplete: "neutral" };
const INPUT = "w-full rounded-lg border border-nbe-border px-3 py-1.5 text-sm";

function FieldRow({ f, lang, onSave }: { f: Field; lang: "en" | "ar"; onSave: (key: string, value: string | boolean | null, reset?: boolean) => void }) {
  const l = L[lang];
  const bool = typeof f.read === "boolean" || typeof f.value === "boolean";
  const [text, setText] = useState(f.value == null ? "" : String(f.value));
  useEffect(() => setText(f.value == null ? "" : String(f.value)), [f.value]);
  const changed = text !== (f.value == null ? "" : String(f.value));
  return (
    <tr className={`border-t border-nbe-border align-top ${f.doubt ? "bg-nbe-orange/10" : ""}`}>
      <td className="py-1.5 pe-3 text-sm font-semibold">{lang === "ar" ? f.label_ar : f.label_en}</td>
      <td className="py-1.5">
        {bool ? (
          <select className={INPUT} value={String(f.value)} onChange={(e) => onSave(f.key, e.target.value === "true")}>
            <option value="true">{l.yes}</option><option value="false">{l.no}</option>
          </select>
        ) : (
          <input dir="auto" className={INPUT} value={text} onChange={(e) => setText(e.target.value)} />
        )}
      </td>
      <td className="whitespace-nowrap py-1.5 ps-2">
        <div className="flex flex-wrap items-center gap-1">
          {f.confidence != null && <Chip tone={f.doubt ? "orange" : "neutral"}>{Math.round(f.confidence * 100)}%</Chip>}
          {f.doubt && <Chip tone="orange">{l.unsure}</Chip>}
          {f.base && !f.corrected && <Chip>{l.baseModel}</Chip>}
          {f.second_read && !f.corrected && <Chip>{l.reread}</Chip>}
          {f.corrected && <Chip tone="green">{l.corrected}</Chip>}
          {!bool && (f.doubt || changed) && <button className="text-xs font-semibold text-nbe-green underline" onClick={() => onSave(f.key, text)}>{changed ? l.save : l.ok}</button>}
          {f.corrected && <button className="text-xs text-nbe-text underline" onClick={() => onSave(f.key, null, true)}>{l.reset}</button>}
        </div>
      </td>
    </tr>
  );
}

export default function D1Cases({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [reader, setReader] = useState<Reader | null>(null);
  const [rows, setRows] = useState<CaseRow[]>([]);
  const [cur, setCur] = useState<Case | null>(null);
  const [form, setForm] = useState<FormData_>(EMPTY);
  const [docType, setDocType] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [tab, setTab] = useState<"document" | "fields" | "ela">("document");
  const [note, setNote] = useState("");
  const picker = useRef<HTMLInputElement>(null);

  // The service answers in English; the common refusals are said in the screen's language
  const fail = (e: unknown) => {
    const status = e instanceof ApiError ? e.status : -1;
    const message = (e as Error).message;
    setError(status === 413 ? l.tooLarge : status === 409 ? l.needTypeFirst : status === 503 ? (reader?.configured === false ? l.absent : l.loading)
      : status === 400 && /image/i.test(message) ? l.badImage : message);
  };
  const loadRows = () => getJSON<CaseRow[]>("/api/d1/cases").then(setRows).catch(fail);
  const show = (c: Case) => { setCur(c); setForm(c.form); if (c.result) onTrace(c.result.trace); loadRows(); };
  useEffect(() => { loadRows(); getJSON<Reader>("/api/d1/cases/reader").then(setReader).catch(fail); }, []);

  const run = async (work: () => Promise<Case>) => {
    setError("");
    try { show(await work()); } catch (e) { fail(e); }
  };
  const base = cur ? `/api/d1/cases/${cur.id}` : "";
  const pick = (id: string) => { setNote(""); run(() => getJSON<Case>(`/api/d1/cases/${id}`)); };
  const saveForm = () => run(() => (cur ? putJSON<Case>(`${base}/form`, form) : postJSON<Case>("/api/d1/cases", form)));
  // A new file opens at once, so the upload area is there before anything is typed; what the applicant
  // declared can be filled in and saved afterwards. What is already typed with no file open goes into it.
  const newFile = () => { setNote(""); onTrace([]); run(() => postJSON<Case>("/api/d1/cases", cur ? EMPTY : form)); };
  // The officer picks the type of every document. After each upload the list is cleared again, so a type
  // picked for one document cannot stick to the next.
  const addFile = (file: File | undefined) => {
    if (file && cur && docType) run(async () => { const c = await upload<Case>(`${base}/documents`, file, { doc_type: docType }); setDocType(""); return c; });
  };
  const verify = async () => { setBusy(true); await run(() => postJSON<Case>(`${base}/verify`)); setBusy(false); };
  const decide = (decision: string) => run(() => postJSON<Case>(`${base}/decision`, { decision, note, reviewer: "loan officer" }));
  const setType = (doc: string, doc_type: string) => run(() => postJSON<Case>(`${base}/documents/${doc}/type`, { doc_type }));
  const saveField = (doc: string) => (key: string, value: string | boolean | null, reset = false) =>
    run(() => postJSON<Case>(`${base}/documents/${doc}/fields`, { key, value, reset }));
  const removeFile = async () => {
    if (!cur || !window.confirm(l.sure)) return;
    try { await del(`${base}`); setCur(null); setForm(EMPTY); onTrace([]); loadRows(); } catch (e) { fail(e); }
  };
  const set = <K extends keyof FormData_>(k: K, v: FormData_[K]) => setForm((f) => ({ ...f, [k]: v }));
  const num = (v: string) => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));

  const res = cur?.result ?? null;
  const doc = cur?.documents.find((d) => d.id === open) ?? null;
  const flagsOf = (id: string) => res?.flags.filter((f) => f.documents.includes(id)).length ?? 0;
  const label = (d: Doc) => (lang === "ar" ? d.label_ar : d.label_en);
  const unread = cur?.documents.some((d) => !d.read) ?? false;

  return (
    <div className="grid gap-5 lg:grid-cols-[220px_1fr_340px]">
      <nav className="flex gap-2 overflow-x-auto lg:flex-col">
        <div className="hidden text-xs font-semibold uppercase text-nbe-text lg:block">{l.files}</div>
        <Button test="new-file" variant="ghost" onClick={newFile}>+ {l.newFile}</Button>
        {rows.map((r) => (
          <button key={r.id} data-test="case" onClick={() => pick(r.id)}
                  className={`shrink-0 rounded-xl border px-3 py-2 text-start text-sm ${cur?.id === r.id ? "border-nbe-green bg-nbe-green text-white" : "border-nbe-border bg-white hover:bg-nbe-bg"}`}>
            <div className="font-bold">{r.id}</div>
            <div dir="auto" className="text-xs opacity-90">{r.applicant_name || "—"}</div>
            <div className="text-xs opacity-90">{r.loan_amount && !Number.isNaN(Number(r.loan_amount)) ? `${Number(r.loan_amount).toLocaleString("en-US")} ${l.egp}` : l.noAmount}</div>
            <div className="text-xs opacity-75">{r.documents} {l.docCount}</div>
            {r.decision && <div className="mt-1"><Chip tone={DECISION[r.decision].tone}>{DECISION[r.decision][lang]}</Chip></div>}
          </button>
        ))}
        {rows.length === 0 && <p className="hidden text-xs text-nbe-text lg:block">{l.none}</p>}
      </nav>

      <section className="space-y-4">
        {reader && !reader.ready && <p className="rounded-lg bg-nbe-orange/20 p-3 text-sm text-nbe-strong">{reader.configured ? l.loading : l.absent}</p>}
        <ErrorNote error={error} />
        <div className="rounded-xl border border-nbe-border bg-white p-4">
          <div className="mb-3 flex items-center gap-3">
            {cur && <span className="font-bold text-nbe-green">{cur.id}</span>}
            <span className="text-sm font-semibold">{l.declared}</span>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-xs text-nbe-text">{l.name}<input dir="auto" data-test="f-name" className={INPUT} value={form.applicant_name} onChange={(e) => set("applicant_name", e.target.value)} /></label>
            <label className="text-xs text-nbe-text">{l.nid}<input dir="ltr" inputMode="numeric" className={INPUT} value={form.national_id} onChange={(e) => set("national_id", e.target.value)} /></label>
            <label className="text-xs text-nbe-text">{l.employer}<input dir="auto" className={INPUT} value={form.employer} onChange={(e) => set("employer", e.target.value)} /></label>
            <label className="text-xs text-nbe-text">{l.salary}<input dir="ltr" inputMode="decimal" className={INPUT} value={form.monthly_salary ?? ""} onChange={(e) => set("monthly_salary", num(e.target.value))} /></label>
            <label className="text-xs text-nbe-text md:col-span-2">{l.address}<input dir="auto" className={INPUT} value={form.address} onChange={(e) => set("address", e.target.value)} /></label>
            <label className="text-xs text-nbe-text">{l.amount}<input dir="ltr" inputMode="decimal" className={INPUT} value={form.loan_amount ?? ""} onChange={(e) => set("loan_amount", num(e.target.value))} /></label>
            <label className="text-xs text-nbe-text">{l.kind}
              <select className={INPUT} value={form.applicant_type} onChange={(e) => set("applicant_type", e.target.value)}>
                <option value="employee">{l.employee}</option><option value="business">{l.business}</option>
              </select>
            </label>
          </div>
          <div className="mt-3"><Button test="save-form" onClick={saveForm}>{cur ? l.save : l.open}</Button></div>
        </div>

        {cur && (
          <div className="rounded-xl border border-nbe-border bg-white p-4">
            <div className="mb-1 text-sm font-semibold">{l.docs}</div>
            <p className="mb-3 text-xs text-nbe-text">{l.local}</p>
            <div className="flex flex-wrap items-center gap-2">
              <select data-test="doc-type" className={`rounded-lg border px-3 py-2 text-sm ${docType ? "border-nbe-border" : "border-nbe-orange bg-nbe-orange/10"}`}
                      value={docType} onChange={(e) => setDocType(e.target.value)}>
                <option value="" disabled>{l.chooseType}</option>
                {(reader?.doc_types ?? []).map((t) => <option key={t.id} value={t.id}>{lang === "ar" ? t.ar : t.en}</option>)}
              </select>
              <input ref={picker} data-test="file" type="file" accept="image/jpeg,image/png,image/webp,application/pdf,.pdf" className="hidden"
                     onChange={(e) => { addFile(e.target.files?.[0]); e.target.value = ""; }} />
              <Button variant="ghost" disabled={!docType} onClick={() => picker.current?.click()}>{l.add}: {l.choose}</Button>
              <span className="ms-auto"><Button test="verify" onClick={verify} disabled={busy || cur.documents.length === 0}>{res && (cur.stale || unread) ? l.reverify : l.verify}</Button></span>
            </div>
            {!docType && <p className="mt-2 text-xs text-nbe-text">{l.pickFirst}</p>}
            {busy && <div className="mt-3"><Spinner label={l.working} /></div>}
            {cur.stale && !busy && <p className="mt-3 text-xs text-nbe-strong">{l.stale}</p>}
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
              {cur.documents.map((d) => (
                <button key={d.id} data-test="doc" onClick={() => { setOpen(d.id); setTab(d.read && !d.error && !d.needs_type ? "fields" : "document"); }}
                        className={`overflow-hidden rounded-xl border-2 bg-white text-start ${flagsOf(d.id) ? "border-status-stop/60" : "border-nbe-border"}`}>
                  <img src={`data:image/jpeg;base64,${d.thumb}`} alt={d.doc_type} className="h-40 w-full object-cover object-top" />
                  <div className="flex items-center justify-between gap-2 px-3 py-2">
                    <span className="text-sm font-semibold" dir="auto">{label(d)}</span>
                    {d.needs_type ? <Chip tone="orange">{l.needType}</Chip> : !d.read ? <Chip>{l.notRead}</Chip> : d.error ? <Chip tone="red">{l.unreadable}</Chip>
                      : flagsOf(d.id) > 0 ? <Chip tone="red">⚑ {flagsOf(d.id)}</Chip> : d.fields.some((f) => f.doubt) ? <Chip tone="orange">?</Chip> : <Chip tone="green">✓</Chip>}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      <Panel title={l.panel} banner={l.banner} tone="review">
        {!res && !busy && <p className="text-sm">{l.pick}</p>}
        {cur && res && (
          <>
            <div data-test="verdict" className="flex flex-wrap items-center gap-2">
              <Chip tone={VTONE[res.verdict] ?? "neutral"}>{l.verdicts[res.verdict as keyof typeof l.verdicts] ?? res.verdict}</Chip>
              <Chip tone={res.risk === "high" ? "red" : res.risk === "medium" ? "orange" : "green"}>risk: {res.risk}</Chip>
              {res.total_ms > 0 && <Chip>{(res.total_ms / 1000).toFixed(0)} s</Chip>}
            </div>
            <p dir="auto" className="text-sm leading-relaxed text-nbe-strong">{lang === "ar" ? res.summary.ar : res.summary.en}</p>
            {res.flags.length > 0 && (
              <Block label={l.evidence} accent="orange">
                {res.flags.map((f, i) => (
                  <div key={i} className="mb-2">
                    <div className="flex flex-wrap items-center gap-1">
                      <Chip tone={SEVT[f.severity]}>{f.severity}</Chip><Chip>{f.source === "forensics" ? "🔬" : f.source === "document" ? "📄" : "🔗"} {f.rule}</Chip>
                      {f.status === "needs_confirmation" && <Chip tone="orange">{l.confirm}</Chip>}
                    </div>
                    <div dir="auto" className="mt-1 text-xs">{lang === "ar" ? f.detail_ar : f.detail_en}</div>
                    <div className="mt-0.5 flex flex-wrap gap-2">
                      {f.documents.map((id) => {
                        const d = cur.documents.find((x) => x.id === id);
                        return d ? <button key={id} className="text-xs text-nbe-green underline" onClick={() => { setOpen(id); setTab("fields"); }}>{label(d)}</button> : null;
                      })}
                    </div>
                  </div>
                ))}
              </Block>
            )}
            {cur.decision ? (
              <Block label={l.decided} accent="green">
                <Chip tone={DECISION[cur.decision.decision].tone}>{DECISION[cur.decision.decision][lang]}</Chip>
                {cur.decision.note && <p dir="auto" className="mt-1 text-xs">{cur.decision.note}</p>}
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
        {cur && <button className="mt-auto text-start text-xs text-status-stop underline" onClick={removeFile}>{l.deleteFile}</button>}
      </Panel>

      {cur && doc && (
        <Modal title={`${label(doc)} · ${cur.id}`} onClose={() => setOpen(null)}>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {(["document", "fields", "ela"] as const).filter((t) => (t !== "ela" || doc.has_ela) && (t !== "fields" || doc.fields.length > 0)).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={`rounded-full px-3 py-1 text-sm ${tab === t ? "bg-nbe-green text-white" : "bg-nbe-bg"}`}>{l[t]}</button>
            ))}
            <button className="ms-auto text-xs text-status-stop underline"
                    onClick={() => { setOpen(null); run(() => del<Case>(`${base}/documents/${doc.id}`)); }}>{l.remove}</button>
          </div>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-xs text-nbe-text">{l.type}</span>
            <select data-test="set-type" className={`rounded-lg border px-2 py-1 text-sm ${doc.needs_type ? "border-nbe-orange bg-nbe-orange/10" : "border-nbe-border"}`}
                    value={doc.needs_type ? "" : doc.doc_type} onChange={(e) => setType(doc.id, e.target.value)}>
              {doc.needs_type && <option value="" disabled>{l.chooseType}</option>}
              {(reader?.doc_types ?? []).map((t) => <option key={t.id} value={t.id}>{lang === "ar" ? t.ar : t.en}</option>)}
            </select>
          </div>
          {doc.source && (
            <p className="mb-3 text-xs text-nbe-text" dir="auto">
              {l.pdf} · {doc.source.pages} {l.pages} · {l.madeBy}: {[doc.source.producer, doc.source.creator].filter(Boolean).join(" / ") || "—"} · {l.saves}: {doc.source.revisions}
              {doc.source.created && ` · ${doc.source.created}`}{doc.source.modified && doc.source.modified !== doc.source.created && ` → ${doc.source.modified}`}
            </p>
          )}
          {doc.error && <ErrorNote error={`${l.unreadable}: ${doc.error}`} />}
          {tab === "document" && (
            <div>
              <div className="relative">
                <img src={`${base}/documents/${doc.id}/image`} alt={doc.doc_type} className="w-full rounded-lg border border-nbe-border" />
                {doc.size && doc.boxes.map((x, i) => (
                  <div key={i} title={x.kind} className={`absolute rounded border-4 ${x.kind === "patch" ? "border-status-stop" : x.kind === "resave" ? "border-nbe-green" : "border-nbe-orange"}`}
                       style={{ left: `${(100 * x.bbox[0]) / doc.size![0]}%`, top: `${(100 * x.bbox[1]) / doc.size![1]}%`,
                                width: `${(100 * (x.bbox[2] - x.bbox[0])) / doc.size![0]}%`, height: `${(100 * (x.bbox[3] - x.bbox[1])) / doc.size![1]}%` }} />
                ))}
              </div>
              {doc.boxes.length > 0 && <p className="mt-2 text-xs">{l.boxes}</p>}
              {doc.noise_checkable === false && <p className="mt-2 text-xs text-nbe-text">{l.uncheckable}</p>}
            </div>
          )}
          {tab === "ela" && (
            <div>
              <img src={`${base}/documents/${doc.id}/image?ela=true`} alt="ELA" className="mx-auto rounded-lg" />
              <p className="mt-2 text-xs">{l.elaNote}</p>
            </div>
          )}
          {tab === "fields" && (
            <div className="grid gap-4 md:grid-cols-2">
              <img src={`${base}/documents/${doc.id}/image`} alt={doc.doc_type} className="w-full rounded-lg border border-nbe-border" />
              <table className="w-full">
                <tbody>
                  {doc.fields.map((f) => <FieldRow key={f.key} f={f} lang={lang} onSave={saveField(doc.id)} />)}
                  <tr className="border-t border-nbe-border"><td className="py-1.5 pe-3 text-sm font-semibold">software</td><td colSpan={2} className="text-sm">{doc.software ?? "—"}</td></tr>
                  {doc.fields.some((f) => f.base) && <tr><td colSpan={3} className="pt-2 text-xs text-nbe-text">{l.baseNote}</td></tr>}
                </tbody>
              </table>
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}
