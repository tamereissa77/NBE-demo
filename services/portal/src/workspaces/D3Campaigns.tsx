import { useEffect, useState } from "react";
import { getJSON, postJSON, type TraceStep } from "../api";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Panel, Spinner } from "./common";

interface Segment { persona: string; persona_ar: string; customers: number; sms: number; email: number }
interface Profile { category: string; category_ar: string; category_en?: string; share: number; lift: number; transactions: number }
interface Merchant { id: string; name_ar: string; category: string; category_ar: string; category_en?: string; city: string; seg_spend: number | null; seg_customers: number | null; from_brief?: boolean }
interface Issue { field: string; rule: string; detail: string }
interface SmsInfo { chars: number; parts: number; encoding: string; max_parts: number; max_chars: number }
interface Result {
  segment: { persona: string; persona_ar: string; n: number; sms: number; email: number }; profile: Profile[]; merchants: Merchant[];
  offer: { merchant: string; category_ar: string; cashback_pct: number; cap_egp: number; valid_until: string };
  copy: Record<string, string>; compliance: { passed: boolean; issues: Issue[]; initial_issues: Issue[]; auto_fixed: boolean; fix_passes: number; enforced_in_code: { field: string; action: string; detail: string }[] };
  sms?: Record<string, SmsInfo>;
  banner: { png_base64: string | null; source: string }; trace: TraceStep[]; total_ms: number;
  ab_test: { per_arm: number; audience_opted_in: number; min_detectable_lift: number | null; baseline_rate: number; baseline_note: string; baseline_note_ar?: string;
             min_detectable_lift_if_baseline: Record<string, number | null>; holdout_pct: number; metric: string; metric_ar?: string; note: string; note_ar?: string; variants: { A: string; B: string } };
}

const PERSONA_EN: Record<string, string> = { young_professional: "Young professionals", family: "Families", student: "Students", affluent: "Affluent", sme_owner: "SME owners" };
const TABS: [string, string][] = [["sms_a_ar", "SMS A"], ["sms_b_ar", "SMS B"], ["sms_en", "SMS EN"], ["email_ar", "Email AR"], ["email_en", "Email EN"], ["social_egy", "Social (EGY)"]];
const DEFAULT_BASELINE = 8;   // % — the API default (CampaignIn.baseline_rate)
const L = {
  en: { segment: "Segment", city: "City (optional)", all: "All cities", brief: "Marketing brief (optional)", stress: "Stress-test compliance (plant a banned claim)",
        baselineField: "Assumed redemption rate for the A/B plan (%)",
        build: "Build campaign", working: "Profiling spend, matching merchants, writing and checking copy…", profile: "Interest profile (share of purchases · lift vs all customers)",
        merchants: "Partner merchant match", card: "Bilingual campaign card", banner: "AI-generated mock-up · synthetic data only", compliance: "Compliance",
        passed: "Checked", fixed: "Auto-fixed", synthetic: "Synthetic data", ab: "A/B test plan", offer: "Offer", none: "Choose a segment and build a campaign.",
        caught: "Caught before output", enforced: "Fixed in code (the model could not fix these)", assumed: "assumed", customers: "customers",
        fromBrief: "Matched from the brief", egp: "EGP", inSegment: "customers in segment", cashback: "cashback", cap: "cap", until: "until",
        smsA: "SMS A · العربية", smsB: "SMS B · العربية", smsEn: "SMS · English", chars: "characters", smsPart: "SMS part", smsParts: "SMS parts",
        copy: "Copy text", copied: "Copied ✓", download: "Download image", mock: "AI-generated mock-up", source: { live: "live", cache: "cache" } as Record<string, string>,
        audience: "Audience", optedIn: "opted in", holdout: "holdout", perArm: "Per arm", baseline: "Baseline", redemption: "redemption", lift: "Detectable lift",
        at: "At", tooSmall: "too small", smsCount: "SMS", emailCount: "email" },
  ar: { segment: "الشريحة", city: "المدينة (اختياري)", all: "كل المدن", brief: "توجيه تسويقي (اختياري)", stress: "اختبار الامتثال (إدراج عبارة مخالفة عمداً)",
        baselineField: "معدل الاستفادة المفترض لخطة A/B (%)",
        build: "إنشاء الحملة", working: "تحليل الإنفاق ومطابقة التجّار وكتابة النصوص وفحصها…", profile: "ملف الاهتمامات (حصة المشتريات · مقارنة بكل العملاء)",
        merchants: "مطابقة التجّار الشركاء", card: "بطاقة الحملة ثنائية اللغة", banner: "تصميم مُولَّد بالذكاء الاصطناعي · بيانات تجريبية فقط", compliance: "الامتثال",
        passed: "تم الفحص", fixed: "تم التصحيح آلياً", synthetic: "بيانات تجريبية", ab: "خطة اختبار A/B", offer: "العرض", none: "اختر شريحة وأنشئ حملة.",
        caught: "رُصدت قبل الإخراج", enforced: "صُحّحت برمجياً (تعذّر على النموذج تصحيحها)", assumed: "افتراض", customers: "عميل",
        fromBrief: "مطابق للتوجيه التسويقي", egp: "جنيه", inSegment: "عميلاً في الشريحة", cashback: "استرداد نقدي", cap: "بحد أقصى", until: "حتى",
        smsA: "رسالة A · العربية", smsB: "رسالة B · العربية", smsEn: "رسالة · English", chars: "حرفاً", smsPart: "رسالة SMS", smsParts: "رسائل SMS",
        copy: "نسخ النص", copied: "تم النسخ ✓", download: "تنزيل الصورة", mock: "تصميم مُولَّد بالذكاء الاصطناعي", source: { live: "مباشر", cache: "من المخزّن" } as Record<string, string>,
        audience: "الجمهور", optedIn: "وافقوا على الرسائل", holdout: "مجموعة ضابطة", perArm: "لكل نسخة", baseline: "خط الأساس", redemption: "معدل استفادة", lift: "الارتفاع القابل للرصد",
        at: "عند", tooSmall: "صغير جداً", smsCount: "رسائل SMS", emailCount: "بريد" },
};

