import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON, type TraceStep } from "../api";
import { Md } from "../components/Md";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Modal, Panel, Spinner } from "./common";

interface CropRef { id: string; page: number; type: string }
// kind "scan": a passage of a scanned document. `crops` are the OCR blocks it was built from, shown as images of the page.
interface Citation { label: string; kind?: "procedure" | "scan"; file: string; doc_id?: string; title: string; version: number | null; lang: string;
                     effective: string | null; section: string; text: string; page?: number; crops?: CropRef[]; rerank: number | null; cited: boolean }
interface Delta { title: string; from: { version: number; effective: string }; to: { version: number; effective: string }; summary: string; sections: { section: string; before: string; after: string }[] }
// blocked: a guardrail stopped the question or the answer. masked: personal identifiers replaced in the answer by rule.
interface Answer { answer: string; citations: Citation[]; delta: Delta | null; found: boolean; restricted?: boolean; blocked?: boolean; masked?: number;
                   trace: TraceStep[]; total_ms: number }
interface Turn { q: string; role: string; a?: Answer; error?: string }
interface Role { id: string; ar: string; en: string; scope_ar: string; scope_en: string }

const L = {
  en: { ask: "Ask about a procedure…", send: "Ask", card: "Branch answer card", sources: "Sources", delta: "Version delta: what changed",
        none: "Ask a question to see the sources and what changed.", banner: "Every answer carries source citations", open: "Open",
        thinking: "Searching procedures and writing a cited answer…", notFound: "Not in the documents: the assistant does not guess.", sections: "Changed sections",
        role: "Asking as", page: "p.", relevance: "Relevance", high: "high", medium: "medium", low: "low", viewImage: "Scanned image", viewText: "Text",
        openOriginal: "Open the original image", imgError: "The image could not be loaded", noImage: "No image for this passage.",
        restricted: "Outside this role's access", blocked: "Stopped by the guardrail", masked: "Personal identifiers masked" },
  ar: { ask: "اسأل عن إجراء…", send: "اسأل", card: "بطاقة إجابة الفرع", sources: "المصادر", delta: "الفرق بين الإصدارات: ما الذي تغيّر",
        none: "اطرح سؤالاً لتظهر المصادر وما تغيّر.", banner: "كل إجابة موثّقة بمصادرها", open: "فتح",
        thinking: "جارٍ البحث في الإجراءات وكتابة إجابة موثّقة…", notFound: "غير موجود في المستندات: المساعد لا يخمّن.", sections: "الأقسام المتغيرة",
        role: "السؤال بصفة", page: "ص", relevance: "ملاءمة", high: "عالية", medium: "متوسطة", low: "منخفضة", viewImage: "عرض الصورة", viewText: "عرض النص",
        openOriginal: "عرض الصورة الأصلية", imgError: "تعذّر تحميل الصورة", noImage: "لا توجد صورة لهذا المقتطف.",
        restricted: "خارج صلاحيات هذا الدور", blocked: "أوقفه حاجز الحماية", masked: "تم حجب بيانات شخصية" },
};

