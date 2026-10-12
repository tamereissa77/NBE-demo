import { Link } from "react-router-dom";
import { OFF_GB10, useI18n } from "../i18n";

export function Header() {
  const { t, toggle } = useI18n();
  return (
    <header className="sticky top-0 z-20 bg-white shadow-sm">
      <div className="mx-auto flex h-20 max-w-7xl items-center justify-between gap-4 px-4">
        <Link to="/" aria-label={t.allDemos} className="shrink-0">
          <img src="/nbe-logo-web.png" alt="National Bank of Egypt" className="h-10 w-auto sm:h-12" />
        </Link>
        <div className="flex items-center gap-3">
          <span className="hidden rounded-full border border-nbe-green px-3 py-1 text-xs font-semibold text-nbe-green md:inline">
            {OFF_GB10 ? t.pocDev : t.poc}
          </span>
          <button
            onClick={toggle}
            className="rounded-full px-3 py-1 text-base font-semibold text-nbe-green hover:bg-nbe-bg"
          >
            {t.switchLang}
          </button>
        </div>
      </div>
      <div className="nbe-rule" />
    </header>
  );
}
