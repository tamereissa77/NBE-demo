import { useState, type ComponentType } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import type { TraceStep } from "../api";
import { DecisionCard } from "../components/DecisionCard";
import { Flow } from "../components/Flow";
import { StatusDot } from "../components/StatusDot";
import { TraceDrawer } from "../components/TraceDrawer";
import { demoById } from "../demos";
import { useI18n } from "../i18n";
import { useHealth } from "../useHealth";
import { WORKSPACES } from "../workspaces";

export interface WorkspaceProps {
  onTrace: (steps: TraceStep[]) => void;
}

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
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const Workspace: ComponentType<WorkspaceProps> | undefined = WORKSPACES[demo.id];

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <Link to="/" className="text-sm font-semibold text-nbe-green hover:underline">
        <span aria-hidden className="inline-block rtl:-scale-x-100">←</span> {t.back}
      </Link>

      <header className="mt-3 mb-4 flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-md bg-nbe-green px-2.5 py-1 text-sm font-bold text-white">{demo.code}</span>
          <h1 className="text-2xl font-bold text-nbe-green sm:text-3xl">{demo.title[lang]}</h1>
          <StatusDot state={health.state} />
        </div>
        <p className="text-base">{demo.tagline[lang]}</p>
      </header>

      <Flow steps={demo.flow[lang]} />

      <details className="mt-4 rounded-xl border border-nbe-border bg-white px-5 py-3">
        <summary className="cursor-pointer font-bold text-nbe-green">{t.story}</summary>
        <p className="mt-2 leading-relaxed text-nbe-strong">{demo.story[lang]}</p>
        <p className="mt-2 text-xs">
          {t.wave} {demo.wave} · {t.effort}: {demo.effortDays} {t.days} · {t.fit}: {demo.fit[lang]}
        </p>
      </details>

      <div className="mt-5">
        {Workspace ? (
          <Workspace onTrace={setTrace} />
        ) : (
          <div className="grid gap-5 lg:grid-cols-3">
            <section className="flex min-h-64 flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed border-nbe-border bg-white p-8 text-center lg:col-span-2">
              <img src="/nbe-mark.png" alt="" className="h-16 w-auto opacity-80" />
              <h2 className="font-bold text-nbe-green">{t.workspace}</h2>
              <p className="max-w-md text-sm">{t.workspacePending.replace("{wave}", String(demo.wave))}</p>
            </section>
            <DecisionCard title={demo.cardTitle[lang]} items={demo.cardItems[lang]} banner={demo.banner[lang]} tone={demo.bannerTone} />
          </div>
        )}
      </div>

      <div className="mt-5">
        <TraceDrawer trace={trace} health={health} />
      </div>
    </div>
  );
}