// The role is part of the URL because the service checks it again before serving a crop
const cropUrl = (c: Citation, b: CropRef, role: string) => `/api/d2/crop/${c.doc_id}/${b.id}?role=${role}`;
// Bands for bge-reranker-v2-m3 scores (0 to 1). Provisional until calibrated on a scanned-corpus golden set.
const relevance = (score: number | null) => (score == null ? null : score >= 0.5 ? "high" : score >= 0.1 ? "medium" : "low");
const preview = (text: string) => text.replace(/[|#*-]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 90) + "…";

function CropImage({ src, alt, errorLabel }: { src: string; alt: string; errorLabel: string }) {
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  if (state === "error") return <div className="rounded-lg bg-status-stop/10 p-3 text-center text-xs text-status-stop">{errorLabel}</div>;
  return (
    <a href={src} target="_blank" rel="noopener noreferrer" className="block">
      {state === "loading" && <div className="h-16 animate-pulse rounded-lg bg-canvas" />}
      <img src={src} alt={alt} onLoad={() => setState("ok")} onError={() => setState("error")}
           className={`mx-auto max-w-full rounded-lg border border-line bg-white ${state === "ok" ? "" : "hidden"}`} />
    </a>
  );
}

export default function D2Chat({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggested, setSuggested] = useState<{ lang: string; q: string }[]>([]);
  const [viewer, setViewer] = useState<{ title: string; text: string; section: string } | null>(null);
  // Roles exist only when the scanned corpus is installed; without it the screen is the procedures-only D2
  const [roles, setRoles] = useState<Role[]>([]);
  const [role, setRole] = useState("manager");
  // Which answer's sources the card shows (default: the latest) and which scanned source is open in it
  const [focus, setFocus] = useState<{ turn: number; label: string } | null>(null);
  const [view, setView] = useState<"image" | "text">("image");
  const end = useRef<HTMLDivElement>(null);
  const shownIdx = focus?.turn ?? turns.reduce((acc, t, i) => (t.a ? i : acc), -1);
  const shown = shownIdx >= 0 ? turns[shownIdx] : undefined;
  const last = shown?.a;
  const scans = last?.citations.filter((c) => c.kind === "scan") ?? [];
  const active = scans.find((c) => c.label === focus?.label) ?? scans.find((c) => c.cited) ?? scans[0];

  useEffect(() => {
    getJSON<{ lang: string; q: string }[]>("/api/d2/suggested").then(setSuggested).catch(() => {});
    getJSON<{ roles: Role[]; default_role: string }>("/api/d2/corpus").then((c) => { setRoles(c.roles); setRole(c.default_role); }).catch(() => {});
  }, []);
  // Braces matter: newer Chrome returns a Promise from scrollIntoView, which React would call as a cleanup function
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [turns, busy]);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setQ("");
    setBusy(true);
    setFocus(null);
    const history = turns.filter((t) => t.a).slice(-2).flatMap((t) => [{ role: "user", content: t.q }, { role: "assistant", content: t.a!.answer }]);
    setTurns((ts) => [...ts, { q: question, role }]);
    try {
      const a = await postJSON<Answer>("/api/d2/ask", { question, history, role });
      setTurns((ts) => ts.map((t, i) => (i === ts.length - 1 ? { ...t, a } : t)));
      onTrace(a.trace);
    } catch (e) {
      setTurns((ts) => ts.map((t, i) => (i === ts.length - 1 ? { ...t, error: (e as Error).message } : t)));
    } finally {
      setBusy(false);
    }
  };

  const openCitation = async (c: Citation) => {
    const d = await getJSON<{ title: string; text: string }>(`/api/d2/doc/${c.file}`);
    setViewer({ title: `${d.title} · v${c.version} · ${c.effective}`, text: d.text, section: c.section });
  };
  // A scanned source opens in the card with its crop images; a procedure opens as Markdown, as before
  const open = (turn: number, c: Citation) => {
    if (c.kind !== "scan") return void openCitation(c);
    setFocus({ turn, label: c.label });
    setView("image");
  };
  const cite = (turn: number, a: Answer) => (label: string) => {
    const c = a.citations.find((x) => x.label === label);
    if (c) open(turn, c);
  };

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <section className="flex min-h-[32rem] flex-col rounded-xl border border-line bg-white lg:col-span-2">
        {roles.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-2.5 text-xs">
            <span className="font-semibold text-ink-soft">{l.role}</span>
            {roles.map((r) => (
              <button key={r.id} data-test={`role-${r.id}`} onClick={() => setRole(r.id)}
                      className={`rounded-full px-3 py-1 font-semibold ${role === r.id ? "bg-brand text-white" : "bg-canvas text-ink hover:bg-accent/20"}`}>
                {lang === "ar" ? r.ar : r.en}
              </button>
            ))}
            <span className="text-ink-soft">{roles.filter((r) => r.id === role).map((r) => (lang === "ar" ? r.scope_ar : r.scope_en))}</span>
          </div>
        )}
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {turns.length === 0 && (
            <div className="flex flex-wrap gap-2">
              {suggested.map((s) => (
                <button key={s.q} data-test="suggested" onClick={() => ask(s.q)} dir="auto" className="rounded-full bg-canvas px-3 py-1.5 text-sm text-ink hover:bg-accent/20">
                  {s.q}
                </button>
              ))}
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className="space-y-2">
              <div dir="auto" className="ms-auto w-fit max-w-[85%] rounded-2xl bg-brand px-4 py-2 text-sm text-white">{t.q}</div>
              {t.a && (
                <div data-test="answer" className="max-w-[92%] rounded-2xl bg-canvas px-4 py-3">
                  <Md text={t.a.answer} onCite={cite(i, t.a)} />
                  {t.a.citations.some((c) => c.kind === "scan") && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {t.a.citations.map((c) => (
                        <button key={c.label} data-test="source-chip" onClick={() => open(i, c)} dir="auto"
                                className={`rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-brand ring-1 ring-line hover:bg-accent/20 ${c.cited ? "" : "opacity-60"}`}>
                          {c.label} · {c.title}{c.kind === "scan" ? ` · ${l.page} ${c.page}` : ""}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                    {t.a.blocked ? <Chip tone="red">{l.blocked}</Chip> : t.a.restricted ? <Chip tone="red">{l.restricted}</Chip> : !t.a.found && <Chip tone="orange">{l.notFound}</Chip>}
                    {!!t.a.masked && <Chip tone="orange">{l.masked}</Chip>}
                    <Chip>{(t.a.total_ms / 1000).toFixed(1)} s</Chip>
                  </div>
                </div>
              )}
              {t.error && <ErrorNote error={t.error} />}
            </div>
          ))}
          {busy && <Spinner label={l.thinking} />}
          <div ref={end} />
        </div>
        <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex gap-2 border-t border-line p-3">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={l.ask} dir="auto"
                 className="flex-1 rounded-full border border-line px-4 py-2 text-sm" />
          <Button type="submit" disabled={busy || !q.trim()}>{l.send}</Button>
        </form>
      </section>

      <Panel title={l.card} banner={l.banner}>
        {!last && <p className="text-sm">{l.none}</p>}
        {last && last.blocked && <Block accent="red">{l.blocked}</Block>}
        {last && last.restricted && <Block accent="red">{l.restricted}</Block>}
        {last && !last.found && !last.restricted && !last.blocked && <Block accent="orange">{l.notFound}</Block>}
        {last && last.found && (
          <>
            <div className="text-xs font-semibold uppercase text-ink-soft">{l.sources}</div>
            {last.citations.filter((c) => c.cited).concat(last.citations.filter((c) => !c.cited)).slice(0, scans.length ? undefined : 4).map((c) => (
              <button key={c.label} onClick={() => open(shownIdx, c)}
                      className={`text-start ${c.cited ? "" : "opacity-60"} ${c.label === active?.label ? "rounded-lg ring-2 ring-brand" : ""}`}>
                <Block accent={c.cited ? "green" : "orange"}>
                  <div className="mb-1 flex flex-wrap items-center gap-1.5">
                    <Chip tone="orange">{c.label}</Chip>
                    {c.kind === "scan" ? (
                      <>
                        <Chip>{l.page} {c.page}</Chip>
                        {relevance(c.rerank) && (
                          <Chip tone={relevance(c.rerank) === "high" ? "green" : relevance(c.rerank) === "medium" ? "orange" : "neutral"}>
                            {l.relevance} {l[relevance(c.rerank)!]}
                          </Chip>
                        )}
                      </>
                    ) : (
                      <Chip tone={c.version === 2 ? "green" : "neutral"}>v{c.version} · {c.effective}</Chip>
                    )}
                    {c.lang === "en" && <Chip>EN</Chip>}
                  </div>
                  <div dir="auto" className="font-semibold">{c.title}</div>
                  <div dir="auto" className="text-xs text-ink-soft">{c.section}</div>
                  {c.kind === "scan" && <div dir="auto" className="mt-1 text-xs text-ink-soft">{preview(c.text)}</div>}
                </Block>
              </button>
            ))}
            {active && shown && (
              <div data-test="citation-detail" className="rounded-lg border border-line p-3">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div dir="auto" className="text-sm font-bold text-brand">{active.title}</div>
                  <Chip>{l.page} {active.page}</Chip>
                </div>
                <div className="mb-2 flex gap-1 rounded-full bg-canvas p-1 text-xs font-semibold">
                  {(["image", "text"] as const).map((m) => (
                    <button key={m} data-test={`view-${m}`} onClick={() => setView(m)}
                            className={`flex-1 rounded-full px-3 py-1 ${view === m ? "bg-white text-brand shadow-sm" : "text-ink-soft"}`}>
                      {m === "image" ? l.viewImage : l.viewText}
                    </button>
                  ))}
                </div>
                {view === "text" ? (
                  <div className="max-h-96 overflow-auto"><Md text={active.text} /></div>
                ) : active.crops?.length ? (
                  <div className="max-h-96 space-y-1.5 overflow-y-auto">
                    {active.crops.map((b) => (
                      <CropImage key={cropUrl(active, b, shown.role)} src={cropUrl(active, b, shown.role)} alt={`${active.title} · ${l.page} ${b.page}`} errorLabel={l.imgError} />
                    ))}
                  </div>
                ) : (
                  <p className="text-xs">{l.noImage}</p>
                )}
                {active.crops?.[0] && (
                  <a href={cropUrl(active, active.crops[0], shown.role)} target="_blank" rel="noopener noreferrer"
                     className="mt-2 inline-block text-xs font-semibold text-brand hover:underline">
                    {l.openOriginal} ↗
                  </a>
                )}
              </div>
            )}
            {last.delta && (
              <Block label={l.delta} accent="orange">
                <div className="mb-1 text-xs" dir="auto">
                  {last.delta.title}: v{last.delta.from.version} ({last.delta.from.effective}) → v{last.delta.to.version} ({last.delta.to.effective})
                </div>
                <Md text={last.delta.summary} />
                {last.delta.sections.length > 0 && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs font-semibold text-brand">{l.sections} ({last.delta.sections.length})</summary>
                    {last.delta.sections.map((s) => (
                      <div key={s.section} className="mt-2 grid gap-1 text-xs">
                        <div className="font-semibold" dir="auto">{s.section}</div>
                        <div dir="auto" className="rounded bg-status-stop/5 p-2 line-through decoration-status-stop/40">{s.before.slice(0, 400)}</div>
                        <div dir="auto" className="rounded bg-brand/5 p-2">{s.after.slice(0, 400)}</div>
                      </div>
                    ))}
                  </details>
                )}
              </Block>
            )}
          </>
        )}
      </Panel>

      {viewer && (
        <Modal title={viewer.title} onClose={() => setViewer(null)}>
          <p className="mb-2 text-xs"><Chip tone="orange">{viewer.section}</Chip></p>
          <Md text={viewer.text.replace(`## ${viewer.section}`, `## ▶ ${viewer.section}`)} />
        </Modal>
      )}
    </div>
  );
}
