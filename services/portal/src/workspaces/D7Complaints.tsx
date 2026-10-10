import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON, type TraceStep } from "../api";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Panel, Spinner } from "./common";

interface Triage {
  topic: string; topic_ar: string; severity: number; sentiment: string; vulnerable: boolean; needs_callback: boolean; summary: string;
  language: string; team: string; sla_hours: number; sla_due: string; similar: { id: string; text: string; topic: string }[];
  draft: string; policy_ok: boolean; policy_violations: string[]; guardrail: { allowed: boolean; rail: string | null };
  labels: { topic: string; severity: number }; trace: TraceStep[];
  team_en?: string | null; public_reply?: boolean; guardrail_gate?: boolean;   // present when data/seed/d7/policy.json is in use
}
interface Item { id: string; channel: string; lang: string; customer_name: string; text: string; received_at: string; status: string; triage: Triage | null; final_reply: string | null }
interface Trends { total: number; clusters: { cluster: number; name: string; count: number; avg_severity: number; top_topic: string; examples: string[] }[]; by_topic: Record<string, number>; topic_ar: Record<string, string> }
interface Accuracy { n: number; topic_accuracy: number; severity_within_1: number; avg_latency_ms: number; note: string }

const CH: Record<string, string> = { email: "✉️", social: "💬", chat: "🗨️", voice: "📞" };
const SEV = ["neutral", "green", "neutral", "orange", "red"] as const;   // index = severity 1-4
const L = {
  en: { queue: "Queue", trends: "Trends", accuracy: "Accuracy", triageAll: "Triage all", triage: "Triage", panel: "Triage dashboard",
        banner: "Human review before any action", sla: "SLA", team: "Team", status: "Status", draft: "Draft reply", similar: "Similar past complaints",
        approve: "Approve & send", edit: "Save edit & send", escalate: "Escalate", awaiting: "Awaiting human", policy: "Policy check", guard: "Guardrail",
        select: "Select a complaint.", policyNote: "Synthetic placeholder policy until NBE supplies its rules.", vulnerable: "Vulnerable customer", callback: "Call back",
        runAcc: "Run on 100 held-out complaints", label: "Synthetic label", publicReply: "Public reply",
        blocked: "The guardrail blocked this draft. Edit it or escalate." },
  ar: { queue: "قائمة الشكاوى", trends: "الاتجاهات", accuracy: "الدقة", triageAll: "فرز الكل", triage: "فرز", panel: "لوحة فرز الشكاوى",
        banner: "مراجعة بشرية قبل أي إجراء", sla: "مستوى الخدمة", team: "الفريق", status: "الحالة", draft: "مسودة الرد", similar: "شكاوى سابقة مشابهة",
        approve: "اعتماد وإرسال", edit: "حفظ التعديل وإرسال", escalate: "تصعيد", awaiting: "بانتظار الموظف", policy: "فحص السياسة", guard: "الحماية",
        select: "اختر شكوى.", policyNote: "سياسة تجريبية مؤقتة إلى أن يوفر البنك قواعده.", vulnerable: "عميل في ظرف صعب", callback: "اتصال هاتفي",
        runAcc: "تشغيل على 100 شكوى خارج العينة", label: "التصنيف التجريبي", publicReply: "رد عام",
        blocked: "أوقفت الحماية هذه المسودة. عدّلها أو صعّد الشكوى." },
};
const STATUS: Record<string, { en: string; ar: string; tone: "neutral" | "orange" | "green" | "red" }> = {
  new: { en: "New", ar: "جديدة", tone: "neutral" }, awaiting_human: { en: "Awaiting human", ar: "بانتظار الموظف", tone: "orange" },
  approved: { en: "Approved", ar: "معتمدة", tone: "green" }, approved_edited: { en: "Edited & approved", ar: "معدلة ومعتمدة", tone: "green" },
  escalated: { en: "Escalated", ar: "مصعّدة", tone: "red" },
};

function due(iso: string) {
  const h = (new Date(iso).getTime() - Date.now()) / 3.6e6;
  return h < 0 ? `overdue ${Math.abs(h).toFixed(0)}h` : h < 1 ? `${Math.round(h * 60)} min` : `${h.toFixed(0)} h`;
}

