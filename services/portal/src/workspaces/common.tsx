import type { ReactNode } from "react";
import type { Tone } from "../demos";

const BANNER: Record<Tone, string> = {
  ok: "bg-brand text-white",
  review: "bg-status-review text-ink",
  stop: "bg-status-stop text-white",
};

// Right-hand decision card from the deck, filled with live results.
export function Panel({ title, banner, tone = "ok", children }: { title: string; banner?: string; tone?: Tone; children: ReactNode }) {
  return (
    <section className="flex h-full flex-col rounded-xl border border-line bg-white p-5">
      <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-ink-soft">{title}</h3>
      <div className="flex flex-1 flex-col gap-3">{children}</div>
      {banner && <div className={`mt-4 rounded-lg px-4 py-3 text-center text-sm font-bold ${BANNER[tone]}`}>{banner}</div>}
    </section>
  );
}

export function Block({ label, children, accent = "green" }: { label?: string; children: ReactNode; accent?: "green" | "orange" | "red" }) {
  const border = { green: "border-s-brand", orange: "border-s-accent", red: "border-s-status-stop" }[accent];
  return (
    <div className={`rounded-lg border border-line border-s-4 ${border} bg-canvas px-4 py-3 text-sm text-ink`}>
      {label && <div className="mb-1 text-xs font-semibold uppercase text-ink-soft">{label}</div>}
      {children}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-soft">
      <span className="size-4 animate-spin rounded-full border-2 border-line border-t-brand" />
      {label}
    </div>
  );
}

export function Chip({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "green" | "orange" | "red" }) {
  const cls = {
    neutral: "bg-canvas text-ink-soft",
    green: "bg-brand/10 text-brand",
    orange: "bg-accent/20 text-ink",
    red: "bg-status-stop/10 text-status-stop",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>{children}</span>;
}

export function ErrorNote({ error }: { error: string }) {
  return error ? <p className="rounded-lg bg-status-stop/10 p-3 text-sm text-status-stop">{error}</p> : null;
}

export const Button = ({ children, onClick, disabled, variant = "primary", type = "button", test }:
  { children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: "primary" | "ghost" | "danger"; type?: "button" | "submit"; test?: string }) => (
  <button
    type={type}
    data-test={test}
    onClick={onClick}
    disabled={disabled}
    className={`rounded-full px-4 py-2 text-sm font-semibold disabled:opacity-40 ${
      variant === "primary" ? "bg-brand text-white hover:bg-brand-dark" : variant === "danger" ? "bg-status-stop text-white" : "bg-white text-brand ring-1 ring-line hover:bg-canvas"
    }`}
  >
    {children}
  </button>
);

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white p-6" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between gap-4">
          <h3 className="font-bold text-brand" dir="auto">{title}</h3>
          <button onClick={onClose} className="text-2xl leading-none text-ink-soft" aria-label="Close">×</button>
        </div>
        {children}
      </div>
    </div>
  );
}
