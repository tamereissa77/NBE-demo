import { useEffect, useState } from "react";
import { getJSON, postJSON, type TraceStep } from "../api";
import { BRAND, LOGO } from "../brand";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Panel, Spinner } from "./common";

interface Segment { persona: string; persona_ar: string; customers: number; sms: number; email: number }
interface Profile { category: string; category_ar: string; share: number; lift: number; transactions: number }
interface Merchant { id: string; name_ar: string; category_ar: string; city: string; seg_spend: number | null; seg_customers: number | null }
interface Issue { field: string; rule: string; detail: string }
interface Result {
  segment: { persona_ar: string; n: number; sms: number; email: number }; profile: Profile[]; merchants: Merchant[];
  offer: { merchant: string; category_ar: string; cashback_pct: number; cap: number; currency: string; valid_until: string };
  copy: Record<string, string>; compliance: { passed: boolean; issues: Issue[]; initial_issues: Issue[]; auto_fixed: boolean };
  banner: { png_base64: string | null; source: string }; trace: TraceStep[]; total_ms: number;
  ab_test: { per_arm: number; audience_opted_in: number; min_detectable_lift: number | null; baseline_rate: number; holdout_pct: number; metric: string; note: string; variants: { A: string; B: string } };
}

const PERSONA_EN: Record<string, string> = { young_professional: "Young professionals", family: "Families", student: "Students", affluent: "Affluent", sme_owner: "SME owners" };
const TABS: [string, string][] = [["sms_a_ar", "SMS A"], ["sms_b_ar", "SMS B"], ["sms_en", "SMS EN"], ["email_ar", "Email AR"], ["email_en", "Email EN"], ["social_local", `Social (${BRAND.locale.dialect.code})`]];
const L = {
  en: { segment: "Segment", city: "City (optional)", all: "All cities", brief: "Marketing brief (optional)", stress: "Stress-test compliance (plant a banned claim)",
        build: "Build campaign", working: "Profiling spend, matching merchants, writing and checking copy…", profile: "Interest profile (share of spend · lift vs all customers)",
        merchants: "Partner merchant match", card: "Bilingual campaign card", banner: "AI-generated mock-up · synthetic data only", compliance: "Compliance",
        passed: "Checked", fixed: "Auto-fixed", synthetic: "Synthetic data", ab: "A/B test plan", offer: "Offer", none: "Choose a segment and build a campaign.",
        caught: "Caught before output" },
  ar: { segment: "الشريحة", city: "المدينة (اختياري)", all: "كل المدن", brief: "توجيه تسويقي (اختياري)", stress: "اختبار الامتثال (إدراج عبارة مخالفة عمداً)",
        build: "إنشاء الحملة", working: "تحليل الإنفاق ومطابقة التجّار وكتابة النصوص وفحصها…", profile: "ملف الاهتمامات (حصة الإنفاق · مقارنة بكل العملاء)",
        merchants: "مطابقة التجّار الشركاء", card: "بطاقة الحملة ثنائية اللغة", banner: "تصميم مُولَّد بالذكاء الاصطناعي · بيانات تجريبية فقط", compliance: "الامتثال",
        passed: "تم الفحص", fixed: "تم التصحيح آلياً", synthetic: "بيانات تجريبية", ab: "خطة اختبار A/B", offer: "العرض", none: "اختر شريحة وأنشئ حملة.",
        caught: "رُصدت قبل الإخراج" },
};

