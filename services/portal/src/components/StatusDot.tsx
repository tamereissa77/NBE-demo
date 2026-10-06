import { useI18n } from "../i18n";
import type { HealthState } from "../useHealth";

const COLOR: Record<HealthState, string> = {
  ok: "bg-nbe-green",
  degraded: "bg-status-review",
  down: "bg-status-stop",
  loading: "bg-nbe-border",
};

export function StatusDot({ state }: { state: HealthState }) {
  const { t } = useI18n();
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-nbe-text">
      <span className={`size-2.5 rounded-full ${COLOR[state]} ${state === "ok" ? "animate-pulse" : ""}`} />
      {t.status[state]}
    </span>
  );
}
