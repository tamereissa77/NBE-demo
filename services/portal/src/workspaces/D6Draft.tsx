import { useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
import { Md } from "../components/Md";
import { Button, Chip, Modal } from "./common";

// A passage of an attached file that an answer or a draft rests on, with the result of checking against it
export interface Source { label: string; file: string; file_id: string | null; page: number; where: string; heading: string; text: string; snippet: string;
                          status: "verified" | "supported" | "nearby" | "unchecked" | "check"; missing: string[]; elsewhere?: Record<string, string[]>;
                          wrong_page?: number[]; page_image: boolean }

// A drafted document as the service reports it: its parts, what has to be done before sending, where it came from
export interface Draft {
  version: number; by: string; type: string; subject: string; body: string; clean: string;
  placeholders: string[]; wrong_weekdays: { written: string; problem: string }[]; unsourced_figures: string[];
  policy: { rule: string; found: string; requested?: boolean }[]; blocking: string[];
  approved: { by: string; at: string } | null; changes?: { segments: { op: "same" | "add" | "del"; text: string }[]; changed_share: number };
  sources?: Source[];
}
export type DraftOpts = Record<string, string>;
interface Choices { options: Record<string, { id: string; label: string }[]>; templates: { id: string; label: string; type: string; request: string }[] }

const T = {
  en: { draft: "Draft", by: { assistant: "written by the assistant", employee: "edited by you" } as Record<string, string>, subject: "Subject",
        before: "Before sending", fill: "Fill in", wrongDay: "The weekday does not match the date", noSource: "Not in your request, the files or the bank's facts (check or remove)",
        policy: "Policy", asked: "you asked for this: check you are authorised", ready: "Nothing left to do: ready for approval",
        copy: "Copy", copied: "Copied", word: "Word", edit: "Edit", save: "Save", cancel: "Cancel", approve: "Approve", approved: (who: string, at: string) => `Approved by ${who}, ${at} (recorded in the audit log)`,
        changes: "Show changes", changed: (pct: number) => `${pct}% of the words changed`, versions: "Versions", sources: "Taken from", older: "An earlier version: read only",
        options: "Draft options", template: "Start from a template", none: "No template",
        names: { type: "Document", tone: "Tone", length: "Length", audience: "Reader", language: "Language" } as Record<string, string> },
  ar: { draft: "مسودة", by: { assistant: "كتبها المساعد", employee: "عدّلتها أنت" } as Record<string, string>, subject: "الموضوع",
        before: "قبل الإرسال", fill: "أكمِل", wrongDay: "اليوم لا يطابق التاريخ", noSource: "غير موجود في طلبك أو الملفات أو بيانات البنك (راجِعه أو احذفه)",
        policy: "السياسات", asked: "أنت طلبت ذلك: تأكد من أن لديك الصلاحية", ready: "لا شيء متبقٍ: جاهزة للاعتماد",
        copy: "نسخ", copied: "تم النسخ", word: "Word", edit: "تعديل", save: "حفظ", cancel: "إلغاء", approve: "اعتماد", approved: (who: string, at: string) => `اعتمدها ${who}، ${at} (مُسجَّل في سجل المراجعة)`,
        changes: "إظهار التغييرات", changed: (pct: number) => `تغيّر ${pct}% من الكلمات`, versions: "النسخ", sources: "مأخوذ من", older: "نسخة سابقة: للقراءة فقط",
        options: "خيارات المسودة", template: "ابدأ من قالب", none: "بدون قالب",
        names: { type: "نوع المستند", tone: "الأسلوب", length: "الطول", audience: "القارئ", language: "اللغة" } as Record<string, string> },
};
const MARK: Record<Source["status"], string> = { verified: "✓", supported: "✓", nearby: "✓", unchecked: "·", check: "⚠" };

// The document card that replaces a plain chat bubble when the answer is a draft
export function DraftCard({ draft, conv, latest, lang, onChange, onSource }:
  { draft: Draft; conv: string | null; latest: boolean; lang: "en" | "ar"; onChange: (d: Draft, text: string) => void; onSource: (s: Source) => void }) {
  const t = T[lang];
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(draft.clean);
  const [showChanges, setShowChanges] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [versions, setVersions] = useState<{ version: number; by: string; at: string; text: string }[] | null>(null);
  const todo = draft.placeholders.length + draft.wrong_weekdays.length + draft.unsourced_figures.length + draft.policy.length;

  const act = async (path: string, body: object) => {
    setError("");
    try {
      const r = await postJSON<{ answer?: string; draft: Draft }>(path, { conversation_id: conv, ...body });
      onChange(r.draft, r.answer ?? r.draft.clean);
      return true;
    } catch (e) { setError((e as Error).message); return false; }
  };
  const copy = async () => { await navigator.clipboard?.writeText(draft.clean).catch(() => {}); setCopied(true); setTimeout(() => setCopied(false), 1500); };

  return (
    <div data-test="draft-card" className="rounded-xl border border-line bg-white p-4">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <Chip tone="green">{t.draft} · v{draft.version}</Chip>
        <Chip>{t.by[draft.by] ?? draft.by}</Chip>
        {draft.changes && <Chip tone="orange">{t.changed(Math.round(draft.changes.changed_share * 100))}</Chip>}
        {draft.changes && !editing && (
          <label className="ms-auto flex cursor-pointer items-center gap-1 text-xs text-ink-soft">
            <input type="checkbox" data-test="show-changes" checked={showChanges} onChange={(e) => setShowChanges(e.target.checked)} /> {t.changes}
          </label>
        )}
      </div>

      {editing ? (
        <textarea data-test="draft-edit" dir="auto" value={text} onChange={(e) => setText(e.target.value)} rows={Math.min(22, text.split("\n").length + 2)}
                  className="w-full rounded-lg border border-line p-3 text-sm leading-relaxed" />
      ) : showChanges && draft.changes ? (
        <div data-test="draft-changes" dir="auto" className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
          {draft.changes.segments.map((s, i) => s.op === "same" ? <span key={i}>{s.text}</span>
            : s.op === "add" ? <ins key={i} className="rounded bg-brand/15 no-underline">{s.text}</ins>
            : <del key={i} className="rounded bg-status-stop/10 text-status-stop">{s.text}</del>)}
        </div>
      ) : (
        <>
          {draft.subject && <div dir="auto" className="mb-2 border-b border-line pb-2 text-sm"><span className="text-ink-soft">{t.subject}: </span><b data-test="draft-subject">{draft.subject}</b></div>}
          {/* A letter's line breaks matter (the address block, the signature): keep them, except inside tables and lists */}
          <Md text={draft.body.replace(/([^\n|])\n(?=[^\n|\-*#\d])/g, "$1  \n")} />
        </>
      )}

      {todo > 0 ? (
        <div data-test="draft-review" className="mt-3 rounded-lg border border-accent bg-accent/10 px-3 py-2 text-xs text-ink">
          <div className="mb-1 font-semibold">{t.before}</div>
          {draft.placeholders.length > 0 && <div>✎ {t.fill}: {draft.placeholders.map((p) => <b key={p} dir="auto" className="me-1 rounded bg-white px-1">[{p}]</b>)}</div>}
          {draft.policy.map((p) => <div key={p.found} className={p.requested ? "" : "text-status-stop"}>⚠ {t.policy}: {p.rule} <b dir="auto">“{p.found}”</b>{p.requested && ` (${t.asked})`}</div>)}
          {draft.wrong_weekdays.map((w) => <div key={w.written} className="text-status-stop">⚠ {t.wrongDay}: <b dir="auto">{w.written}</b> ({w.problem})</div>)}
          {draft.unsourced_figures.length > 0 && <div className="text-status-stop">⚠ {t.noSource}: <b dir="ltr">{draft.unsourced_figures.join(", ")}</b></div>}
        </div>
      ) : !draft.approved && <div data-test="draft-ready" className="mt-3 rounded-lg bg-brand/10 px-3 py-2 text-xs text-brand">✓ {t.ready}</div>}

      {draft.sources && draft.sources.length > 0 && (
        <div data-test="draft-sources" className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-ink-soft">{t.sources}:</span>
          {draft.sources.map((s) => (
            <button key={s.label} data-test="source" onClick={() => onSource(s)} className="rounded-md bg-canvas px-2 py-1 ring-1 ring-line hover:bg-accent/25">
              <span dir="auto">{s.file}</span>{s.where && ` · ${s.where}`} {MARK[s.status]}
            </button>
          ))}
        </div>
      )}

      {draft.approved && <div data-test="draft-approved" className="mt-3 rounded-lg bg-brand px-3 py-2 text-xs font-semibold text-white">✓ {t.approved(draft.approved.by, draft.approved.at)}</div>}
      {error && <p className="mt-2 rounded-lg bg-status-stop/10 p-2 text-xs text-status-stop">{error}</p>}

      <div className="mt-3 flex flex-wrap gap-2">
        {editing ? (
          <>
            <Button test="draft-save" onClick={async () => { if (await act("/api/d6/draft/save", { text })) setEditing(false); }}>{t.save}</Button>
            <Button variant="ghost" onClick={() => { setEditing(false); setText(draft.clean); }}>{t.cancel}</Button>
          </>
        ) : (
          <>
            <Button variant="ghost" test="draft-copy" onClick={copy}>{copied ? t.copied : t.copy}</Button>
            {conv && <a data-test="draft-word" href={`/api/d6/draft/${conv}/export.docx?version=${draft.version}`} className="rounded-full bg-white px-4 py-2 text-sm font-semibold text-brand ring-1 ring-line hover:bg-canvas">{t.word}</a>}
            {conv && <Button variant="ghost" test="draft-versions" onClick={() => getJSON<{ versions: NonNullable<typeof versions> }>(`/api/d6/draft/${conv}/versions`).then((r) => setVersions(r.versions)).catch(() => {})}>{t.versions}</Button>}
            {latest && !draft.approved && <Button variant="ghost" test="draft-edit-button" onClick={() => { setText(draft.clean); setEditing(true); }}>{t.edit}</Button>}
            {latest && !draft.approved && <Button test="draft-approve" disabled={draft.blocking.length > 0} onClick={() => act("/api/d6/draft/approve", {})}>{t.approve}</Button>}
          </>
        )}
      </div>

      {versions && (
        <Modal title={t.versions} onClose={() => setVersions(null)}>
          <div className="space-y-3">
            {[...versions].reverse().map((v) => (
              <div key={v.version} className="rounded-lg border border-line p-3">
                <div className="mb-1 text-xs font-semibold text-ink-soft">v{v.version} · {t.by[v.by] ?? v.by} · {v.at}</div>
                <div dir="auto" className="max-h-48 overflow-auto whitespace-pre-wrap text-sm text-ink">{v.text}</div>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </div>
  );
}

// The choices sent with a drafting request, and the templates that start one
export function DraftOptions({ lang, value, onChange, onTemplate }:
  { lang: "en" | "ar"; value: DraftOpts; onChange: (v: DraftOpts) => void; onTemplate: (request: string) => void }) {
  const t = T[lang];
  const [choices, setChoices] = useState<Choices | null>(null);
  useEffect(() => { getJSON<Choices>(`/api/d6/drafting/options?lang=${lang}`).then(setChoices).catch(() => {}); }, [lang]);
  if (!choices) return null;
  const select = "rounded-lg border border-line bg-white px-2 py-1 text-xs";
  return (
    <div data-test="draft-options" className="mx-3 mb-1 flex flex-wrap items-center gap-2 rounded-lg bg-canvas px-3 py-2 text-xs">
      <b className="text-ink-soft">{t.options}</b>
      <select data-test="draft-template" className={select} value={value.template ?? ""} onChange={(e) => {
        const tpl = choices.templates.find((x) => x.id === e.target.value);
        onChange({ ...value, template: e.target.value, ...(tpl ? { type: tpl.type } : {}) });
        if (tpl) onTemplate(tpl.request);
      }}>
        <option value="">{t.template}: {t.none}</option>
        {choices.templates.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
      </select>
      {Object.entries(choices.options).map(([name, list]) => (
        <label key={name} className="flex items-center gap-1">
          <span className="text-ink-soft">{t.names[name] ?? name}</span>
          <select data-test={`draft-${name}`} className={select} value={value[name] ?? "auto"} onChange={(e) => onChange({ ...value, [name]: e.target.value })}>
            {list.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </label>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ summaries
// What the service reports about a summary: what it was built from, and the result of checking each point
export interface SummaryReport {
  form: string; legal: boolean; checked: boolean; corrected: number; missing: string[];
  unsupported: { point: string; verdict: string; note: string }[];
  coverage: { passages_read: number; passages_total: number; parts_read: number; parts_total: number; complete: boolean; sections: number };
}
export interface Coverage { passages_read: number; passages_total: number; complete: boolean }

const S = {
  en: { checked: (n: number) => n ? `Every point was checked against the source; ${n} corrected` : "Every point was checked against the source", notChecked: "Not checked against the source",
        unsupported: "Could not be confirmed in the source", missing: "The source also says (not in this summary)",
        whole: "Built from the whole source", sections: (n: number) => `The source is long: it was read in ${n} sections, then summarised`,
        partial: (a: number, b: number) => `Only part of the source was read: ${a} of ${b} passages`,
        legal: "This reads like a contract or a ruling. For clauses, risks and comparison with the approved template, use Legal Documents Summarisation",
        copy: "Copy", copied: "Copied", word: "Word", shorter: "Shorter", longer: "More detail", email: "Turn into an e-mail",
        askShorter: "Make it shorter.", askLonger: "Add more detail.", askEmail: "Draft an e-mail that passes this summary on to [recipient].",
        options: "Summary options", focus: "Only about…", names: { form: "Form", length: "Length", audience: "Reader", language: "Language" } as Record<string, string>,
        cut: (a: number, b: number) => `This file is long: only the first ${a} of its ${b} passages were read for this answer. Ask for a summary to cover all of it.` },
  ar: { checked: (n: number) => n ? `تمت مراجعة كل نقطة على المصدر، وصُحِّحت ${n}` : "تمت مراجعة كل نقطة على المصدر", notChecked: "لم تُراجَع على المصدر",
        unsupported: "لم يتأكد وجودها في المصدر", missing: "ورد في المصدر أيضاً (غير مذكور في الملخص)",
        whole: "مبني على المصدر كاملاً", sections: (n: number) => `المصدر طويل: قُرئ على ${n} أجزاء ثم لُخِّص`,
        partial: (a: number, b: number) => `قُرئ جزء من المصدر فقط: ${a} من ${b} مقطعاً`,
        legal: "يبدو هذا عقداً أو حكماً. لتحليل البنود والمخاطر والمقارنة بالنموذج المعتمد استخدم تلخيص المستندات القانونية",
        copy: "نسخ", copied: "تم النسخ", word: "Word", shorter: "أقصر", longer: "تفصيل أكثر", email: "حوّله إلى بريد",
        askShorter: "اجعله أقصر.", askLonger: "أضف تفاصيل أكثر.", askEmail: "اكتب بريداً إلكترونياً ينقل هذا الملخص إلى [المستلم].",
        options: "خيارات الملخص", focus: "فقط ما يخص…", names: { form: "الشكل", length: "الطول", audience: "القارئ", language: "اللغة" } as Record<string, string>,
        cut: (a: number, b: number) => `هذا الملف طويل: قُرئ أول ${a} من ${b} مقطعاً فقط لهذه الإجابة. اطلب ملخصاً ليشمل الملف كله.` },
};

// Under a summary: what it covers, what the check found, and what to do with it next
export function SummaryTools({ report, text, lang, latest, onAsk }:
  { report: SummaryReport; text: string; lang: "en" | "ar"; latest: boolean; onAsk: (message: string) => void }) {
  const t = S[lang];
  const [copied, setCopied] = useState(false);
  const clean = text.replace(/\s*\[S\d+\]/g, "");
  const c = report.coverage;
  const word = async () => {
    const r = await fetch("/api/d6/export.docx", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: clean }) });
    if (!r.ok) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await r.blob());
    a.download = "summary.docx";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <div data-test="summary-tools" className="mt-2 rounded-lg border border-line bg-white px-3 py-2 text-xs text-ink">
      <div data-test="summary-coverage" className={c.complete ? "text-brand" : "text-status-stop"}>
        {c.complete ? (c.sections ? t.sections(c.sections) : t.whole) : t.partial(c.passages_read, c.passages_total)}
        {" · "}{report.checked ? t.checked(report.corrected) : t.notChecked}
      </div>
      {report.unsupported.length > 0 && (
        <div data-test="summary-unsupported" className="mt-1 text-status-stop">⚠ {t.unsupported}:
          <ul className="list-inside list-disc">{report.unsupported.map((u, i) => <li key={i} dir="auto">{u.point.replace(/\s*\[S\d+\]/g, "")}{u.note && <span className="text-ink-soft"> ({u.note})</span>}</li>)}</ul>
        </div>
      )}
      {report.missing.length > 0 && (
        <div data-test="summary-missing" className="mt-1">ℹ {t.missing}:
          <ul className="list-inside list-disc">{report.missing.map((m, i) => <li key={i} dir="auto">{m}</li>)}</ul>
        </div>
      )}
      {report.legal && <div data-test="summary-legal" className="mt-1 rounded bg-accent/15 px-2 py-1">⚖ {t.legal}: <a href="/d5" className="font-semibold text-brand underline">D5</a></div>}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button variant="ghost" test="summary-copy" onClick={async () => { await navigator.clipboard?.writeText(clean).catch(() => {}); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>{copied ? t.copied : t.copy}</Button>
        <Button variant="ghost" test="summary-word" onClick={word}>{t.word}</Button>
        {latest && <Button variant="ghost" test="summary-shorter" onClick={() => onAsk(t.askShorter)}>{t.shorter}</Button>}
        {latest && <Button variant="ghost" test="summary-longer" onClick={() => onAsk(t.askLonger)}>{t.longer}</Button>}
        {latest && <Button variant="ghost" test="summary-email" onClick={() => onAsk(t.askEmail)}>{t.email}</Button>}
      </div>
    </div>
  );
}

// Shown under an ordinary answer about a file that was too long to be read whole
export function CoverageNote({ coverage, lang }: { coverage: Coverage; lang: "en" | "ar" }) {
  return <p data-test="coverage-note" className="mt-2 rounded-lg bg-accent/15 px-3 py-1.5 text-xs text-ink">⚠ {S[lang].cut(coverage.passages_read, coverage.passages_total)}</p>;
}

// The choices sent with a summary request
export function SummaryOptions({ lang, value, onChange }: { lang: "en" | "ar"; value: DraftOpts; onChange: (v: DraftOpts) => void }) {
  const t = S[lang];
  const [choices, setChoices] = useState<{ options: Record<string, { id: string; label: string }[]> } | null>(null);
  useEffect(() => { getJSON<typeof choices>(`/api/d6/summary/options?lang=${lang}`).then(setChoices).catch(() => {}); }, [lang]);
  if (!choices) return null;
  const select = "rounded-lg border border-line bg-white px-2 py-1 text-xs";
  return (
    <div data-test="summary-options" className="mx-3 mb-1 flex flex-wrap items-center gap-2 rounded-lg bg-canvas px-3 py-2 text-xs">
      <b className="text-ink-soft">{t.options}</b>
      {Object.entries(choices.options).map(([name, list]) => (
        <label key={name} className="flex items-center gap-1">
          <span className="text-ink-soft">{t.names[name] ?? name}</span>
          <select data-test={`summary-${name}`} className={select} value={value[name] ?? "auto"} onChange={(e) => onChange({ ...value, [name]: e.target.value })}>
            {list.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </label>
      ))}
      <input data-test="summary-focus" dir="auto" placeholder={t.focus} value={value.focus ?? ""} onChange={(e) => onChange({ ...value, focus: e.target.value })}
             className="min-w-40 flex-1 rounded-lg border border-line bg-white px-2 py-1 text-xs" />
    </div>
  );
}

// ------------------------------------------------------------------ translations
// One unit of the text (a paragraph, a list item, a table row) with its translation and what the read-back found
export interface Segment { n: number; source: string; target: string; status: "ok" | "check" | "empty"; missing: string[]; extra: string[]; terms: string[] }
export interface TranslationReport { direction: string; target: string; total: number; translated: number; to_check: number; complete: boolean; left_out: number;
                                     source?: string; segments: Segment[] }

const X = {
  en: { done: (a: number, b: number) => `${a} of ${b} paragraphs translated`, allChecked: "every figure and reference came through", toCheck: (n: number) => `${n} to check`,
        partial: (n: number) => `${n} paragraphs were not translated: the text is longer than one request allows`,
        ofAnswer: "Translation of the previous answer (say \"translate the file\" for the whole file)", ofPasted: "Translation of the pasted text", side: "Side by side", source: "Source", translation: "Translation", missing: "not in the translation", extra: "not in the source", term: "bank term not used", empty: "not translated",
        copy: "Copy", copied: "Copied", word: "Word", bilingual: "Word, two columns", options: "Translation options",
        names: { target: "Into", register: "Style", numerals: "Numerals" } as Record<string, string> },
  ar: { done: (a: number, b: number) => `تُرجم ${a} من ${b} فقرة`, allChecked: "جميع الأرقام والمراجع انتقلت كما هي", toCheck: (n: number) => `${n} للمراجعة`,
        partial: (n: number) => `لم تُترجم ${n} فقرة: النص أطول مما يسمح به طلب واحد`,
        ofAnswer: "ترجمة الإجابة السابقة (اكتب «ترجم الملف» لترجمة الملف كله)", ofPasted: "ترجمة النص الملصق", side: "جنباً إلى جنب", source: "الأصل", translation: "الترجمة", missing: "غير موجود في الترجمة", extra: "غير موجود في الأصل", term: "مصطلح البنك غير مستخدم", empty: "لم يُترجم",
        copy: "نسخ", copied: "تم النسخ", word: "Word", bilingual: "Word بعمودين", options: "خيارات الترجمة",
        names: { target: "إلى", register: "الأسلوب", numerals: "الأرقام" } as Record<string, string> },
};

// Under a translation: how much was translated, what to check, and the source beside the translation
export function TranslationView({ report, text, lang }: { report: TranslationReport; text: string; lang: "en" | "ar" }) {
  const t = X[lang];
  const [side, setSide] = useState(report.to_check > 0);
  const [copied, setCopied] = useState(false);
  const save = async (body: object, name: string) => {
    const r = await fetch("/api/d6/export.docx", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await r.blob());
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const why = (s: Segment) => [s.status === "empty" && t.empty, s.missing.length > 0 && `${s.missing.join(", ")}: ${t.missing}`,
                              s.extra.length > 0 && `${s.extra.join(", ")}: ${t.extra}`, s.terms.length > 0 && `${t.term}: ${s.terms.join(", ")}`].filter(Boolean).join(" · ");
  return (
    <div data-test="translation-view" className="mt-2 rounded-lg border border-line bg-white px-3 py-2 text-xs text-ink">
      <div data-test="translation-status" className={report.complete && report.to_check === 0 ? "text-brand" : "text-ink"}>
        {report.source && <b data-test="translation-source">{report.source === "the previous answer" ? t.ofAnswer : report.source === "pasted text" ? t.ofPasted : report.source} · </b>}
        {report.direction} · {t.done(report.translated, report.total)} · {report.to_check === 0 ? t.allChecked : <b className="text-status-stop">{t.toCheck(report.to_check)}</b>}
      </div>
      {!report.complete && <div data-test="translation-partial" className="mt-1 text-status-stop">⚠ {t.partial(report.left_out)}</div>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button variant="ghost" test="translation-copy" onClick={async () => { await navigator.clipboard?.writeText(text).catch(() => {}); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>{copied ? t.copied : t.copy}</Button>
        <Button variant="ghost" test="translation-word" onClick={() => save({ text }, "translation.docx")}>{t.word}</Button>
        <Button variant="ghost" test="translation-bilingual" onClick={() => save({ rows: report.segments.filter((s) => s.target).map((s) => [s.source, s.target]) }, "translation-bilingual.docx")}>{t.bilingual}</Button>
        <label className="ms-auto flex cursor-pointer items-center gap-1 text-ink-soft">
          <input type="checkbox" data-test="translation-side" checked={side} onChange={(e) => setSide(e.target.checked)} /> {t.side}
        </label>
      </div>
      {side && (
        <table data-test="translation-table" className="mt-2 w-full table-fixed border-collapse text-xs">
          <thead><tr className="text-ink-soft"><th className="w-1/2 border border-line px-2 py-1 text-start">{t.source}</th><th className="border border-line px-2 py-1 text-start">{t.translation}</th></tr></thead>
          <tbody>
            {report.segments.filter((s) => s.source.trim() && !/^\s*\|[\s:|-]+\|\s*$/.test(s.source)).map((s) => (
              <tr key={s.n} data-test={s.status === "ok" ? "segment" : "segment-flagged"} className={s.status === "ok" ? "" : "bg-accent/15"}>
                <td dir="auto" className="whitespace-pre-wrap border border-line px-2 py-1 align-top">{s.source}</td>
                <td dir="auto" className="whitespace-pre-wrap border border-line px-2 py-1 align-top">{s.target}{s.status !== "ok" && <div className="mt-1 text-status-stop" dir="auto">⚠ {why(s)}</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// The choices sent with a translation request
export function TranslationOptions({ lang, value, onChange }: { lang: "en" | "ar"; value: DraftOpts; onChange: (v: DraftOpts) => void }) {
  const t = X[lang];
  const [choices, setChoices] = useState<{ options: Record<string, { id: string; label: string }[]> } | null>(null);
  useEffect(() => { getJSON<typeof choices>(`/api/d6/translation/options?lang=${lang}`).then(setChoices).catch(() => {}); }, [lang]);
  if (!choices) return null;
  return (
    <div data-test="translation-options" className="mx-3 mb-1 flex flex-wrap items-center gap-2 rounded-lg bg-canvas px-3 py-2 text-xs">
      <b className="text-ink-soft">{t.options}</b>
      {Object.entries(choices.options).map(([name, list]) => (
        <label key={name} className="flex items-center gap-1">
          <span className="text-ink-soft">{t.names[name] ?? name}</span>
          <select data-test={`translation-${name}`} className="rounded-lg border border-line bg-white px-2 py-1 text-xs" value={value[name] ?? list[0].id} onChange={(e) => onChange({ ...value, [name]: e.target.value })}>
            {list.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </label>
      ))}
    </div>
  );
}


// ------------------------------------------------------------------ code: what was checked, what was run, what to be careful with
export interface CodeReport { mode: "write" | "review"; masked: number; repaired: boolean; first_problem: string;
  blocks: { lang: string; problems: string[]; run: { ok: boolean; error: string; seconds: number; files: string[] } | null }[];
  warnings: { kind: string; severity: "high" | "medium"; message: string; where: "yours" | "generated" }[] }

const C = {
  en: { ran: (f: string, s: number) => `Run on ${f} in ${s} s: the result under the code comes from the data`, failed: "The code did not run on the file",
        checked: "Checked before it was shown: it parses and uses only functions that exist", problem: "Check before use",
        repaired: "Corrected once after its first check failed", masked: (n: number) => `${n} secret${n === 1 ? "" : "s"} hidden before the code was sent to the model`,
        yours: "In your code", generated: "In the code written here", options: "Code",
        names: { language: "Language", depth: "Explanation", explain: "Explain in" } as Record<string, string> },
  ar: { ran: (f: string, s: number) => `تم تشغيله على ${f} في ${s} ث: النتيجة أسفل الكود مصدرها البيانات`, failed: "تعذّر تشغيل الكود على الملف",
        checked: "تم فحصه قبل عرضه: صياغته سليمة ويستخدم دوال موجودة فقط", problem: "راجِعه قبل الاستخدام",
        repaired: "صُحّح مرة واحدة بعد فشل الفحص الأول", masked: (n: number) => `تم إخفاء ${n} من البيانات السرية قبل إرسال الكود إلى النموذج`,
        yours: "في الكود الذي أرسلته", generated: "في الكود المكتوب هنا", options: "الكود",
        names: { language: "اللغة", depth: "الشرح", explain: "لغة الشرح" } as Record<string, string> },
};

export function CodeNote({ report, lang }: { report: CodeReport; lang: "en" | "ar" }) {
  const t = C[lang];
  const run = report.blocks.map((b) => b.run).find(Boolean);
  const problems = report.blocks.flatMap((b) => b.problems);
  const written = report.mode === "write" && report.blocks.length > 0;
  if (!run && !written && !report.masked && report.warnings.length === 0) return null;
  const line = "rounded-md px-2 py-1";
  return (
    <div data-test="code-note" className="mt-2 space-y-1 rounded-lg border border-line bg-white px-3 py-2 text-xs">
      {report.warnings.map((w) => (
        <p key={w.kind} data-test="code-warning" className={`${line} ${w.severity === "high" ? "bg-status-stop/10 text-status-stop" : "bg-accent/15 text-ink"}`}>
          ⚠ <b>{w.where === "yours" ? t.yours : t.generated}:</b> {w.message}
        </p>
      ))}
      {report.masked > 0 && <p data-test="code-masked" className={`${line} bg-canvas`}>🔒 {t.masked(report.masked)}</p>}
      {run && (run.ok
        ? <p data-test="code-ran" className={`${line} bg-canvas`}>✓ {t.ran(run.files.join(", "), run.seconds)}</p>
        : <p data-test="code-ran" className={`${line} bg-accent/15`}>⚠ {t.failed}: <span dir="ltr">{run.error}</span></p>)}
      {!run && written && (problems.length === 0
        ? <p data-test="code-checked" className={`${line} bg-canvas`}>✓ {t.checked}</p>
        : <p data-test="code-checked" className={`${line} bg-accent/15`}>⚠ {t.problem}: <span dir="ltr">{problems.join("; ")}</span></p>)}
      {report.repaired && <p className={`${line} bg-canvas text-ink-soft`}>↻ {t.repaired}: <span dir="ltr">{report.first_problem}</span></p>}
    </div>
  );
}

// The choices sent with a code request
export function CodeOptions({ lang, value, onChange }: { lang: "en" | "ar"; value: DraftOpts; onChange: (v: DraftOpts) => void }) {
  const t = C[lang];
  const [choices, setChoices] = useState<{ options: Record<string, { id: string; label: string }[]> } | null>(null);
  useEffect(() => { getJSON<typeof choices>(`/api/d6/code/options?lang=${lang}`).then(setChoices).catch(() => {}); }, [lang]);
  if (!choices) return null;
  return (
    <div data-test="code-options" className="mx-3 mb-1 flex flex-wrap items-center gap-2 rounded-lg bg-canvas px-3 py-2 text-xs">
      <b className="text-ink-soft">{t.options}</b>
      {Object.entries(choices.options).map(([name, list]) => (
        <label key={name} className="flex items-center gap-1">
          <span className="text-ink-soft">{t.names[name] ?? name}</span>
          <select data-test={`code-${name}`} className="rounded-lg border border-line bg-white px-2 py-1 text-xs" value={value[name] ?? "auto"} onChange={(e) => onChange({ ...value, [name]: e.target.value })}>
            {list.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </label>
      ))}
    </div>
  );
}
