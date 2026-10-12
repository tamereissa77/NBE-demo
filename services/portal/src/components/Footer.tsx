import { Link } from "react-router-dom";
import { OFF_GB10, useI18n } from "../i18n";

export function Footer() {
  const { t } = useI18n();
  return (
    <footer className="mt-16 bg-brand-dark text-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-6 text-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-x-4 gap-y-1 opacity-90">
          <span>{OFF_GB10 ? t.pocDev : t.poc}</span>
          <span aria-hidden className="hidden sm:inline">·</span>
          {!OFF_GB10 && (
            <>
              <span>{t.offline}</span>
              <span aria-hidden className="hidden sm:inline">·</span>
            </>
          )}
          <span>{t.synthetic}</span>
        </div>
        <div className="flex items-center gap-4">
          <Link to="/eval" className="opacity-70 hover:opacity-100 hover:underline">
            Arabic gate
          </Link>
          {!OFF_GB10 && <span className="font-semibold text-accent-light">{t.poweredBy}</span>}
        </div>
      </div>
    </footer>
  );
}
