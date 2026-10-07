// Small fetch helpers for the demo APIs behind the gateway (/api/<demo>/...).

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

// A network failure (server unreachable, a forwarded port that dropped) surfaces as a bare
// "TypeError: Failed to fetch"; say what it means and what to do instead.
const UNREACHABLE =
  "Cannot reach the demo server on the GB10. If you open the portal through a forwarded port (VS Code or SSH), " +
  "check the port is still forwarded, or open http://<gb10-address>:8200 directly.";

const send = (url: string, init?: RequestInit) =>
  fetch(url, init).catch((e) => {
    throw e instanceof TypeError ? new ApiError(0, UNREACHABLE) : e;
  });

export const getJSON = <T,>(url: string) => send(url).then((r) => handle<T>(r));

export const postJSON = <T,>(url: string, body: unknown = {}) =>
  send(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => handle<T>(r));

export const upload = <T,>(url: string, file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return send(url, { method: "POST", body: fd }).then((r) => handle<T>(r));
};

export interface TraceStep {
  kind: string;
  label: string;
  detail: unknown;
  ms: number | null;
  at_ms: number;
}