export default function D7Complaints({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [tab, setTab] = useState<"queue" | "trends" | "accuracy">("queue");
  const [items, setItems] = useState<Item[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [trends, setTrends] = useState<Trends | null>(null);
  const [acc, setAcc] = useState<Accuracy | null>(null);
  const item = items.find((i) => i.id === sel);

  const load = useCallback(async () => setItems(await getJSON<Item[]>("/api/d7/queue")), []);
  useEffect(() => { load().catch((e) => setError(String(e))); }, [load]);
  useEffect(() => { setDraft(item?.final_reply ?? item?.triage?.draft ?? ""); if (item?.triage) onTrace(item.triage.trace); }, [sel, item?.triage]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setError("");
    try { await fn(); await load(); } catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  };
  const openTab = async (t: typeof tab) => {
    setTab(t);
    if (t === "trends" && !trends) await run("trends", async () => setTrends(await getJSON<Trends>("/api/d7/trends")));
    if (t === "accuracy" && !acc) await run("acc", async () => setAcc(await getJSON<Accuracy>("/api/d7/accuracy")));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {(["queue", "trends", "accuracy"] as const).map((t) => (
          <button key={t} onClick={() => openTab(t)} className={`rounded-full px-4 py-1.5 text-sm font-semibold ${tab === t ? "bg-nbe-green text-white" : "bg-white text-nbe-green ring-1 ring-nbe-border"}`}>
            {l[t]}
          </button>
        ))}
        {tab === "queue" && (
          <span className="ms-auto">
            <Button onClick={() => run("all", () => postJSON("/api/d7/triage-all"))} disabled={!!busy}>{l.triageAll}</Button>
          </span>
        )}
      </div>
      <ErrorNote error={error} />
      {busy && <Spinner label={busy === "all" ? "Classifying, routing and drafting replies for the queue…" : "…"} />}

      {tab === "queue" && (
        <div className="grid gap-5 lg:grid-cols-3">
          <section className="overflow-hidden rounded-xl border border-nbe-border bg-white lg:col-span-2">
            <div className="max-h-[38rem] overflow-y-auto">
              {items.map((i) => (
                <button key={i.id} data-test="queue-item" onClick={() => setSel(i.id)} className={`flex w-full items-start gap-3 border-b border-nbe-border px-4 py-3 text-start ${sel === i.id ? "bg-nbe-orange/10" : "hover:bg-nbe-bg"}`}>
                  <span className="text-lg" title={i.channel}>{CH[i.channel]}</span>
                  <span className="flex-1">
                    <span className="flex flex-wrap items-center gap-1.5 text-xs">
                      <b className="text-nbe-strong">{i.id}</b>
                      <span dir="auto">{i.customer_name}</span>
                      <Chip>{i.lang}</Chip>
                      {i.triage && <Chip tone={SEV[i.triage.severity]}>S{i.triage.severity} · {lang === "ar" ? i.triage.topic_ar : i.triage.topic}</Chip>}
                      {i.triage && <Chip>{l.sla} {due(i.triage.sla_due)}</Chip>}
                      {i.triage?.vulnerable && <Chip tone="red">{l.vulnerable}</Chip>}
                      <Chip tone={STATUS[i.status].tone}>{STATUS[i.status][lang]}</Chip>
                    </span>
                    <span dir="auto" className="mt-1 line-clamp-2 block text-sm text-nbe-strong">{i.text}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>

          <Panel title={l.panel} banner={l.banner} tone="review">
            {!item && <p className="text-sm">{l.select}</p>}
            {item && (
              <>
                <Block label={`${item.id} · ${CH[item.channel]} ${item.channel}`}><p dir="auto" className="whitespace-pre-wrap">{item.text}</p></Block>
                {!item.triage ? (
                  <Button test="triage" onClick={() => run("one", () => postJSON(`/api/d7/triage/${item.id}`))} disabled={!!busy}>{l.triage}</Button>
                ) : (
                  <>
                    <Block label={`${l.sla} · ${l.team}`}>
                      <div className="flex flex-wrap gap-1.5">
                        <Chip tone={SEV[item.triage.severity]}>S{item.triage.severity}</Chip>
                        <Chip>{lang === "ar" ? item.triage.topic_ar : item.triage.topic}</Chip>
                        <Chip>{item.triage.sentiment}</Chip>
                        {item.triage.needs_callback && <Chip tone="orange">{l.callback}</Chip>}
                        <Chip>{item.triage.sla_hours} h · {due(item.triage.sla_due)}</Chip>
                      </div>
                      <div className="mt-1 font-semibold" dir="auto">{lang === "en" && item.triage.team_en ? item.triage.team_en : item.triage.team}</div>
                      <div className="mt-1 text-xs text-nbe-text" dir="auto">{item.triage.summary}</div>
                      <div className="mt-1 text-xs text-nbe-text">{l.label}: {item.triage.labels.topic} / S{item.triage.labels.severity}</div>
                    </Block>
                    <div>
                      <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase text-nbe-text">
                        {l.draft}
                        {item.triage.public_reply && <Chip tone="orange">{l.publicReply}</Chip>}
                        <Chip tone={item.triage.policy_ok ? "green" : "red"}>{l.policy} {item.triage.policy_ok ? "✓" : "✗"}</Chip>
                        <Chip tone={item.triage.guardrail.allowed ? "green" : "red"}>{l.guard} {item.triage.guardrail.allowed ? "✓" : "✗"}</Chip>
                      </div>
                      <textarea data-test="draft" dir="auto" value={draft} onChange={(e) => setDraft(e.target.value)} rows={8} disabled={item.status !== "awaiting_human"}
                                className="w-full rounded-lg border border-nbe-border p-3 text-sm leading-relaxed" />
                      <p className="text-xs text-nbe-text">{l.policyNote}</p>
                    </div>
                    {item.status === "awaiting_human" ? (
                      <div className="flex flex-wrap gap-2">
                        <Button onClick={() => run("d", () => postJSON(`/api/d7/decision/${item.id}`, draft === item.triage!.draft ? { action: "approve" } : { action: "edit", text: draft }))}
                                disabled={!!busy || (!!item.triage.guardrail_gate && !item.triage.guardrail.allowed && draft === item.triage.draft)}>
                          {draft === item.triage.draft ? l.approve : l.edit}
                        </Button>
                        <Button variant="ghost" onClick={() => run("d", () => postJSON(`/api/d7/decision/${item.id}`, { action: "escalate" }))} disabled={!!busy}>{l.escalate}</Button>
                        {item.triage.guardrail_gate && !item.triage.guardrail.allowed && <p className="w-full text-xs text-red-700">{l.blocked}</p>}
                      </div>
                    ) : (
                      <Chip tone={STATUS[item.status].tone}>{STATUS[item.status][lang]}</Chip>
                    )}
                    {item.triage.similar.length > 0 && (
                      <details className="text-xs">
                        <summary className="cursor-pointer font-semibold text-nbe-green">{l.similar} ({item.triage.similar.length})</summary>
                        {item.triage.similar.map((s) => <p key={s.id} dir="auto" className="mt-1 rounded bg-nbe-bg p-2">{s.id}: {s.text}…</p>)}
                      </details>
                    )}
                  </>
                )}
              </>
            )}
          </Panel>
        </div>
      )}

      {tab === "trends" && trends && (
        <section className="grid gap-5 lg:grid-cols-3">
          <div className="rounded-xl border border-nbe-border bg-white p-5 lg:col-span-2">
            <h3 className="mb-3 font-bold text-nbe-green">{trends.total} complaints · themes found by clustering (bge-m3 embeddings, named by the LLM)</h3>
            {trends.clusters.map((c) => (
              <div key={c.cluster} className="mb-2">
                <div className="flex justify-between text-sm" dir="auto"><span className="font-semibold">{c.name}</span><span>{c.count} · S{c.avg_severity}</span></div>
                <div className="h-2.5 rounded-full bg-nbe-bg"><div className="h-full rounded-full bg-nbe-orange" style={{ width: `${(100 * c.count) / trends.clusters[0].count}%` }} /></div>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-nbe-border bg-white p-5">
            <h3 className="mb-3 font-bold text-nbe-green">By topic</h3>
            {Object.entries(trends.by_topic).sort((a, b) => b[1] - a[1]).map(([t, n]) => (
              <div key={t} className="flex justify-between border-t border-nbe-border py-1.5 text-sm"><span>{lang === "ar" ? trends.topic_ar[t] : t}</span><b>{n}</b></div>
            ))}
          </div>
        </section>
      )}

      {tab === "accuracy" && acc && (
        <section className="grid gap-4 sm:grid-cols-3">
          {[["Topic accuracy", `${Math.round(acc.topic_accuracy * 100)}%`], ["Severity within ±1", `${Math.round(acc.severity_within_1 * 100)}%`], ["Avg latency", `${(acc.avg_latency_ms / 1000).toFixed(1)} s`]].map(([k, v]) => (
            <div key={k} className="rounded-xl border border-nbe-border bg-white p-5">
              <div className="text-sm text-nbe-text">{k}</div>
              <div className="text-3xl font-bold text-nbe-green">{v}</div>
            </div>
          ))}
          <p className="text-xs sm:col-span-3">n = {acc.n}. {acc.note}</p>
        </section>
      )}
    </div>
  );
}
