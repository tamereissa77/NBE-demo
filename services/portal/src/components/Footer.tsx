import { useI18n } from "../i18n";

export function Footer() {
  const { t } = useI18n();
  return (
    <footer className="mt-16 bg-nbe-green-dark text-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-6 text-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-x-4 gap-y-1 opacity-90">
          <span>{t.poc}</span>
          <span aria-hidden className="hidden sm:inline">·</span>
          <span>{t.offline}</span>
          <span aria-hidden className="hidden sm:inline">·</span>
          <span>{t.synthetic}</span>
        </div>
        <div className="font-semibold text-nbe-gold">{t.poweredBy}</div>
      </div>
    </footer>
  );
}
