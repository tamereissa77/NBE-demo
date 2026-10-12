import { useState } from "react";
import type { TraceStep } from "../api";
import { useI18n } from "../i18n";
import type { Health } from "../useHealth";

const ICON: Record<string, string> = {
  llm: "🧠", retrieval: "🔎", guardrail: "🛡️", tool: "🔧", rules: "📏", route: "🧭", chunk: "✂️", cache: "♻️", ingest: "📥",
  forensics: "🔬", asr: "🎙️", tts: "🔊", image: "🖼️", sql: "🗄️",
};

// "Show the work": every step behind the last response, with timings, plus live service health.
export function TraceDrawer({ trace, health }: { trace: TraceStep[]; health: Health }) {
  const { t } = useI18n();
  const [open, setOpen] = useState<number | null>(null);
  const total = trace.length ? Math.max(...trace.map((s) => s.at_ms + (s.ms ?? 0))) : 0;
  return (
    <details className="group rounded-xl border border-line bg-white" open={trace.length > 0 ? undefined : false}>
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 font-semibold text-brand">
        <span>
          {t.showWork}
          {trace.length > 0 && <span className="ms-2 text-xs font-normal text-ink-soft">· {trace.length} steps · {(total / 1000).toFixed(1)} s</span>}
        </span>
        <span aria-hidden className="transition group-open:rotate-180">▾</span>
      </summary>
      <div className="border-t border-line px-5 py-4">
        {trace.length === 0 ? (
          <p className="text-sm">{t.showWorkHint}</p>
        ) : (
          <ol className="space-y-1">
            {trace.map((s, i) => (
              <li key={i} className="rounded-lg bg-canvas">
                <button onClick={() => setOpen(open === i ? null : i)} className="flex w-full items-center gap-2 px-3 py-2 text-start text-sm">
                  <span aria-hidden>{ICON[s.kind] ?? "•"}</span>
                  <span className="flex-1 text-ink" dir="auto">
                    {s.label}
                  </span>
                  {s.ms !== null && <span className="text-xs tabular-nums text-ink-soft">{s.ms} ms</span>}
                </button>
                {open === i && s.detail !== null && s.detail !== undefined && (
                  <pre dir="ltr" className="mx-3 mb-2 max-h-72 overflow-auto rounded-md bg-ink p-3 text-xs text-white">
                    {JSON.stringify(s.detail, null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ol>
        )}
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-ink-soft">Service health</summary>
          <pre dir="ltr" className="mt-2 overflow-x-auto rounded-md bg-ink p-3 text-white">
            {JSON.stringify({ health: health.body ?? health.state, info: health.info }, null, 2)}
          </pre>
        </details>
      </div>
    </details>
  );
}