// Plain-language names for the compliance output (the API returns rule ids such as "offer_terms").
const FIELD: Record<string, [string, string]> = {
  sms_a_ar: ["SMS A (Arabic)", "رسالة A بالعربية"], sms_b_ar: ["SMS B (Arabic)", "رسالة B بالعربية"], sms_en: ["SMS (English)", "رسالة بالإنجليزية"],
  email_subject_ar: ["Email subject (Arabic)", "عنوان البريد بالعربية"], email_body_ar: ["Email (Arabic)", "البريد بالعربية"],
  email_subject_en: ["Email subject (English)", "عنوان البريد بالإنجليزية"], email_body_en: ["Email (English)", "البريد بالإنجليزية"],
  social_egy: ["Social post", "منشور التواصل"], banner_headline_ar: ["Banner headline", "عنوان البانر"],
};
const RULE: Record<string, [string, string]> = {
  offer_terms: ["Missing offer details", "تفاصيل العرض ناقصة"], required_disclaimer: ["Missing disclaimer", "العبارة القانونية ناقصة"],
  sms_length: ["SMS too long", "رسالة SMS طويلة"], banned_claim: ["Banned claim", "عبارة محظورة"],
};
const ACTION: Record<string, [string, string]> = {
  replaced_with_offer_terms: ["Replaced with the standard offer text", "استُبدلت بنص العرض القياسي"],
  removed_claim: ["Removed banned claim", "حُذفت العبارة المحظورة"], added_disclaimer: ["Added the disclaimer", "أُضيفت العبارة القانونية"],
  trimmed_sms: ["Shortened to fit the SMS limit", "اختُصرت لتناسب حد الرسالة"],
};
const tr = (m: Record<string, [string, string]>, k: string, lang: "en" | "ar") => (m[k] ? m[k][lang === "ar" ? 1 : 0] : k);
const detail = (d: string) => d.replace(/^missing /, "");

// navigator.clipboard exists only on https:// or localhost; the portal is also opened as http://<gb10-ip>:8200.
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

