import { useEffect, useRef, useState } from "react";
import { ApiError, getJSON, postJSON, type TraceStep } from "../api";
import { Md } from "../components/Md";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Modal, Panel, Spinner } from "./common";
import { CodeNote, CoverageNote, DraftCard, DraftOptions, SummaryOptions, SummaryTools, TranslationOptions, TranslationView,
         type CodeReport, type Coverage, type Draft, type DraftOpts, type Source, type SummaryReport, type TranslationReport } from "./D6Draft";

interface Route { lang: string; task: string; alias: string; reason: string; how: string; model?: string; fallback?: boolean }
interface Quote { quote: string; found: boolean; label: string | null }
interface Reply { answer: string; route: Route; meta: { latency_ms: number; tokens_per_s: number; completion_tokens: number }; trace: TraceStep[];
                  sources?: Source[]; quotes?: Quote[]; evidence?: { figures_not_in_files: string[] };
                  draft?: Draft; summary?: SummaryReport; coverage?: Coverage; translation?: TranslationReport; code?: CodeReport }
interface Suggested { task: string; q: string; file?: string }       // `file`: a sample the server attaches before the request is sent
interface Msg { role: "user" | "assistant"; content: string; reply?: Reply }
interface FileInfo { file_id: string; name: string; chars: number; converted_by: string; structure?: { pages?: number | null; headings?: number; tables?: number; sheets?: number; rows?: number } }

// The server keeps the conversation; the browser only remembers which one, so a reloaded page can ask for it back
const CONVERSATION_KEY = "d6.conversation";
interface Saved { messages: { role: "user" | "assistant"; content: string; reply?: Pick<Reply, "route" | "meta" | "sources" | "quotes" | "evidence" | "draft" | "summary" | "coverage" | "translation" | "code"> }[]; files: FileInfo[] }

// A file being read: the bytes go up first (sent / size), then the server reports its stage and the pages read so far
interface Pending { key: string; name: string; stage: string; sent: number; pagesDone?: number | null; pagesTotal?: number | null; percent: number; eta?: number | null; cancel: () => void }
interface JobStatus { job_id: string; stage: string; pages_done: number | null; pages_total: number | null; percent: number; eta_s: number | null;
                      result: FileInfo | null; error: { code: string; message: string } | null }

// fetch() cannot report how much of a request body has been sent; XMLHttpRequest can
const startUpload = (url: string, file: File, onSent: (fraction: number) => void, onXhr: (x: XMLHttpRequest) => void) =>
  new Promise<JobStatus>((resolve, reject) => {
    const x = new XMLHttpRequest();
    const fd = new FormData();
    fd.append("file", file);
    x.upload.onprogress = (e) => e.lengthComputable && onSent(e.loaded / e.total);
    x.onload = () => {
      let body: { detail?: { message?: string } | string } & Partial<JobStatus> = {};
      try { body = JSON.parse(x.responseText); } catch { /* not JSON */ }
      if (x.status >= 200 && x.status < 300) return resolve(body as JobStatus);
      reject(new ApiError(x.status, typeof body.detail === "string" ? body.detail : body.detail?.message ?? x.statusText));
    };
    x.onerror = () => reject(new ApiError(0, "Cannot reach the demo server."));
    x.onabort = () => reject(new ApiError(-1, "cancelled"));
    x.open("POST", url);
    onXhr(x);
    x.send(fd);
  });

