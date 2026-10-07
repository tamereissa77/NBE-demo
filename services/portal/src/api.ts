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

export const getJSON = <T,>(url: string) => fetch(url).then((r) => handle<T>(r));

export const postJSON = <T,>(url: string, body: unknown = {}) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => handle<T>(r));

export const upload = <T,>(url: string, file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return fetch(url, { method: "POST", body: fd }).then((r) => handle<T>(r));
};

export interface TraceStep {
  kind: string;
  label: string;
  detail: unknown;
  ms: number | null;
  at_ms: number;
}
