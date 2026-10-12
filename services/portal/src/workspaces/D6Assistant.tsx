import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON, upload, type TraceStep } from "../api";
import { Md } from "../components/Md";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Panel, Spinner } from "./common";

interface Route { lang: string; task: string; alias: string; reason: string; how: string; model?: string; fallback?: boolean }
interface Reply { answer: string; route: Route; meta: { latency_ms: number; tokens_per_s: number; completion_tokens: number }; trace: TraceStep[] }
interface Msg { role: "user" | "assistant"; content: string; reply?: Reply }
interface FileInfo { file_id: string; name: string; chars: number; converted_by: string }

const MODELS: Record<string, string> = { workhorse: "Gemma 4 26B-A4B", hero: "gpt-oss-120b" };
const TABLE: [string, string, string][] = [
  ["file_chat", "File chat & extraction", "workhorse"], ["drafting", "Drafting", "workhorse"], ["summarise", "Summaries", "workhorse"],
  ["translation", "Translation", "workhorse"], ["code", "Code explanation", "hero"], ["general", "General", "workhorse"],
];
const L = {
  en: { ask: "Ask the assistant, or attach a file…", send: "Send", attach: "Attach file", panel: "Model-selection panel", banner: "Router picks the right model per task",
        lastRoute: "Last request", task: "Task", lang: "Language", model: "Model", why: "Why", how: "Decided by", fallback: "Hero model is not running: answered by the workhorse (start it with make hero)",
        table: "Routing table", thinking: "Routing and answering…", file: "File attached", dataiku: "Dataiku LLM Mesh" },
  ar: { ask: "اسأل المساعد أو أرفق ملفاً…", send: "إرسال", attach: "إرفاق ملف", panel: "لوحة اختيار النموذج", banner: "الموجّه يختار النموذج المناسب لكل مهمة",
        lastRoute: "آخر طلب", task: "المهمة", lang: "اللغة", model: "النموذج", why: "السبب", how: "طريقة القرار", fallback: "النموذج الأكبر غير مشغّل: أجاب النموذج الأساسي (شغّله بـ make hero)",
        table: "جدول التوجيه", thinking: "جارٍ التوجيه والإجابة…", file: "ملف مرفق", dataiku: "التكامل مع Dataiku" },
};

export default function D6Assistant({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<FileInfo | null>(null);
  const [suggested, setSuggested] = useState<{ task: string; q: string }[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const lastRoute = [...msgs].reverse().find((m) => m.reply)?.reply;

  useEffect(() => { getJSON<{ task: string; q: string }[]>("/api/d6/suggested").then(setSuggested).catch(() => {}); }, []);
  // Braces matter: newer Chrome returns a Promise from scrollIntoView, which React would call as a cleanup function
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [msgs, busy]);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    setQ(""); setError(""); setBusy(true);
    const next: Msg[] = [...msgs, { role: "user", content: text }];
    setMsgs(next);
    try {
      const reply = await postJSON<Reply>("/api/d6/chat", {
        messages: next.slice(-6).map(({ role, content }) => ({ role, content })), file_id: file?.file_id,
      });
      setMsgs([...next, { role: "assistant", content: reply.answer, reply }]);
      onTrace(reply.trace);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const attach = async (f: File) => {
    setBusy(true); setError("");
    try { setFile(await upload<FileInfo>("/api/d6/upload", f)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <section className="flex min-h-[32rem] flex-col rounded-xl border border-line bg-white lg:col-span-2">
        <div className="flex-1 space-y-3 overflow-y-auto p-5">
          {msgs.length === 0 && (
            <div className="flex flex-wrap gap-2">
              {suggested.map((s) => (
                <button key={s.q} data-test="suggested" onClick={() => send(s.q)} dir="auto" className="max-w-full truncate rounded-full bg-canvas px-3 py-1.5 text-sm text-ink hover:bg-accent/20">
                  <span className="me-1 text-xs text-brand">{s.task}</span>{s.q.split("\n")[0]}
                </button>
              ))}
            </div>
          )}
          {msgs.map((m, i) =>
            m.role === "user" ? (
              <div key={i} dir="auto" className="ms-auto w-fit max-w-[85%] whitespace-pre-wrap rounded-2xl bg-brand px-4 py-2 text-sm text-white">{m.content}</div>
            ) : (
              <div key={i} data-test="answer" className="max-w-[92%] rounded-2xl bg-canvas px-4 py-3">
                <Md text={m.content} />
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
          {busy && <Spinner label={l.thinking} />}
          <ErrorNote error={error} />
          <div ref={end} />
        </div>
        {file && (
          <div className="mx-3 mb-1 flex items-center gap-2 rounded-lg bg-accent/15 px-3 py-1.5 text-xs">
            📎 {l.file}: <b dir="auto">{file.name}</b> · {file.chars.toLocaleString()} chars · {file.converted_by}
            <button onClick={() => setFile(null)} className="ms-auto text-base">×</button>
          </div>
        )}
        <form onSubmit={(e) => { e.preventDefault(); send(q); }} className="flex gap-2 border-t border-line p-3">
          <input ref={fileInput} type="file" className="hidden" accept=".pdf,.docx,.pptx,.html,.md,.txt"
                 onChange={(e) => e.target.files?.[0] && attach(e.target.files[0])} />
          <Button variant="ghost" onClick={() => fileInput.current?.click()} disabled={busy}>📎</Button>
          <textarea value={q} onChange={(e) => setQ(e.target.value)} placeholder={l.ask} dir="auto" rows={1}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }}
                    className="flex-1 resize-none rounded-2xl border border-line px-4 py-2 text-sm" />
          <Button type="submit" disabled={busy || !q.trim()}>{l.send}</Button>
        </form>
      </section>

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
