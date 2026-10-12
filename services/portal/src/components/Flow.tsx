// `active` is the index of the step a running demo has reached: earlier steps show as done, later ones are dimmed.
// Without it (idle, or a demo that does not report progress) every step is shown the same.
export function Flow({ steps, active = null }: { steps: string[]; active?: number | null }) {
  const tone = (i: number) =>
    active === null || i < active ? "bg-brand text-white" : i === active ? "animate-pulse bg-accent text-ink" : "bg-brand/35 text-white";
  return (
    <ol className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-stretch">
      {steps.map((step, i) => (
        <li key={step} className="flex items-center gap-2 sm:flex-1" aria-current={i === active ? "step" : undefined}>
          <span data-test="flow-step" data-state={active === null ? "idle" : i < active ? "done" : i === active ? "active" : "pending"}
                className={`flex min-h-14 flex-1 items-center justify-center rounded-lg px-3 py-2 text-center text-sm font-semibold transition-colors ${tone(i)}`}>
            {active !== null && i < active && <span aria-hidden className="me-1.5">✓</span>}
            {step}
          </span>
          {i < steps.length - 1 && (
            <span aria-hidden className="hidden text-xl font-bold text-accent sm:inline rtl:-scale-x-100">
              →
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