export default function D3Campaigns({ onTrace, onProgress }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [segments, setSegments] = useState<Segment[]>([]);
  const [cities, setCities] = useState<string[]>([]);
  const [persona, setPersona] = useState("young_professional");
  const [city, setCity] = useState("");
  const [brief, setBrief] = useState("");
  const [stress, setStress] = useState(false);
  const [baseline, setBaseline] = useState(String(DEFAULT_BASELINE));
  const [res, setRes] = useState<Result | null>(null);
  const [tab, setTab] = useState("sms_a_ar");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getJSON<{ segments: Segment[]; cities: string[] }>("/api/d3/segments").then((d) => { setSegments(d.segments); setCities(d.cities); }).catch((e) => setError(String(e)));
  }, []);

  const build = async () => {
    setBusy(true); setError("");
    // The service reports which flow step this run has reached; the chips above the workspace follow it.
    const runId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    let running = true;
    onProgress?.(0);
    const poll = window.setInterval(() => {
      getJSON<{ step: number | null }>(`/api/d3/campaign/progress/${runId}`).then((p) => { if (running && p.step !== null) onProgress?.(p.step); }).catch(() => {});
    }, 400);
    const pct = Number(baseline);
    try {
      const r = await postJSON<Result>("/api/d3/campaign", { persona, city: city || null, brief, stress_test: stress, run_id: runId,
                                                             baseline_rate: (pct >= 1 && pct <= 49 ? pct : DEFAULT_BASELINE) / 100 });
      setRes(r); onTrace(r.trace);
    } catch (e) { setRes(null); setError((e as Error).message); } finally {
      running = false; window.clearInterval(poll); onProgress?.(null); setBusy(false);
    }
  };
  const copyFor = (key: string) => res ? (key === "email_ar" ? `${res.copy.email_subject_ar}\n\n${res.copy.email_body_ar}` : key === "email_en" ? `${res.copy.email_subject_en}\n\n${res.copy.email_body_en}` : res.copy[key]) : "";
  const copyTab = async () => { if (await copyText(copyFor(tab))) { setCopied(true); window.setTimeout(() => setCopied(false), 1500); } };
  const maxShare = res ? Math.max(...res.profile.map((p) => Number(p.share))) : 1;
  const category = (x: { category_ar: string; category_en?: string }) => (lang === "en" && x.category_en) || x.category_ar;
  const sms = res?.sms?.[tab];
  const stale = busy ? "opacity-50 transition-opacity" : "transition-opacity";   // the previous campaign stays, dimmed, until the new one arrives

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <section className="space-y-4 lg:col-span-2">
        <div className="grid gap-3 rounded-xl border border-nbe-border bg-white p-4 sm:grid-cols-2">
          <label className="text-sm">{l.segment}
            <select value={persona} onChange={(e) => setPersona(e.target.value)} className="mt-1 w-full rounded-lg border border-nbe-border bg-white px-3 py-2">
              {segments.map((s) => <option key={s.persona} value={s.persona}>{lang === "ar" ? s.persona_ar : PERSONA_EN[s.persona]} · {s.customers.toLocaleString()}</option>)}
            </select>
          </label>
          <label className="text-sm">{l.city}
            <select value={city} onChange={(e) => setCity(e.target.value)} className="mt-1 w-full rounded-lg border border-nbe-border bg-white px-3 py-2">
              <option value="">{l.all}</option>
              {cities.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label className="text-sm sm:col-span-2">{l.brief}
            <input value={brief} onChange={(e) => setBrief(e.target.value)} dir="auto" placeholder="مثال: عروض الصيف للسفر" className="mt-1 w-full rounded-lg border border-nbe-border px-3 py-2" />
          </label>
          <label className="text-sm">{l.baselineField}
            <input data-test="baseline" type="number" min={1} max={49} step={1} value={baseline} onChange={(e) => setBaseline(e.target.value)} dir="ltr" className="mt-1 w-full rounded-lg border border-nbe-border px-3 py-2" />
          </label>
          <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={stress} onChange={(e) => setStress(e.target.checked)} />{l.stress}</label>
          <div className="text-end sm:col-span-2"><Button test="run-campaign" onClick={build} disabled={busy}>{l.build}</Button></div>
        </div>
        <ErrorNote error={error} />
        {busy && <Spinner label={l.working} />}

        {res && (
          <div className={`space-y-4 ${stale}`} aria-busy={busy}>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-xl border border-nbe-border bg-white p-4">
                <h3 className="mb-2 text-sm font-bold text-nbe-green">{l.profile}</h3>
                {res.profile.slice(0, 6).map((p) => (
                  <div key={p.category} className="mb-1.5">
                    <div className="flex justify-between text-xs"><span dir="auto">{category(p)}</span><span dir="ltr">{Number(p.share)}% · ×{Number(p.lift)}</span></div>
                    <div className="h-2 rounded-full bg-nbe-bg"><div className={`h-full rounded-full ${Number(p.lift) >= 1 ? "bg-nbe-green" : "bg-nbe-border"}`} style={{ width: `${(100 * Number(p.share)) / maxShare}%` }} /></div>
                  </div>
                ))}
              </div>
              <div className="rounded-xl border border-nbe-border bg-white p-4">
                <h3 className="mb-2 text-sm font-bold text-nbe-green">{l.merchants}</h3>
                {res.merchants.map((m, i) => (
                  <div key={m.id} data-test="merchant" className={`mb-2 rounded-lg p-2 text-sm ${i === 0 ? "bg-nbe-orange/15" : "bg-nbe-bg"}`}>
                    <div dir="auto"><b>{m.name_ar}</b> · {category(m)} · {m.city}</div>
                    {m.seg_spend !== null && <div className="text-xs text-nbe-text">{Number(m.seg_spend).toLocaleString()} {l.egp} · {m.seg_customers} {l.inSegment}</div>}
                    {m.from_brief && <div className="mt-1"><Chip tone="orange">{l.fromBrief}</Chip></div>}
                  </div>
                ))}
                <div className="mt-2 text-xs"><b>{l.offer}:</b> {l.cashback} {res.offer.cashback_pct}% · {l.cap} {res.offer.cap_egp.toLocaleString()} {l.egp} · {l.until} <bdi>{res.offer.valid_until}</bdi></div>
              </div>
            </div>

            <div className="rounded-xl border border-nbe-border bg-white p-4">
              <div className="mb-3 flex flex-wrap items-center gap-1.5">
                {TABS.map(([k, name]) => <button key={k} onClick={() => setTab(k)} className={`rounded-full px-3 py-1 text-xs font-semibold ${tab === k ? "bg-nbe-green text-white" : "bg-nbe-bg"}`}>{name}</button>)}
                <button data-test="copy-text" onClick={copyTab} className="ms-auto rounded-full px-3 py-1 text-xs font-semibold text-nbe-green ring-1 ring-nbe-border hover:bg-nbe-bg">{copied ? l.copied : l.copy}</button>
              </div>
              <p dir="auto" data-test="copy" className="whitespace-pre-wrap text-sm leading-relaxed text-nbe-strong">{copyFor(tab)}</p>
              {/* SMS billing: Arabic is UCS-2 (70 characters, 67 per part when split), not the 160 of a Latin SMS */}
              {sms && (
                <p data-test="sms-count" className={`mt-1 text-xs ${sms.parts > sms.max_parts ? "font-semibold text-status-stop" : "text-nbe-text"}`}>
                  <bdi>{sms.chars} / {sms.max_chars}</bdi> {l.chars} · <bdi>{sms.parts}</bdi> {sms.parts === 1 ? l.smsPart : l.smsParts} · <bdi>{sms.encoding}</bdi>
                </p>
              )}
            </div>

            {res.banner.png_base64 && (
              <div className="relative overflow-hidden rounded-xl border border-nbe-border">
                <img src={`data:image/png;base64,${res.banner.png_base64}`} alt="banner" className="w-full" />
                {/* The photo is generated with its copy space on the right, so the overlay sits on the right in both languages */}
                <div dir="ltr" className="absolute inset-y-0 right-0 flex w-1/2 flex-col items-end justify-center gap-2 bg-gradient-to-l from-black/55 to-transparent p-6 text-right">
                  <img src="/nbe-logo-web.png" alt="" className="h-10 rounded bg-white/90 p-1" />
                  <div dir="rtl" className="text-2xl font-bold text-white drop-shadow sm:text-3xl">{res.copy.banner_headline_ar}</div>
                  <div dir={lang === "ar" ? "rtl" : "ltr"} className="rounded-full bg-nbe-orange px-3 py-1 text-sm font-bold text-nbe-strong">{res.offer.cashback_pct}% · {res.offer.merchant}</div>
                </div>
                <span data-test="banner-label" data-source={res.banner.source} className="absolute left-3 top-3 rounded bg-black/60 px-2 py-0.5 text-xs text-white">{l.mock} · {l.source[res.banner.source] ?? res.banner.source}</span>
                {/* The file is the generated photo; the headline and logo above are page overlays, not part of the image */}
                <a data-test="banner-download" href={`data:image/png;base64,${res.banner.png_base64}`} download={`nbe-d3-banner-${res.merchants[0].category}.png`}
                   className="absolute bottom-3 left-3 rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-nbe-green hover:bg-white">{l.download}</a>
              </div>
            )}

            <div className="rounded-xl border border-nbe-border bg-white p-4 text-sm">
              <h3 className="mb-2 font-bold text-nbe-green">{l.ab}</h3>
              <div className="grid gap-2 sm:grid-cols-4">
                <Block label={l.audience}>{res.ab_test.audience_opted_in.toLocaleString()} {l.optedIn} · {res.ab_test.holdout_pct}% {l.holdout}</Block>
                <Block label={l.perArm}>{res.ab_test.per_arm.toLocaleString()}</Block>
                <Block label={l.baseline}>{Math.round(res.ab_test.baseline_rate * 100)}% {l.redemption} <Chip tone="orange">{l.assumed}</Chip></Block>
                <Block label={l.lift}><bdi>{res.ab_test.min_detectable_lift ? `≥ ${Math.round(res.ab_test.min_detectable_lift * 100)}%` : "—"}</bdi></Block>
              </div>
              <p className="mt-2 text-xs">{(lang === "ar" && res.ab_test.metric_ar) || res.ab_test.metric}. {(lang === "ar" && res.ab_test.note_ar) || res.ab_test.note}</p>
              <p className="mt-1 text-xs text-nbe-text">
                {(lang === "ar" && res.ab_test.baseline_note_ar) || res.ab_test.baseline_note}{" "}
                {Object.entries(res.ab_test.min_detectable_lift_if_baseline).map(([b, m]) => `${l.at} ${b}: ${m ? `≥ ${Math.round(m * 100)}%` : l.tooSmall}`).join(" · ")}
              </p>
            </div>
          </div>
        )}
      </section>

      <Panel title={l.card} banner={l.banner}>
        {!res && !busy && <p className="text-sm">{l.none}</p>}
        {res && (
          <div data-test="campaign-card" className={`space-y-3 ${stale}`} aria-busy={busy}>
            <div className="flex flex-wrap gap-1.5">
              <Chip tone={res.compliance.passed ? "green" : "red"}>{l.compliance}: {res.compliance.passed ? (res.compliance.auto_fixed ? l.fixed : l.passed) : "✗"}</Chip>
              <Chip tone="orange">{l.synthetic}</Chip>
              <Chip>{(res.total_ms / 1000).toFixed(0)} s</Chip>
            </div>
            <Block label={l.smsA}><p dir="rtl" className="whitespace-pre-wrap">{res.copy.sms_a_ar}</p></Block>
            <Block label={l.smsB}><p dir="rtl" className="whitespace-pre-wrap">{res.copy.sms_b_ar}</p></Block>
            <Block label={l.smsEn}><p dir="ltr">{res.copy.sms_en}</p></Block>
            {res.compliance.initial_issues.length > 0 && (
              <Block label={l.caught} accent="red">
                {res.compliance.initial_issues.map((i, k) => (
                  <div key={k} className="text-xs">• <b>{tr(FIELD, i.field, lang)}</b>: {tr(RULE, i.rule, lang)}{i.rule === "required_disclaimer" ? "" : <> (<bdi>{detail(i.detail)}</bdi>)</>}</div>
                ))}
              </Block>
            )}
            {res.compliance.enforced_in_code.length > 0 && (
              <Block label={l.enforced} accent="orange">
                {res.compliance.enforced_in_code.map((a, k) => (
                  <div key={k} className="text-xs">• <b>{tr(FIELD, a.field, lang)}</b>: {tr(ACTION, a.action, lang)}{a.action === "added_disclaimer" ? "" : <> (<bdi>{detail(a.detail)}</bdi>)</>}</div>
                ))}
              </Block>
            )}
            <p className="text-xs text-nbe-text"><bdi>{(lang === "en" && PERSONA_EN[res.segment.persona]) || res.segment.persona_ar}</bdi> · {res.segment.n.toLocaleString()} {l.customers} · {l.smsCount} {res.segment.sms.toLocaleString()} · {l.emailCount} {res.segment.email.toLocaleString()}</p>
          </div>
        )}
      </Panel>
    </div>
  );
}