const MARK: Record<Source["status"], string> = { verified: "✓", supported: "✓", nearby: "✓", unchecked: "·", check: "⚠" };
const MODELS: Record<string, string> = { workhorse: "Gemma 4 26B-A4B", hero: "gpt-oss-120b" };
const TABLE: [string, string, string][] = [
  ["file_chat", "File chat & extraction", "workhorse"], ["drafting", "Drafting", "workhorse"], ["summarise", "Summaries", "workhorse"],
  ["translation", "Translation", "workhorse"], ["code", "Code explanation", "hero"], ["general", "General", "workhorse"],
];
const L = {
  en: { ask: "Ask the assistant, or attach a file…", send: "Send", attach: "Attach file", panel: "Model-selection panel", banner: "Router picks the right model per task",
        lastRoute: "Last request", task: "Task", lang: "Language", model: "Model", why: "Why", how: "Decided by", fallback: "Hero model is not running: answered by the workhorse (start it with make hero)",
        table: "Routing table", thinking: "Routing and answering…", file: "File attached", dataiku: "Dataiku LLM Mesh", newChat: "New chat", cancel: "Cancel",
        sources: (n: number, ok: number) => `Sources: ${n} passage${n === 1 ? "" : "s"} cited, ${ok} confirmed against the file`,
        quoteMissing: "Quoted words not found in the files", looseFigures: "Not found in the files as written (worked out by the assistant, or to be checked)", under: "Under the heading", closest: "Closest text in this passage", passage: "The passage",
        showPage: (where: string) => `Show ${where} as an image`, foundIn: "it is in",
        wrongPage: (said: string, real: number) => `Check this: the answer says page ${said}, but this passage is on page ${real}`,
        status: { verified: "The figures in the answer are in this passage", nearby: "The figures are in this file; not all of them in this passage", supported: "The wording of the answer matches this passage",
                  unchecked: "Not checked: the answer and the passage are in different languages and the sentence has no figures",
                  check: "Check this: not found in the cited passage" },
        stage: { waiting: "waiting", uploading: (pct: number) => `uploading ${pct}%`, checking: "checking the file", converting: "converting the document",
                 reading: (done: number, total: number) => `reading page ${Math.min(done + 1, total)} of ${total}`, left: (s: number) => `about ${s} s left`, finishing: "finishing" }, tooMany: (max: number) => `You can attach up to ${max} files at a time. Remove one before adding another.`,
        tooLarge: (mb: string, max: number) => `This file is ${mb} MB. The largest file you can attach is ${max} MB.`,
        badType: (ext: string, ok: string) => `Files of type ${ext} cannot be attached. Supported: ${ok}.` },
  ar: { ask: "اسأل المساعد أو أرفق ملفاً…", send: "إرسال", attach: "إرفاق ملف", panel: "لوحة اختيار النموذج", banner: "الموجّه يختار النموذج المناسب لكل مهمة",
        lastRoute: "آخر طلب", task: "المهمة", lang: "اللغة", model: "النموذج", why: "السبب", how: "طريقة القرار", fallback: "النموذج الأكبر غير مشغّل: أجاب النموذج الأساسي (شغّله بـ make hero)",
        table: "جدول التوجيه", thinking: "جارٍ التوجيه والإجابة…", file: "ملف مرفق", dataiku: "التكامل مع Dataiku", newChat: "محادثة جديدة", cancel: "إلغاء",
        sources: (n: number, ok: number) => `المصادر: ${n} مقطع مُستشهد به، ${ok} تم التحقق منه في الملف`,
        quoteMissing: "نص مقتبس غير موجود في الملفات", looseFigures: "غير موجود في الملفات بهذا النص (محسوب من المساعد أو يحتاج إلى مراجعة)", under: "تحت العنوان", closest: "أقرب نص في هذا المقطع", passage: "المقطع",
        showPage: (where: string) => `عرض ${where} كصورة`, foundIn: "موجود في",
        wrongPage: (said: string, real: number) => `راجِع: الإجابة تذكر الصفحة ${said} لكن هذا المقطع في الصفحة ${real}`,
        status: { verified: "الأرقام الواردة في الإجابة موجودة في هذا المقطع", nearby: "الأرقام موجودة في هذا الملف، وليست كلها في هذا المقطع", supported: "صياغة الإجابة تطابق هذا المقطع",
                  unchecked: "لم يُتحقق: الإجابة والمقطع بلغتين مختلفتين والجملة بلا أرقام",
                  check: "راجِع: غير موجود في المقطع المُستشهد به" },
        stage: { waiting: "في الانتظار", uploading: (pct: number) => `جارٍ الرفع ${pct}%`, checking: "جارٍ فحص الملف", converting: "جارٍ تحويل المستند",
                 reading: (done: number, total: number) => `جارٍ قراءة الصفحة ${Math.min(done + 1, total)} من ${total}`, left: (s: number) => `يتبقى نحو ${s} ثانية`, finishing: "اللمسات الأخيرة" }, tooMany: (max: number) => `يمكن إرفاق ${max} ملفات كحد أقصى في المرة الواحدة. احذف ملفاً قبل إضافة آخر.`,
        tooLarge: (mb: string, max: number) => `حجم هذا الملف ${mb} ميجابايت. أقصى حجم يمكن إرفاقه هو ${max} ميجابايت.`,
        badType: (ext: string, ok: string) => `لا يمكن إرفاق ملفات من نوع ${ext}. الأنواع المدعومة: ${ok}.` },
};

