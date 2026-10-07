import { Link } from "react-router-dom";
import { StatusDot } from "../components/StatusDot";
import { DEMOS, type Demo } from "../demos";
import { useI18n } from "../i18n";
import { useHealth } from "../useHealth";

function DemoCard({ demo }: { demo: Demo }) {
  const { lang, t } = useI18n();
  const health = useHealth(demo.id);
  return (
    <article className="flex flex-col rounded-xl border border-line bg-white p-5 transition hover:-translate-y-0.5 hover:shadow-lg">
      <div className="mb-3 flex items-center justify-between">
        <span className="rounded-md bg-brand px-2.5 py-1 text-sm font-bold text-white">{demo.code}</span>
        <StatusDot state={health.state} />
      </div>
      <h2 className="mb-1 text-lg font-bold leading-snug text-brand">{demo.title[lang]}</h2>
      <p className="mb-4 flex-1 text-sm">{demo.tagline[lang]}</p>
      <div className="mb-4 flex flex-wrap gap-2 text-xs">
        <span className="rounded-full bg-canvas px-2.5 py-1 font-semibold">
          {t.wave} {demo.wave}
        </span>
        <span className="rounded-full bg-canvas px-2.5 py-1">
          {t.fit}: {demo.fit[lang]}
        </span>
      </div>
      <Link
        to={`/${demo.id}`}
        className="self-start rounded-full bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
      >
        {t.openDemo}
      </Link>
    </article>
  );
}

export function Home() {
  const { t } = useI18n();
  return (
    <>
      <section className="bg-brand text-white">
        <div className="mx-auto max-w-7xl px-4 py-12 sm:py-16">
          <h1 className="max-w-3xl text-3xl font-bold leading-tight sm:text-4xl">{t.heroTitle}</h1>
          <p className="mt-4 max-w-2xl text-lg opacity-90">{t.heroSub}</p>
          <div className="mt-6 flex flex-wrap gap-2 text-sm font-semibold">
            {[t.poc, t.offline, t.synthetic].map((label) => (
              <span key={label} className="rounded-full bg-accent px-3 py-1 text-ink">
                {label}
              </span>
            ))}
          </div>
        </div>
      </section>
      <div className="brand-rule" />
      <section className="mx-auto max-w-7xl px-4 py-10">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {DEMOS.map((demo) => (
            <DemoCard key={demo.id} demo={demo} />
          ))}
        </div>
      </section>
    </>
  );
}
