import { Link, Navigate, useParams } from "react-router-dom";
import { DecisionCard } from "../components/DecisionCard";
import { Flow } from "../components/Flow";
import { StatusDot } from "../components/StatusDot";
import { WorkDrawer } from "../components/WorkDrawer";
import { demoById } from "../demos";
import { useI18n } from "../i18n";
import { useHealth } from "../useHealth";

export function DemoPage() {
  const { demoId } = useParams();
  const demo = demoById(demoId);
  if (!demo) return <Navigate to="/" replace />;
  return <DemoView key={demo.id} id={demo.id} />;
}

function DemoView({ id }: { id: string }) {
  const demo = demoById(id)!;
  const { lang, t } = useI18n();
  const health = useHealth(demo.id, true);

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <Link to="/" className="text-sm font-semibold text-nbe-green hover:underline">
        <span aria-hidden className="inline-block rtl:-scale-x-100">←</span> {t.back}
      </Link>

      <header className="mt-4 mb-6 flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-md bg-nbe-green px-2.5 py-1 text-sm font-bold text-white">{demo.code}</span>
          <h1 className="text-2xl font-bold text-nbe-green sm:text-3xl">{demo.title[lang]}</h1>
          <StatusDot state={health.state} />
        </div>
        <p className="text-base">{demo.tagline[lang]}</p>
        <p className="text-xs">
          {t.wave} {demo.wave} · {t.effort}: {demo.effortDays} {t.days} · {t.fit}: {demo.fit[lang]}
        </p>
      </header>

      <Flow steps={demo.flow[lang]} />

      <div className="mt-6 grid gap-5 lg:grid-cols-3">
        <div className="flex flex-col gap-5 lg:col-span-2">
          <section className="rounded-xl border border-nbe-border bg-white p-5">
            <h2 className="mb-2 font-bold text-nbe-green">{t.story}</h2>
            <p className="leading-relaxed text-nbe-strong">{demo.story[lang]}</p>
          </section>
          <section className="flex min-h-64 flex-1 flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed border-nbe-border bg-white p-8 text-center">
            <img src="/nbe-mark.png" alt="" className="h-16 w-auto opacity-80" />
            <h2 className="font-bold text-nbe-green">{t.workspace}</h2>
            <p className="max-w-md text-sm">{t.workspacePending.replace("{wave}", String(demo.wave))}</p>
          </section>
        </div>
        <DecisionCard title={demo.cardTitle[lang]} items={demo.cardItems[lang]} banner={demo.banner[lang]} tone={demo.bannerTone} />
      </div>

      <div className="mt-6">
        <WorkDrawer health={health} />
      </div>
    </div>
  );
}