export default function D6Assistant({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [shown, setShown] = useState<Source | null>(null);       // the cited passage open in the source panel
  const [showPage, setShowPage] = useState(false);
  const [draftOpts, setDraftOpts] = useState<DraftOpts>({});
  const [optsOpen, setOptsOpen] = useState(false);
  const [sumOpts, setSumOpts] = useState<DraftOpts>({});
  const [sumOpen, setSumOpen] = useState(false);
  const [trOpts, setTrOpts] = useState<DraftOpts>({});
  const [trOpen, setTrOpen] = useState(false);
  const [suggested, setSuggested] = useState<Suggested[]>([]);
  const [limits, setLimits] = useState<{ max_mb: number; max_files: number; types: string[]; supported: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const lastRoute = [...msgs].reverse().find((m) => m.reply)?.reply;
  const lastDraft = msgs.reduce((at, m, i) => (m.reply?.draft ? i : at), -1);      // only the newest draft can be edited or approved

  const [conv, setConv] = useState<string | null>(() => localStorage.getItem(CONVERSATION_KEY));
  useEffect(() => { getJSON<Suggested[]>("/api/d6/suggested").then(setSuggested).catch(() => {}); }, []);
  useEffect(() => {      // after a page reload: bring the conversation and its file back
    if (!conv || msgs.length) return;
    getJSON<Saved>(`/api/d6/conversation/${conv}`).then((c) => {
      setMsgs(c.messages.map((m) => ({ role: m.role, content: m.content, reply: m.reply && { answer: m.content, trace: [], ...m.reply } })));
      setFiles(c.files ?? []);
    }).catch(() => { localStorage.removeItem(CONVERSATION_KEY); setConv(null); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const startConversation = async () => {
    const { conversation_id } = await postJSON<{ conversation_id: string }>("/api/d6/conversation");
    localStorage.setItem(CONVERSATION_KEY, conversation_id);
    setConv(conversation_id);
    return conversation_id;
  };
  const newChat = () => { localStorage.removeItem(CONVERSATION_KEY); setConv(null); setMsgs([]); setFiles([]); setError(""); };
  useEffect(() => { getJSON<typeof limits>(`/api/d6/limits?lang=${lang}`).then(setLimits).catch(() => {}); }, [lang]);
  // Braces matter: newer Chrome returns a Promise from scrollIntoView, which React would call as a cleanup function
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [msgs, busy]);

  const send = async (text: string, attached: FileInfo[] = files) => {
    if (!text.trim() || busy) return;
    setQ(""); setError(""); setBusy(true);
    const next: Msg[] = [...msgs, { role: "user", content: text }];
    setMsgs(next);
    try {
      const ask = (id: string) => postJSON<Reply>("/api/d6/chat", { conversation_id: id, messages: [{ role: "user", content: text }], file_ids: attached.map((f) => f.file_id), draft_options: draftOpts, summary_options: sumOpts, translation_options: trOpts });
      // A conversation the server no longer has (it was restarted) is replaced by a new one, once
      const reply = await ask(conv ?? (await startConversation())).catch(async (e) => {
        if (e instanceof ApiError && e.status === 404) return ask(await startConversation());
        throw e;
      });
      setMsgs([...next, { role: "assistant", content: reply.answer, reply }]);
      onTrace(reply.trace);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // A suggested request that needs a file: the server attaches its sample, then the request goes with it
  const trySample = async (s: Suggested) => {
    if (!s.file) return send(s.q);
    setError(""); setBusy(true);
    try {
      const info = await postJSON<FileInfo>(`/api/d6/sample/${encodeURIComponent(s.file)}?lang=${lang}`, {});
      setFiles([info]);
      setBusy(false);
      await send(s.q, [info]);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  };
  const attach = async (picked: File[]) => {
    setError("");
    const max = limits?.max_files ?? 5;
    if (files.length + picked.length > max) return setError(l.tooMany(max));
    // Refuse an oversized or unsupported file here, before it is uploaded; the server checks again, and checks the content
    for (const f of picked) {
      const ext = f.name.includes(".") ? f.name.slice(f.name.lastIndexOf(".")).toLowerCase() : "";
      if (limits && f.size > limits.max_mb * 1024 * 1024) return setError(`${f.name}: ${l.tooLarge((f.size / 1024 / 1024).toFixed(1), limits.max_mb)}`);
      if (limits && !limits.types.includes(ext) && ![".doc", ".xls", ".ppt"].includes(ext)) return setError(`${f.name}: ${l.badType(ext || "?", limits.supported)}`);
    }
    setBusy(true);
    // Every picked file shows at once as "waiting"; they are read one at a time (each scanned page is a model call)
    const queue = picked.map((f, i) => ({ f, key: `${Date.now()}-${i}` }));
    let stopped = false;
    setPending(queue.map(({ f, key }) => ({ key, name: f.name, stage: "waiting", sent: 0, percent: 0, cancel: () => { stopped = true; } })));
    const patch = (key: string, change: Partial<Pending>) => setPending((all) => all.map((p) => (p.key === key ? { ...p, ...change } : p)));
    const drop = (key: string) => setPending((all) => all.filter((p) => p.key !== key));
    try {
      for (const { f, key } of queue) {
        if (stopped) { drop(key); continue; }
        let cancelled = false;
        try {
          let job = await startUpload(`/api/d6/upload/start?lang=${lang}`, f, (fraction) => patch(key, { stage: "uploading", sent: fraction }),
            (x) => patch(key, { stage: "uploading", cancel: () => { cancelled = true; x.abort(); } }));
          patch(key, { cancel: () => { cancelled = true; fetch(`/api/d6/upload/${job.job_id}`, { method: "DELETE" }).catch(() => {}); } });
          while (!["done", "failed", "cancelled"].includes(job.stage) && !cancelled) {
            patch(key, { stage: job.stage, pagesDone: job.pages_done, pagesTotal: job.pages_total, percent: job.percent, eta: job.eta_s });
            await new Promise((r) => setTimeout(r, 500));
            job = await getJSON<JobStatus>(`/api/d6/upload/${job.job_id}/status`);
          }
          if (job.stage === "done" && job.result && !cancelled) setFiles((have) => [...have, job.result as FileInfo]);
          if (job.stage === "failed") setError(`${f.name}: ${job.error?.message ?? ""}`);
        } catch (e) {
          if (!cancelled) setError(`${f.name}: ${(e as Error).message}`);
        }
        drop(key);
      }
    } finally { setPending([]); setBusy(false); }
  };
  const stageText = (p: Pending) =>
    p.stage === "uploading" ? l.stage.uploading(Math.round(p.sent * 100))
    : p.stage === "reading_pages" && p.pagesTotal ? l.stage.reading(p.pagesDone ?? 0, p.pagesTotal) + (p.eta ? ` · ${l.stage.left(p.eta)}` : "")
    : (l.stage as Record<string, unknown>)[p.stage] as string ?? p.stage;

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <section className="flex min-h-[32rem] flex-col rounded-xl border border-line bg-white lg:col-span-2">
        <div className="flex-1 space-y-3 overflow-y-auto p-5">
          {msgs.length === 0 && (
            <div className="flex flex-wrap gap-2">
              {suggested.map((s) => (
                <button key={s.task + s.q} data-test="suggested" onClick={() => trySample(s)} dir="auto" className="max-w-full truncate rounded-full bg-canvas px-3 py-1.5 text-sm text-ink hover:bg-accent/20">
                  <span className="me-1 text-xs text-brand">{s.task}</span>{s.file && <span className="me-1 text-xs text-ink-soft">📎 {s.file}</span>}{s.q.split("\n")[0]}
                </button>
              ))}
            </div>
          )}
          {msgs.map((m, i) =>
            m.role === "user" ? (
              <div key={i} dir="auto" className="ms-auto w-fit max-w-[85%] whitespace-pre-wrap rounded-2xl bg-brand px-4 py-2 text-sm text-white">{m.content}</div>
            ) : (
              <div key={i} data-test="answer" className="max-w-[92%] rounded-2xl bg-canvas px-4 py-3">
                {m.reply?.draft ? (
                  <DraftCard draft={m.reply.draft} conv={conv} lang={lang} latest={i === lastDraft}
                             onSource={(src) => { setShowPage(false); setShown(src); }}
                             onChange={(d, text) => setMsgs((all) => all.map((x, j) => (j === i && x.reply ? { ...x, content: text, reply: { ...x.reply, draft: d } } : x)))} />
                ) : (
                  <Md text={m.reply?.translation ? m.content.replace(/([^\n|])\n(?=[^\n|\-*#\d])/g, "$1  \n") /* a translated letter keeps its line breaks */ : m.content} onCite={m.reply?.sources?.length ? (label) => { setShowPage(false); setShown(m.reply?.sources?.find((s) => s.label === label) ?? null); } : undefined} />
                )}
                {(m.reply?.evidence?.figures_not_in_files.length ?? 0) > 0 && !m.reply?.draft && (
                  <p data-test="loose-figures" className="mt-2 rounded-lg bg-accent/15 px-3 py-1.5 text-xs text-ink">⚠ {l.looseFigures}: <b dir="ltr">{m.reply?.evidence?.figures_not_in_files.join(", ")}</b></p>
                )}
                {m.reply?.sources && m.reply.sources.length > 0 && (
                  <div data-test="sources" className="mt-2 rounded-lg border border-line bg-white px-3 py-2">
                    <div className="mb-1 text-xs font-semibold text-ink-soft">{l.sources(m.reply.sources.length, m.reply.sources.filter((s) => ["verified", "supported", "nearby"].includes(s.status)).length)}</div>
                    <div className="flex flex-wrap gap-1.5">
                      {m.reply.sources.map((s) => (
                        <button key={s.label} data-test="source" onClick={() => { setShowPage(false); setShown(s); }} title={s.heading}
                                className={`rounded-md px-2 py-1 text-xs ring-1 ${s.status === "check" ? "bg-accent/15 ring-accent" : "bg-canvas ring-line"} hover:bg-accent/25`}>
                          <b>{s.label}</b> · <span dir="auto">{s.file}</span>{s.where && ` · ${s.where}`} {MARK[s.status]}
                        </button>
                      ))}
                    </div>
                    {m.reply.quotes?.some((q) => !q.found) && (
                      <p className="mt-1.5 text-xs text-status-stop">{l.quoteMissing}: {m.reply.quotes.filter((q) => !q.found).map((q) => `“${q.quote.slice(0, 60)}”`).join(", ")}</p>
                    )}
                  </div>
                )}
                {m.reply?.coverage && !m.reply.coverage.complete && <CoverageNote coverage={m.reply.coverage} lang={lang} />}
                {m.reply?.code && <CodeNote report={m.reply.code} lang={lang} />}
                {m.reply?.translation && <TranslationView report={m.reply.translation} text={m.content} lang={lang} />}
                {m.reply?.summary && <SummaryTools report={m.reply.summary} text={m.content} lang={lang} latest={i === msgs.length - 1} onAsk={send} />}
                {m.reply && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <Chip tone="green">{m.reply.route.task} → {MODELS[m.reply.route.alias]}</Chip>
                    {m.reply.route.fallback && <Chip tone="orange">fallback: workhorse</Chip>}
                    <Chip>{(m.reply.meta.latency_ms / 1000).toFixed(1)} s · {m.reply.meta.tokens_per_s} tok/s</Chip>
                  </div>
                )}
              </div>
            ),
          )}
          {busy && pending.length === 0 && <Spinner label={l.thinking} />}
          <ErrorNote error={error} />
          <div ref={end} />
        </div>
        {pending.map((p) => (
          <div key={p.key} data-test="upload-progress" className="mx-3 mb-1 rounded-lg bg-canvas px-3 py-1.5 text-xs">
            <div className="flex items-center gap-2">
              ⏳ <b dir="auto">{p.name}</b> · {stageText(p)}
              <button onClick={p.cancel} title={l.cancel} className="ms-auto text-base">×</button>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded bg-line">
              <div className="h-full bg-brand transition-all duration-500" style={{ width: `${p.stage === "uploading" ? Math.round(p.sent * 3) : p.percent}%` }} />
            </div>
          </div>
        ))}
        {files.map((file) => (
          <div key={file.file_id} className="mx-3 mb-1 flex items-center gap-2 rounded-lg bg-accent/15 px-3 py-1.5 text-xs">
            📎 <b dir="auto">{file.name}</b> · {file.chars.toLocaleString()} chars{file.structure && ` · ${(file.structure.sheets ? [`${file.structure.sheets} sheets`, `${(file.structure.rows ?? 0).toLocaleString()} rows`] : [file.structure.pages && `${file.structure.pages} pages`, `${file.structure.headings} headings`, `${file.structure.tables} tables`]).filter(Boolean).join(", ")}`} · {file.converted_by}
            <button onClick={() => setFiles((have) => have.filter((f) => f.file_id !== file.file_id))} className="ms-auto text-base">×</button>
          </div>
        ))}
        {optsOpen && <DraftOptions lang={lang} value={draftOpts} onChange={setDraftOpts} onTemplate={setQ} />}
        {sumOpen && <SummaryOptions lang={lang} value={sumOpts} onChange={setSumOpts} />}
        {trOpen && <TranslationOptions lang={lang} value={trOpts} onChange={setTrOpts} />}
        <form onSubmit={(e) => { e.preventDefault(); send(q); }} className="flex gap-2 border-t border-line p-3">
          <input ref={fileInput} type="file" multiple className="hidden" accept=".pdf,.docx,.pptx,.html,.md,.txt,.png,.jpg,.jpeg,.webp,.xlsx,.xlsm,.csv,.tsv"
                 onChange={(e) => { const picked = Array.from(e.target.files ?? []); e.target.value = ""; if (picked.length) attach(picked); }} />   {/* cleared so the same file can be picked again after a refusal */}
          <Button variant="ghost" onClick={() => fileInput.current?.click()} disabled={busy}>📎</Button>
          <Button variant="ghost" test="draft-options-toggle" onClick={() => { setOptsOpen((o) => !o); setSumOpen(false); setTrOpen(false); }}>✎</Button>
          <Button variant="ghost" test="summary-options-toggle" onClick={() => { setSumOpen((o) => !o); setOptsOpen(false); setTrOpen(false); }}>≡</Button>
          <Button variant="ghost" test="translation-options-toggle" onClick={() => { setTrOpen((o) => !o); setOptsOpen(false); setSumOpen(false); }}>⇄</Button>
          {msgs.length > 0 && <Button variant="ghost" onClick={newChat} disabled={busy}>{l.newChat}</Button>}
          <textarea value={q} onChange={(e) => setQ(e.target.value)} placeholder={l.ask} dir="auto" rows={1}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }}
                    className="flex-1 resize-none rounded-2xl border border-line px-4 py-2 text-sm" />
          <Button type="submit" disabled={busy || !q.trim()}>{l.send}</Button>
        </form>
      </section>

      {shown && (
        <Modal title={`${shown.label} · ${shown.file}${shown.where ? ` · ${shown.where}` : ""}`} onClose={() => setShown(null)}>
          <div data-test="source-panel" className="space-y-3 text-sm">
            {shown.heading && <div className="text-xs text-ink-soft" dir="auto">{l.under}: <b>{shown.heading}</b></div>}
            <Block accent={shown.status === "check" ? "orange" : "green"}>
              {MARK[shown.status]} {shown.status === "check" && (shown.wrong_page?.length ?? 0) > 0 ? l.wrongPage(shown.wrong_page!.join(", "), shown.page) : l.status[shown.status]}
              {(shown.status === "check" || shown.status === "nearby") && shown.missing.length > 0 && `: ${shown.missing.map((f) => (shown.elsewhere?.[f]?.length ? `${f} (${l.foundIn} ${shown.elsewhere[f].join(", ")})` : f)).join(", ")}`}
            </Block>
            {shown.snippet && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase text-ink-soft">{l.closest}</div>
                <div dir="auto" className="rounded-lg bg-accent/20 px-3 py-2 text-ink">{shown.snippet}</div>
              </div>
            )}
            <div>
              <div className="mb-1 text-xs font-semibold uppercase text-ink-soft">{l.passage}</div>
              <div className="max-h-72 overflow-auto rounded-lg border border-line px-3 py-2"><Md text={shown.text} /></div>
            </div>
            {shown.page_image && shown.file_id && (showPage
              ? <img data-test="source-page" src={`/api/d6/file/${shown.file_id}/page/${shown.page}`} alt={shown.where} className="w-full rounded-lg border border-line" />
              : <Button variant="ghost" test="show-page" onClick={() => setShowPage(true)}>{l.showPage(shown.where || shown.file)}</Button>)}
          </div>
        </Modal>
      )}
      <Panel title={l.panel} banner={l.banner}>
        {lastRoute && (
          <Block label={l.lastRoute} accent={lastRoute.route.fallback ? "orange" : "green"}>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-ink-soft">{l.task}</dt><dd className="font-semibold">{lastRoute.route.task}</dd>
              <dt className="text-ink-soft">{l.lang}</dt><dd>{lastRoute.route.lang === "ar" ? "العربية" : "English"}</dd>
              <dt className="text-ink-soft">{l.model}</dt><dd className="font-semibold">{MODELS[lastRoute.route.alias]}</dd>
              <dt className="text-ink-soft">{l.why}</dt><dd>{lastRoute.route.reason}</dd>
              <dt className="text-ink-soft">{l.how}</dt><dd>{lastRoute.route.how}</dd>
            </dl>
            {lastRoute.route.fallback && <p className="mt-2 text-xs font-semibold text-ink">{l.fallback}</p>}
          </Block>
        )}
        <div className="text-xs font-semibold uppercase text-ink-soft">{l.table}</div>
        <table className="text-sm">
          <tbody>
            {TABLE.map(([key, name, alias]) => (
              <tr key={key} className={`border-t border-line ${lastRoute?.route.task === key ? "bg-accent/15 font-semibold" : ""}`}>
                <td className="py-1.5">{name}</td>
                <td className="py-1.5 text-end">{MODELS[alias]}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <details className="text-xs">
          <summary className="cursor-pointer font-semibold text-brand">{l.dataiku}</summary>
          <p className="mt-1">LLM Mesh → Custom OpenAI-compatible connection:</p>
          <pre dir="ltr" className="mt-1 rounded bg-ink p-2 text-white">{`Base URL: http://<gb10>:8200/v1\nModel:    auto\nAPI key:  D6_API_KEY from .env`}</pre>
        </details>
      </Panel>
    </div>
  );
}
