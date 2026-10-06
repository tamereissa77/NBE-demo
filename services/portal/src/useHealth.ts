import { useEffect, useState } from "react";

export type HealthState = "loading" | "ok" | "degraded" | "down";

export interface Health {
  state: HealthState;
  body?: unknown;
  info?: unknown;
}

// Polls /api/<demo>/health (and /info once) through the gateway.
export function useHealth(demoId: string, withInfo = false, intervalMs = 10_000): Health {
  const [health, setHealth] = useState<Health>({ state: "loading" });

  useEffect(() => {
    let alive = true;
    let info: unknown;

    const poll = async () => {
      try {
        if (withInfo && info === undefined) {
          info = await fetch(`/api/${demoId}/info`).then((r) => (r.ok ? r.json() : undefined));
        }
        const r = await fetch(`/api/${demoId}/health`);
        const body = await r.json();
        if (alive) setHealth({ state: body.status === "ok" ? "ok" : "degraded", body, info });
      } catch {
        if (alive) setHealth({ state: "down", info });
      }
    };

    poll();
    const timer = setInterval(poll, intervalMs);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [demoId, withInfo, intervalMs]);

  return health;
}
