import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON, type TraceStep } from "../api";
import { Md } from "../components/Md";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Modal, Panel, Spinner } from "./common";

interface Citation { label: string; file: string; title: string; version: number; lang: string; effective: string; section: string; text: string; cited: boolean }
interface Delta { title: string; from: { version: number; effective: string }; to: { version: number; effective: string }; summary: string; sections: { section: string; before: string; after: string }[] }
interface Answer { answer: string; citations: Citation[]; delta: Delta | null; found: boolean; trace: TraceStep[]; total_ms: number }
interface Turn { q: string; a?: Answer; error?: string }

const L = {
  en: { ask: "Ask about a procedure…", send: "Ask", card: "Branch answer card", sources: "Sources", delta: "Version delta: what changed",
        none: "Ask a question to see the sources and what changed.", banner: "Every answer carries source citations", open: "Open",
        thinking: "Searching procedures and writing a cited answer…", notFound: "Not in the documents: the assistant does not guess.", sections: "Changed sections" },
  ar: { ask: "اسأل عن إجراء…", send: "اسأل", card: "بطاقة إجابة الفرع", sources: "المصادر", delta: "الفرق بين الإصدارات: ما الذي تغيّر",
        none: "اطرح سؤالاً لتظهر المصادر وما تغيّر.", banner: "كل إجابة موثّقة بمصادرها", open: "فتح",
        thinking: "جارٍ البحث في الإجراءات وكتابة إجابة موثّقة…", notFound: "غير موجود في المستندات: المساعد لا يخمّن.", sections: "الأقسام المتغيرة" },
};

export default function D2Chat({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggested, setSuggested] = useState<{ lang: string; q: string }[]>([]);
  const [viewer, setViewer] = useState<{ title: string; text: string; section: string } | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const last = [...turns].reverse().find((t) => t.a)?.a;

  useEffect(() => {
    getJSON<{ lang: string; q: string }[]>("/api/d2/suggested").then(setSuggested).catch(() => {});
  }, []);
  // Braces matter: newer Chrome returns a Promise from scrollIntoView, which React would call as a cleanup function
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [turns, busy]);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setQ("");
    setBusy(true);
    const history = turns.filter((t) => t.a).slice(-2).flatMap((t) => [{ role: "user", content: t.q }, { role: "assistant", content: t.a!.answer }]);
    setTurns((ts) => [...ts, { q: question }]);
    try {
      const a = await postJSON<Answer>("/api/d2/ask", { question, history });
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
  const cite = (a: Answer) => (label: string) => {
    const c = a.citations.find((x) => x.label === label);
    if (c) openCitation(c);
  };

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <section className="flex min-h-[32rem] flex-col rounded-xl border border-nbe-border bg-white lg:col-span-2">
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {turns.length === 0 && (
            <div className="flex flex-wrap gap-2">
              {suggested.map((s) => (
                <button key={s.q} data-test="suggested" onClick={() => ask(s.q)} dir="auto" className="rounded-full bg-nbe-bg px-3 py-1.5 text-sm text-nbe-strong hover:bg-nbe-orange/20">
                  {s.q}
                </button>
              ))}
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className="space-y-2">
              <div dir="auto" className="ms-auto w-fit max-w-[85%] rounded-2xl bg-nbe-green px-4 py-2 text-sm text-white">{t.q}</div>
              {t.a && (
                <div data-test="answer" className="max-w-[92%] rounded-2xl bg-nbe-bg px-4 py-3">
                  <Md text={t.a.answer} onCite={cite(t.a)} />
                  <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                    {!t.a.found && <Chip tone="orange">{l.notFound}</Chip>}
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
        <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex gap-2 border-t border-nbe-border p-3">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={l.ask} dir="auto"
                 className="flex-1 rounded-full border border-nbe-border px-4 py-2 text-sm" />
          <Button type="submit" disabled={busy || !q.trim()}>{l.send}</Button>
        </form>
      </section>

      <Panel title={l.card} banner={l.banner}>
        {!last && <p className="text-sm">{l.none}</p>}
        {last && !last.found && <Block accent="orange">{l.notFound}</Block>}
        {last && last.found && (
          <>
            <div className="text-xs font-semibold uppercase text-nbe-text">{l.sources}</div>
            {last.citations.filter((c) => c.cited).concat(last.citations.filter((c) => !c.cited)).slice(0, 4).map((c) => (
              <button key={c.label} onClick={() => openCitation(c)} className={`text-start ${c.cited ? "" : "opacity-60"}`}>
                <Block accent={c.cited ? "green" : "orange"}>
                  <div className="mb-1 flex flex-wrap items-center gap-1.5">
                    <Chip tone="orange">{c.label}</Chip>
                    <Chip tone={c.version === 2 ? "green" : "neutral"}>v{c.version} · {c.effective}</Chip>
                    {c.lang === "en" && <Chip>EN</Chip>}
                  </div>
                  <div dir="auto" className="font-semibold">{c.title}</div>
                  <div dir="auto" className="text-xs text-nbe-text">{c.section}</div>
                </Block>
              </button>
            ))}
            {last.delta && (
              <Block label={l.delta} accent="orange">
                <div className="mb-1 text-xs" dir="auto">
                  {last.delta.title}: v{last.delta.from.version} ({last.delta.from.effective}) → v{last.delta.to.version} ({last.delta.to.effective})
                </div>
                <Md text={last.delta.summary} />
                {last.delta.sections.length > 0 && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs font-semibold text-nbe-green">{l.sections} ({last.delta.sections.length})</summary>
                    {last.delta.sections.map((s) => (
                      <div key={s.section} className="mt-2 grid gap-1 text-xs">
                        <div className="font-semibold" dir="auto">{s.section}</div>
                        <div dir="auto" className="rounded bg-status-stop/5 p-2 line-through decoration-status-stop/40">{s.before.slice(0, 400)}</div>
                        <div dir="auto" className="rounded bg-nbe-green/5 p-2">{s.after.slice(0, 400)}</div>
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
