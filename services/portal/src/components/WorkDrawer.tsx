import { useI18n } from "../i18n";
import type { Health } from "../useHealth";

export function WorkDrawer({ health }: { health: Health }) {
  const { t } = useI18n();
  return (
    <details className="group rounded-xl border border-nbe-border bg-white">
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 font-semibold text-nbe-green">
        {t.showWork}
        <span aria-hidden className="transition group-open:rotate-180">▾</span>
      </summary>
      <div className="border-t border-nbe-border px-5 py-4">
        <p className="mb-3 text-sm">{t.showWorkHint}</p>
        <pre dir="ltr" className="overflow-x-auto rounded-lg bg-nbe-strong p-4 text-xs leading-relaxed text-white">
          {JSON.stringify({ health: health.body ?? health.state, info: health.info }, null, 2)}
        </pre>
      </div>
    </details>
  );
}