export default function D3Campaigns({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [segments, setSegments] = useState<Segment[]>([]);
  const [cities, setCities] = useState<string[]>([]);
  const [persona, setPersona] = useState("young_professional");
  const [city, setCity] = useState("");
  const [brief, setBrief] = useState("");
  const [stress, setStress] = useState(false);
  const [res, setRes] = useState<Result | null>(null);
  const [tab, setTab] = useState("sms_a_ar");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getJSON<{ segments: Segment[]; cities: string[] }>("/api/d3/segments").then((d) => { setSegments(d.segments); setCities(d.cities); }).catch((e) => setError(String(e)));
  }, []);

  const build = async () => {
    setBusy(true); setError(""); setRes(null);
    try {
      const r = await postJSON<Result>("/api/d3/campaign", { persona, city: city || null, brief, stress_test: stress });
      setRes(r); onTrace(r.trace);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const copyFor = (key: string) => res ? (key === "email_ar" ? `${res.copy.email_subject_ar}\n\n${res.copy.email_body_ar}` : key === "email_en" ? `${res.copy.email_subject_en}\n\n${res.copy.email_body_en}` : res.copy[key]) : "";
  const maxShare = res ? Math.max(...res.profile.map((p) => Number(p.share))) : 1;

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <section className="space-y-4 lg:col-span-2">
        <div className="grid gap-3 rounded-xl border border-line bg-white p-4 sm:grid-cols-2">
          <label className="text-sm">{l.segment}
            <select value={persona} onChange={(e) => setPersona(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2">
              {segments.map((s) => <option key={s.persona} value={s.persona}>{lang === "ar" ? s.persona_ar : PERSONA_EN[s.persona]} · {s.customers.toLocaleString()}</option>)}
            </select>
          </label>
          <label className="text-sm">{l.city}
            <select value={city} onChange={(e) => setCity(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2">
              <option value="">{l.all}</option>
              {cities.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label className="text-sm sm:col-span-2">{l.brief}
            <input value={brief} onChange={(e) => setBrief(e.target.value)} dir="auto" placeholder="مثال: عروض الصيف للسفر" className="mt-1 w-full rounded-lg border border-line px-3 py-2" />
          </label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={stress} onChange={(e) => setStress(e.target.checked)} />{l.stress}</label>
          <div className="text-end"><Button test="run-campaign" onClick={build} disabled={busy}>{l.build}</Button></div>
        </div>
        <ErrorNote error={error} />
        {busy && <Spinner label={l.working} />}

        {res && (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-xl border border-line bg-white p-4">
                <h3 className="mb-2 text-sm font-bold text-brand">{l.profile}</h3>
                {res.profile.slice(0, 6).map((p) => (
                  <div key={p.category} className="mb-1.5">
                    <div className="flex justify-between text-xs" dir="auto"><span>{p.category_ar}</span><span>{Number(p.share)}% · ×{Number(p.lift)}</span></div>
                    <div className="h-2 rounded-full bg-canvas"><div className={`h-full rounded-full ${Number(p.lift) >= 1 ? "bg-brand" : "bg-line"}`} style={{ width: `${(100 * Number(p.share)) / maxShare}%` }} /></div>
                  </div>
                ))}
              </div>
              <div className="rounded-xl border border-line bg-white p-4">
                <h3 className="mb-2 text-sm font-bold text-brand">{l.merchants}</h3>
                {res.merchants.map((m, i) => (
                  <div key={m.id} className={`mb-2 rounded-lg p-2 text-sm ${i === 0 ? "bg-accent/15" : "bg-canvas"}`} dir="auto">
                    <b>{m.name_ar}</b> · {m.category_ar} · {m.city}
                    {m.seg_spend !== null && <div className="text-xs text-ink-soft">{Number(m.seg_spend).toLocaleString()} {BRAND.locale.currency.en} · {m.seg_customers} customers in segment</div>}
                  </div>
                ))}
                <div className="mt-2 text-xs" dir="auto"><b>{l.offer}:</b> {res.offer.cashback_pct}% cashback · cap {res.offer.cap} {res.offer.currency} · {res.offer.valid_until}</div>
              </div>
            </div>

            <div className="rounded-xl border border-line bg-white p-4">
              <div className="mb-3 flex flex-wrap gap-1.5">
                {TABS.map(([k, name]) => <button key={k} onClick={() => setTab(k)} className={`rounded-full px-3 py-1 text-xs font-semibold ${tab === k ? "bg-brand text-white" : "bg-canvas"}`}>{name}</button>)}
              </div>
              <p dir="auto" className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{copyFor(tab)}</p>
              {tab.startsWith("sms") && <p className="mt-1 text-xs text-ink-soft">{copyFor(tab).length}/160</p>}
            </div>

            {res.banner.png_base64 && (
              <div className="relative overflow-hidden rounded-xl border border-line">
                <img src={`data:image/png;base64,${res.banner.png_base64}`} alt="banner" className="w-full" />
                <div className="absolute inset-y-0 end-0 flex w-1/2 flex-col items-end justify-center gap-2 bg-gradient-to-l from-black/55 to-transparent p-6 text-end rtl:bg-gradient-to-r">
                  <img src={LOGO} alt="" className="h-10 rounded bg-white/90 p-1" />
                  <div dir="rtl" className="text-2xl font-bold text-white drop-shadow sm:text-3xl">{res.copy.banner_headline_ar}</div>
                  <div className="rounded-full bg-accent px-3 py-1 text-sm font-bold text-ink">{res.offer.cashback_pct}% · {res.offer.merchant}</div>
                </div>
                <span className="absolute start-3 top-3 rounded bg-black/60 px-2 py-0.5 text-xs text-white">AI-generated mock-up · {res.banner.source}</span>
              </div>
            )}

            <div className="rounded-xl border border-line bg-white p-4 text-sm">
              <h3 className="mb-2 font-bold text-brand">{l.ab}</h3>
              <div className="grid gap-2 sm:grid-cols-4">
                <Block label="Audience">{res.ab_test.audience_opted_in.toLocaleString()} opted in · {res.ab_test.holdout_pct}% holdout</Block>
                <Block label="Per arm">{res.ab_test.per_arm.toLocaleString()}</Block>
                <Block label="Baseline">{Math.round(res.ab_test.baseline_rate * 100)}% redemption</Block>
                <Block label="Detectable lift">{res.ab_test.min_detectable_lift ? `≥ ${Math.round(res.ab_test.min_detectable_lift * 100)}%` : "—"}</Block>
              </div>
              <p className="mt-2 text-xs">{res.ab_test.metric}. {res.ab_test.note}</p>
            </div>
          </>
        )}
      </section>

      <Panel title={l.card} banner={l.banner}>
        {!res && !busy && <p className="text-sm">{l.none}</p>}
        {res && (
          <div data-test="campaign-card" className="space-y-3">
            <div className="flex flex-wrap gap-1.5">
              <Chip tone={res.compliance.passed ? "green" : "red"}>{l.compliance}: {res.compliance.passed ? (res.compliance.auto_fixed ? l.fixed : l.passed) : "✗"}</Chip>
              <Chip tone="orange">{l.synthetic}</Chip>
              <Chip>{(res.total_ms / 1000).toFixed(0)} s</Chip>
            </div>
            <Block label="SMS · العربية"><p dir="rtl" className="whitespace-pre-wrap">{res.copy.sms_a_ar}</p></Block>
            <Block label="SMS · English"><p dir="ltr">{res.copy.sms_en}</p></Block>
            {res.compliance.initial_issues.length > 0 && (
              <Block label={l.caught} accent="red">
                {res.compliance.initial_issues.map((i, k) => <div key={k} className="text-xs" dir="auto">• {i.field}: {i.rule} {i.detail}</div>)}
              </Block>
            )}
            <p className="text-xs text-ink-soft" dir="auto">{res.segment.persona_ar} · {res.segment.n.toLocaleString()} customers · SMS {res.segment.sms} · email {res.segment.email}</p>
          </div>
        )}
      </Panel>
    </div>
  );
}
