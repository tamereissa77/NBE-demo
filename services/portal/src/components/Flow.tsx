export function Flow({ steps }: { steps: string[] }) {
  return (
    <ol className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-stretch">
      {steps.map((step, i) => (
        <li key={step} className="flex items-center gap-2 sm:flex-1">
          <span className="flex min-h-14 flex-1 items-center justify-center rounded-lg bg-nbe-green px-3 py-2 text-center text-sm font-semibold text-white">
            {step}
          </span>
          {i < steps.length - 1 && (
            <span aria-hidden className="hidden text-xl font-bold text-nbe-orange sm:inline rtl:-scale-x-100">
              →
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
