// The seven NBE use cases, one demo each (deck slides 4 and 6-12). Content is bilingual;
// the decision card mirrors the panel on each slide.

export type Lang = "en" | "ar";
export type Tone = "ok" | "review" | "stop";

type Text = Record<Lang, string>;
type TextList = Record<Lang, string[]>;

export interface Demo {
  id: string;            // d1..d7, also the API prefix /api/<id>
  code: string;          // D1..D7
  wave: 1 | 2;
  effortDays: number;
  fit: Text;
  title: Text;
  tagline: Text;
  story: Text;
  flow: TextList;
  cardTitle: Text;
  cardItems: TextList;
  banner: Text;
  bannerTone: Tone;
}

export const DEMOS: Demo[] = [
  {
    id: "d1", code: "D1", wave: 2, effortDays: 8,
    fit: { en: "Strong", ar: "قوي" },
    title: { en: "Doc verification for credit lending", ar: "التحقق من مستندات الإقراض" },
    tagline: { en: "Extract fields, detect tampering, cross-check", ar: "استخراج البيانات وكشف التلاعب والمطابقة بين المستندات" },
    story: {
      en: "A loan officer uploads an applicant's documents. A fine-tuned model on this machine reads them, rules cross-check them against each other and the application, and readings the model was unsure of are confirmed by the officer first. The verdict is evidence-backed, for a human to approve or override. Synthetic packs with planted forgeries are included.",
      ar: "يرفع موظف الائتمان مستندات العميل. يقرؤها نموذج مدرَّب على هذا الجهاز، وتطابقها القواعد فيما بينها ومع بيانات الطلب، ويؤكد الموظف أولاً القراءات التي لم يكن النموذج متأكداً منها. الحكم مدعوم بالأدلة ليعتمده الموظف أو يعدّله. تتضمن المنصة ملفات تجريبية مولَّدة بها تلاعب مقصود.",
    },
    flow: {
      en: ["Uploaded documents", "Field extraction", "Cross-document checks", "Evidence-backed verdict", "Human review"],
      ar: ["مستندات مرفوعة", "استخراج البيانات", "المطابقة بين المستندات", "حكم مدعوم بالأدلة", "مراجعة بشرية"],
    },
    cardTitle: { en: "Review decision panel", ar: "لوحة قرار المراجعة" },
    cardItems: {
      en: ["Document card: extracted fields", "Evidence link: metadata mismatch", "Risk verdict: flagged for review"],
      ar: ["بطاقة المستند: البيانات المستخرجة", "رابط الدليل: عدم تطابق البيانات الوصفية", "تقييم المخاطر: محال للمراجعة"],
    },
    banner: { en: "Flags for review. A human decides; never fraud-proof", ar: "إشارات للمراجعة فقط. القرار للإنسان" },
    bannerTone: "review",
  },
  {
    id: "d2", code: "D2", wave: 1, effortDays: 6,
    fit: { en: "Strong", ar: "قوي" },
    title: { en: "Chat with Document", ar: "المحادثة مع المستندات" },
    tagline: { en: "Working procedures, legal documents and contracts", ar: "إجراءات العمل والمستندات القانونية والعقود" },
    story: {
      en: "A branch employee asks in Arabic about a procedure that changed last month. The answer cites the current version and shows what changed since the previous one.",
      ar: "يسأل موظف الفرع بالعربية عن إجراء تغيّر الشهر الماضي. تأتي الإجابة مع الإشارة إلى الإصدار الحالي وتوضيح ما تغيّر عن الإصدار السابق.",
    },
    flow: {
      en: ["Procedure / contract", "Index & retrieve (bge-m3 + reranker)", "Branch question", "Cited answer", "Version delta"],
      ar: ["إجراء / عقد", "فهرسة واسترجاع", "سؤال الفرع", "إجابة موثّقة بالمصادر", "الفرق بين الإصدارات"],
    },
    cardTitle: { en: "Branch answer card", ar: "بطاقة إجابة الفرع" },
    cardItems: {
      en: ["Arabic question: procedure updated", "Answer with source citations", "Version delta: what changed"],
      ar: ["سؤال بالعربية: إجراء محدَّث", "إجابة مع الإشارة إلى المصادر", "الفرق بين الإصدارات: ما الذي تغيّر"],
    },
    banner: { en: "Every answer carries source citations", ar: "كل إجابة موثّقة بمصادرها" },
    bannerTone: "ok",
  },
  {
    id: "d3", code: "D3", wave: 2, effortDays: 6,
    fit: { en: "Good", ar: "جيد" },
    title: { en: "Campaigns & Offers (Hyper-Personalization)", ar: "الحملات والعروض المخصّصة" },
    tagline: { en: "Personalised offers with specific merchants", ar: "عروض مخصّصة مع تجّار محددين" },
    story: {
      en: "Marketing picks a synthetic segment. The system profiles interests from transactions, matches merchants and writes Arabic and English offers that pass a compliance check, with a banner mock-up and an A/B test plan.",
      ar: "يختار فريق التسويق شريحة عملاء تجريبية. يحلّل النظام الاهتمامات من المعاملات ويطابقها مع التجّار ويكتب عروضًا بالعربية والإنجليزية تجتاز فحص الامتثال، مع تصميم إعلاني وخطة اختبار A/B.",
    },
    flow: {
      en: ["Synthetic segment", "Interest profile", "Merchant match", "AR + EN message", "Compliance check", "Banner / A-B plan"],
      ar: ["شريحة تجريبية", "ملف الاهتمامات", "مطابقة التجّار", "رسالة عربي + إنجليزي", "فحص الامتثال", "إعلان / خطة A-B"],
    },
    cardTitle: { en: "Bilingual campaign card", ar: "بطاقة الحملة ثنائية اللغة" },
    cardItems: {
      en: ["Arabic + English offer message", "Compliance badge: checked", "Synthetic-data badge"],
      ar: ["رسالة العرض بالعربية والإنجليزية", "شارة الامتثال: تم الفحص", "شارة البيانات التجريبية"],
    },
    banner: { en: "AI-generated mock-up · synthetic data only", ar: "تصميم مُولَّد بالذكاء الاصطناعي · بيانات تجريبية فقط" },
    bannerTone: "ok",
  },
  {
    id: "d4", code: "D4", wave: 2, effortDays: 9,
    fit: { en: "Good; voice is the risk", ar: "جيد؛ الصوت هو التحدي" },
    title: { en: "AI Virtual Agent", ar: "المساعد الافتراضي الذكي" },
    tagline: { en: "Chat / voice with KB grounding and tool calls", ar: "محادثة نصية وصوتية مستندة إلى قاعدة المعرفة مع تنفيذ إجراءات" },
    story: {
      en: "A customer speaks Arabic: “I lost my card.” The agent verifies them with a mock OTP, blocks the card, logs a complaint and hands off to a human on request. A jailbreak attempt is blocked live.",
      ar: "يقول العميل بالعربية: «فقدت بطاقتي». يتحقق المساعد من هويته برمز تحقق تجريبي، ويوقف البطاقة، ويسجّل شكوى، ويحوّله إلى موظف عند الطلب. وتُصدّ محاولة التلاعب مباشرة.",
    },
    flow: {
      en: ["Arabic voice request", "Mock OTP", "Mock card API", "Complaint ticket", "Human handoff"],
      ar: ["طلب صوتي بالعربية", "رمز تحقق تجريبي", "واجهة بطاقات تجريبية", "تذكرة شكوى", "تحويل إلى موظف"],
    },
    cardTitle: { en: "Conversation + tool-call lane", ar: "المحادثة ومسار الإجراءات" },
    cardItems: {
      en: ["Transcript: Arabic voice turn", "Tool-call lane: mock OTP / card API", "Guardrail: jailbreak blocked"],
      ar: ["النص: محادثة صوتية بالعربية", "مسار الإجراءات: رمز التحقق / واجهة البطاقات", "الحماية: صدّ محاولة التلاعب"],
    },
    banner: { en: "Guardrail STOP marker shown live", ar: "علامة الإيقاف تظهر مباشرة" },
    bannerTone: "stop",
  },
  {
    id: "d5", code: "D5", wave: 1, effortDays: 5,
    fit: { en: "Strong", ar: "قوي" },
    title: { en: "Legal Documents Summarization", ar: "تلخيص المستندات القانونية" },
    tagline: { en: "Rulings, clauses, risks, version compare", ar: "الأحكام والبنود والمخاطر ومقارنة الإصدارات" },
    story: {
      en: "Legal uploads a ruling or contract and gets a structured summary, the key clauses, risk flags and a comparison against NBE's standard template.",
      ar: "يرفع الفريق القانوني حكمًا أو عقدًا فيحصل على ملخص منظّم، وأهم البنود، وإشارات المخاطر، ومقارنة بالنموذج المعتمد لدى البنك.",
    },
    flow: {
      en: ["Ruling / contract upload", "Chunked map-reduce summary", "Clause extraction", "Risk flags", "Diff vs template"],
      ar: ["رفع الحكم / العقد", "تلخيص على مراحل", "استخراج البنود", "إشارات المخاطر", "المقارنة بالنموذج"],
    },
    cardTitle: { en: "Legal summary card", ar: "بطاقة الملخص القانوني" },
    cardItems: {
      en: ["Ruling summary: key points", "Clauses: indemnity, termination, SLA", "Risk flags + diff vs template"],
      ar: ["ملخص الحكم: النقاط الرئيسية", "البنود: التعويض والإنهاء ومستوى الخدمة", "إشارات المخاطر والمقارنة بالنموذج"],
    },
    banner: { en: "Shares D2's RAG pipeline, separate demo experience", ar: "يشارك منظومة الاسترجاع مع D2 بتجربة مستقلة" },
    bannerTone: "ok",
  },
  {
    id: "d6", code: "D6", wave: 1, effortDays: 5,
    fit: { en: "Strong", ar: "قوي" },
    title: { en: "NBE AI Assistant", ar: "مساعد البنك الأهلي الذكي" },
    tagline: { en: "In-house employee assistant, Dataiku-integrated", ar: "مساعد داخلي للموظفين متكامل مع Dataiku" },
    story: {
      en: "An employee uses one assistant for file chat, drafting, summarisation, translation and code explanation. A panel shows which model the router chose for each task and why.",
      ar: "يستخدم الموظف مساعدًا واحدًا للمحادثة مع الملفات والصياغة والتلخيص والترجمة وشرح الأكواد. وتعرض لوحة النموذج الذي اختاره الموجّه لكل مهمة وسبب اختياره.",
    },
    flow: {
      en: ["Employee task", "Router selects model", "File chat / translation / code", "Grounded answer"],
      ar: ["مهمة الموظف", "الموجّه يختار النموذج", "ملفات / ترجمة / أكواد", "إجابة موثّقة"],
    },
    cardTitle: { en: "Model-selection panel", ar: "لوحة اختيار النموذج" },
    cardItems: {
      en: ["File chat & drafting → workhorse LLM", "Translation & general → workhorse LLM", "Code explanation → hero model"],
      ar: ["الملفات والصياغة ← النموذج الأساسي", "الترجمة والمهام العامة ← النموذج الأساسي", "شرح الأكواد ← النموذج الأكبر"],
    },
    banner: { en: "Router picks the right model per task", ar: "الموجّه يختار النموذج المناسب لكل مهمة" },
    bannerTone: "ok",
  },
  {
    id: "d7", code: "D7", wave: 1, effortDays: 7,
    fit: { en: "Strong", ar: "قوي" },
    title: { en: "Complaints Personalization", ar: "معالجة الشكاوى المخصّصة" },
    tagline: { en: "Route and draft empathetic, policy-compliant responses", ar: "توجيه الشكاوى وصياغة ردود متعاطفة ومتوافقة مع السياسات" },
    story: {
      en: "Incoming complaints are classified by topic, severity and SLA, routed to a team and given an empathetic, policy-compliant draft reply that waits for human approval.",
      ar: "تُصنَّف الشكاوى الواردة حسب الموضوع والأولوية ومستوى الخدمة، وتُوجَّه إلى الفريق المختص مع مسودة رد متعاطفة ومتوافقة مع السياسات بانتظار اعتماد الموظف.",
    },
    flow: {
      en: ["20 synthetic complaints", "Classify topic / severity / SLA", "Route", "Draft compliant reply", "Trend view"],
      ar: ["٢٠ شكوى تجريبية", "تصنيف الموضوع / الأولوية / مستوى الخدمة", "التوجيه", "مسودة رد متوافقة", "عرض الاتجاهات"],
    },
    cardTitle: { en: "Triage dashboard", ar: "لوحة فرز الشكاوى" },
    cardItems: {
      en: ["Severity + SLA: prioritised queue", "Route: assigned team", "Review status: awaiting human"],
      ar: ["الأولوية ومستوى الخدمة: قائمة مرتّبة", "التوجيه: الفريق المختص", "حالة المراجعة: بانتظار الموظف"],
    },
    banner: { en: "Human review before any action", ar: "مراجعة بشرية قبل أي إجراء" },
    bannerTone: "review",
  },
];

export const demoById = (id: string | undefined) => DEMOS.find((d) => d.id === id);
