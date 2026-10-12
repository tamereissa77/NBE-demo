import type { Tone } from "../demos";

const BANNER: Record<Tone, string> = {
  ok: "bg-brand text-white",
  review: "bg-status-review text-ink",
  stop: "bg-status-stop text-white",
};

export function DecisionCard({ title, items, banner, tone }: { title: string; items: string[]; banner: string; tone: Tone }) {
  return (
    <section className="flex h-full flex-col rounded-xl border border-line bg-white p-5">
      <h3 className="mb-4 text-sm font-bold uppercase tracking-wide text-ink-soft">{title}</h3>
      <ul className="flex flex-1 flex-col gap-3">
        {items.map((item) => (
          <li key={item} className="rounded-lg border border-line border-s-4 border-s-brand bg-canvas px-4 py-3 text-sm text-ink">
            {item}
          </li>
        ))}
      </ul>
      <div className={`mt-4 rounded-lg px-4 py-3 text-center text-sm font-bold ${BANNER[tone]}`}>{banner}</div>
    </section>
  );
}
