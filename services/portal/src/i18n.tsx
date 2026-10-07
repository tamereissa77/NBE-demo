import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { BRAND } from "./brand";
import type { Lang } from "./demos";

// UI chrome strings. Demo content lives in demos.ts.
const STRINGS = {
  en: {
    appTitle: BRAND.appTitle.en,
    heroTitle: BRAND.heroTitle?.en ?? "Seven AI use cases, live on one Dell Pro Max with GB10",
    heroSub: `One demo per ${BRAND.short} use case, on one shared, fully offline platform.`,
    allDemos: "All demos",
    openDemo: "Open demo",
    wave: "Wave",
    effort: "Effort",
    days: "engineer-days",
    fit: "GB10 fit",
    poc: "Single-user PoC on one GB10",
    offline: "Fully offline",
    synthetic: "Synthetic data only",
    poweredBy: "Powered by Dell Pro Max with GB10",
    story: "The story",
    workspace: "Demo workspace",
    workspacePending: "The interactive demo is built in Wave {wave}. This screen already runs live against its own service.",
    showWork: "Show the work",
    showWorkHint: "Live service health and metadata. Model calls, retrieved sources and tool calls appear here once the demo is wired.",
    status: { ok: "Live", degraded: "Degraded", down: "Offline", loading: "Checking" },
    switchLang: "عربي",
    back: "Back to all demos",
  },
  ar: {
    appTitle: BRAND.appTitle.ar,
    heroTitle: BRAND.heroTitle?.ar ?? "سبع حالات استخدام للذكاء الاصطناعي على جهاز واحد Dell Pro Max with GB10",
    heroSub: "عرض لكل حالة استخدام، على منصة واحدة مشتركة تعمل دون اتصال بالإنترنت.",
    allDemos: "جميع العروض",
    openDemo: "افتح العرض",
    wave: "المرحلة",
    effort: "الجهد",
    days: "يوم عمل",
    fit: "الملاءمة لـ GB10",
    poc: "إثبات مفهوم لمستخدم واحد على جهاز GB10",
    offline: "يعمل دون إنترنت",
    synthetic: "بيانات تجريبية فقط",
    poweredBy: "يعمل على Dell Pro Max with GB10",
    story: "السيناريو",
    workspace: "مساحة العرض",
    workspacePending: "يُبنى العرض التفاعلي في المرحلة {wave}. هذه الشاشة متصلة الآن بخدمتها الخاصة.",
    showWork: "اعرض التفاصيل",
    showWorkHint: "حالة الخدمة وبياناتها مباشرة. ستظهر هنا استدعاءات النماذج والمصادر والإجراءات بعد ربط العرض.",
    status: { ok: "متصل", degraded: "أداء منخفض", down: "غير متصل", loading: "جارٍ الفحص" },
    switchLang: "English",
    back: "العودة إلى جميع العروض",
  },
} as const;

export type Strings = (typeof STRINGS)["en"];

interface I18n { lang: Lang; t: Strings; toggle: () => void }
const Ctx = createContext<I18n | null>(null);

// ?lang=ar|en in the URL wins (handy for opening a screen straight in Arabic), then the saved choice.
function initialLang(): Lang {
  const fromUrl = new URLSearchParams(window.location.search).get("lang");
  if (fromUrl === "ar" || fromUrl === "en") return fromUrl;
  try {
    return localStorage.getItem("nbe-lang") === "ar" ? "ar" : "en";
  } catch {
    return "en";
  }
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(initialLang);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.title = STRINGS[lang].appTitle;
    try {
      localStorage.setItem("nbe-lang", lang);
    } catch {
      /* storage unavailable: language just won't persist */
    }
  }, [lang]);

  const toggle = () => setLang((l) => (l === "en" ? "ar" : "en"));
  return <Ctx.Provider value={{ lang, t: STRINGS[lang] as Strings, toggle }}>{children}</Ctx.Provider>;
}

export function useI18n() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n outside I18nProvider");
  return ctx;
}
