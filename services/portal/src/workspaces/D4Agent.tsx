import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON, type TraceStep } from "../api";
import { BRAND, MARK } from "../brand";
import { useI18n } from "../i18n";
import type { WorkspaceProps } from "../pages/DemoPage";
import { Block, Button, Chip, ErrorNote, Spinner } from "./common";

interface Customer { id: string; name_ar: string; name_en: string; city: string }
interface Event { type: string; name?: string; args?: Record<string, unknown>; result?: Record<string, unknown>; ms?: number; code?: string; to?: string; stage?: string; rail?: string; text?: string; verified?: boolean }
interface TurnOut { reply: string; blocked: boolean; events: Event[]; audio_wav_b64: string | null; verified: boolean; trace: TraceStep[]; total_ms: number }
// "note" is something that happened outside the conversation, such as a code entered on the keypad
interface Msg { role: "user" | "agent" | "note"; text: string; at: string; blocked?: boolean; ms?: number; voice?: boolean }
interface Card { last4: string; type: string; status: string }
interface State { verified: boolean; cards: Card[] | null; tickets: { id: string; category: string }[]; handoffs: { id: string; status: string }[] }
type Channel = "whatsapp" | "ivr";
// Each channel is its own conversation with its own session: a WhatsApp chat is not the transcript of a call
interface Conv { sid: string | null; msgs: Msg[]; lane: Event[]; sms: Event | null; state: State | null }
const EMPTY: Conv = { sid: null, msgs: [], lane: [], sms: null, state: null };

const L = {
  en: { customer: "Customer", start: "New conversation", say: "Type what the customer says…", send: "Send", voice: "Speak replies", mic: "Hold to talk",
        listen: "Listen", lane: "Tool-call lane", phone: "Customer's phone", enterCode: "Enter the code", script: "Demo script", account: "Account state", verified: "Verified",
        notVerified: "Not verified", stop: "STOP · guardrail blocked this turn", working: "Agent is thinking…", noSms: "No messages yet", recording: "Recording… release to send",
        micBlocked: "Microphone needs HTTPS or localhost; use typing or the script buttons.",
        whatsapp: "WhatsApp chat", ivr: "IVR call", agent: "NBE Virtual Agent", online: "online", inCall: "Call in progress", keypad: "Secure keypad",
        codeSent: "Code entered on the secure keypad: it went to the bank, not to the AI", bankChecked: "Bank checked the code itself; the AI saw only the result" },
  ar: { customer: "العميل", start: "محادثة جديدة", say: "اكتب ما يقوله العميل…", send: "إرسال", voice: "نطق الردود", mic: "اضغط مع الاستمرار للتحدث",
        listen: "استمع", lane: "مسار الإجراءات", phone: "هاتف العميل", enterCode: "أدخل الرمز", script: "سيناريو العرض", account: "حالة الحساب", verified: "تم التحقق",
        notVerified: "لم يتم التحقق", stop: "إيقاف · منعت الحماية هذا الطلب", working: "المساعد يفكر…", noSms: "لا رسائل بعد", recording: "جارٍ التسجيل… اترك للإرسال",
        micBlocked: "الميكروفون يتطلب HTTPS أو localhost؛ استخدم الكتابة أو أزرار السيناريو.",
        whatsapp: "محادثة واتساب", ivr: "مكالمة IVR", agent: "المساعد الافتراضي للبنك الأهلي", online: "متصل الآن", inCall: "المكالمة جارية", keypad: "لوحة أرقام آمنة",
        codeSent: "أُدخل الرمز من لوحة الأرقام الآمنة: أُرسل إلى البنك لا إلى الذكاء الاصطناعي", bankChecked: "البنك تحقق من الرمز بنفسه؛ الذكاء الاصطناعي رأى النتيجة فقط" },
};
const SCRIPT = BRAND.locale.d4Script;   // per bank (brand/brand.json): local dialect and wording
const STEP_LABEL = { ar: ["فقدان البطاقة", "إدخال الرمز", "تأكيد الإيقاف", "شكوى", "محاولة تلاعب", "طلب موظف"], en: ["Lost card", "Enter the code", "Confirm block", "Complaint", "Jailbreak", "Ask for a human"] };

export default function D4Agent({ onTrace }: WorkspaceProps) {
  const { lang } = useI18n();
  const l = L[lang];
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [cid, setCid] = useState("C0001");
  const [convs, setConvs] = useState<Record<Channel, Conv>>({ whatsapp: EMPTY, ivr: EMPTY });
  const [q, setQ] = useState("");
  const [pin, setPin] = useState("");                               // digits typed on the keypad
  const [channel, setChannel] = useState<Channel>("whatsapp");
  const { sid, msgs, lane, sms, state } = convs[channel];
  // Updates name their channel, so a reply still lands in the conversation that asked for it after a switch
  const patch = (ch: Channel, change: (c: Conv) => Partial<Conv>) => setConvs((all) => ({ ...all, [ch]: { ...all[ch], ...change(all[ch]) } }));
  const [voice, setVoice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const player = useRef<HTMLAudioElement | null>(null);
  const [speaking, setSpeaking] = useState<number | null>(null);    // index of the message being read aloud
  const wa = channel === "whatsapp";
  const spoken = voice || !wa;                                      // a phone call is always spoken

  useEffect(() => { getJSON<Customer[]>("/api/d4/customers").then(setCustomers).catch((e) => setError(String(e))); }, []);
  // Braces matter: newer Chrome returns a Promise from scrollIntoView, which React would call as a cleanup function
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [msgs, busy]);

  const now = () => new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  // The customer interrupts the voice by starting to talk or by sending a message; typing alone does not
  const hush = () => { player.current?.pause(); setSpeaking(null); };
  const start = async (ch: Channel = channel) => {
    const s = await postJSON<{ session_id: string }>("/api/d4/session", { customer_id: cid });
    hush(); setPin("");
    patch(ch, () => ({ ...EMPTY, sid: s.session_id }));
    return s.session_id;
  };
  const refresh = async (ch: Channel, id: string) => { const st = await getJSON<State>(`/api/d4/state/${id}`); patch(ch, () => ({ state: st })); };
  const switchTo = (ch: Channel) => { hush(); setPin(""); setChannel(ch); };

  // One voice at a time: a spoken reply and the listen buttons share the player
  const play = (wavB64: string, done?: () => void) => {
    player.current?.pause();
    const a = new Audio(`data:audio/wav;base64,${wavB64}`);
    player.current = a;
    a.onended = () => done?.();
    a.play().catch(() => done?.());
  };
  const listen = async (i: number, text: string) => {
    player.current?.pause();
    if (speaking === i) { setSpeaking(null); return; }      // a second click stops it
    setSpeaking(i); setError("");
    try {
      const r = await postJSON<{ audio_wav_b64: string }>("/api/d4/speak", { text });
      play(r.audio_wav_b64, () => setSpeaking((cur) => (cur === i ? null : cur)));
    } catch (e) { setError((e as Error).message); setSpeaking(null); }
  };
  const listenButton = (i: number, text: string) => (
    <button type="button" data-test="listen" onClick={() => listen(i, text)} title={l.listen} aria-label={l.listen}
            className={`rounded-full px-1.5 text-sm leading-none ${speaking === i ? "animate-pulse" : "opacity-60 hover:opacity-100"}`}>
      {speaking === i ? "⏹" : "🔊"}
    </button>
  );

  const turn = async (payload: { text?: string; audio_b64?: string; code?: string }, shown?: Pick<Msg, "role" | "text">) => {
    if (busy) return;
    hush();
    setBusy(true); setError("");
    const ch = channel;
    const id = sid ?? (await start(ch));
    if (shown) patch(ch, (c) => ({ msgs: [...c.msgs, { ...shown, at: now() }] }));
    try {
      const r = await postJSON<TurnOut>("/api/d4/turn", { session_id: id, voice: spoken, ...payload });
      const transcript = r.events.find((e) => e.type === "transcript")?.text;
      const s = r.events.find((e) => e.type === "sms");
      patch(ch, (c) => ({
        msgs: [...c.msgs, ...(transcript ? [{ role: "user" as const, text: transcript, voice: true, at: now() }] : []),
               { role: "agent" as const, text: r.reply, blocked: r.blocked, ms: r.total_ms, at: now() }],
        lane: [...c.lane, ...r.events.filter((e) => e.type !== "transcript")],
        sms: s ?? c.sms,
      }));
      onTrace(r.trace);
      if (r.audio_wav_b64) { setSpeaking(null); play(r.audio_wav_b64); }
      await refresh(ch, id);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const say = (text: string) => { setQ(""); turn({ text }, { role: "user", text }); };
  // The keypad sends the code as its own field: the service passes it to the bank and never to a model
  const enterCode = (code: string) => { setPin(""); turn({ code }, { role: "note", text: l.codeSent }); };
  const scriptStep = (i: number) => {
    const raw = SCRIPT[lang][i];
    if (raw === "{code}") { if (sms?.code) enterCode(sms.code); return; }
    say(raw);
  };

  const startRec = async () => {
    hush();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const r = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const buf = await new Blob(chunks, { type: r.mimeType }).arrayBuffer();
        const bytes = new Uint8Array(buf);
        let bin = "";
        for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));   // chunked: no stack overflow
        const b64 = btoa(bin);
        turn({ audio_b64: b64 });
      };
      r.start(); setRec(r);
    } catch { setError(l.micBlocked); }
  };
  const stopRec = () => { rec?.stop(); setRec(null); };
  const micButton = (cls: string) => (
    <button type="button" onMouseDown={startRec} onMouseUp={stopRec} onTouchStart={startRec} onTouchEnd={stopRec} title={l.mic}
            className={`rounded-full ${cls} ${rec ? "animate-pulse bg-status-stop text-white" : wa ? "bg-[#25D366] text-white" : "bg-brand text-white"}`}>🎙️</button>
  );

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
      <section className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white p-3">
          <span className="text-sm">{l.customer}</span>
          <select value={cid} onChange={(e) => setCid(e.target.value)} className="rounded-lg border border-line bg-white px-2 py-1.5 text-sm" dir="auto">
            {customers.map((c) => <option key={c.id} value={c.id}>{c.id} · {lang === "ar" ? c.name_ar : c.name_en}</option>)}
          </select>
          <Button variant="ghost" onClick={() => start()}>{l.start}</Button>
          <div className="flex overflow-hidden rounded-full ring-1 ring-line">
            {(["whatsapp", "ivr"] as const).map((c) => (
              <button key={c} type="button" data-test={`channel-${c}`} onClick={() => switchTo(c)}
                      className={`px-3 py-1.5 text-xs font-semibold ${channel === c ? "bg-brand text-white" : "bg-white text-brand"}`}>
                {c === "whatsapp" ? "💬" : "📞"} {l[c]}
              </button>
            ))}
          </div>
          <label className="ms-auto flex items-center gap-1.5 text-sm"><input type="checkbox" checked={spoken} disabled={!wa} onChange={(e) => setVoice(e.target.checked)} />🔊 {l.voice}</label>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <span className="self-center text-xs font-semibold uppercase text-ink-soft">{l.script}</span>
          {STEP_LABEL[lang].map((label, i) => (
            <button key={i} data-test="script-step" onClick={() => scriptStep(i)} disabled={busy || (i === 1 && !sms)}
                    className={`rounded-full px-3 py-1 text-xs font-semibold disabled:opacity-40 ${i === 4 ? "bg-status-stop/10 text-status-stop" : "bg-white text-brand ring-1 ring-line"}`}>
              {i + 1}. {label}
            </button>
          ))}
        </div>

        {/* The conversation in the look of its channel: a WhatsApp chat, or a phone call with its transcript */}
        <div className="flex min-h-[26rem] flex-col overflow-hidden rounded-xl border border-line bg-white">
          <div className={`flex items-center gap-3 px-4 py-2.5 text-white ${wa ? "bg-[#075E54]" : "bg-ink"}`}>
            {wa ? <img src={MARK} alt="" className="size-9 rounded-full bg-white object-contain p-1" />
                : <span className="flex size-9 items-center justify-center rounded-full bg-white/15 text-lg">📞</span>}
            <div className="leading-tight">
              <div className="text-sm font-bold">{l.agent}</div>
              <div className="flex items-center gap-1.5 text-xs opacity-80">
                {!wa && <span className="size-2 animate-pulse rounded-full bg-status-stop" />}{wa ? l.online : l.inCall}
              </div>
            </div>
          </div>
          <div className={`flex-1 space-y-2 overflow-y-auto p-4 ${wa ? "bg-[#ECE5DD]" : "bg-canvas"}`}>
            {msgs.map((m, i) => m.role === "note" ? (
              <div key={i} className="mx-auto w-fit max-w-[90%] rounded-lg bg-[#FFF3C4] px-3 py-1 text-center text-xs text-ink shadow-sm" dir="auto">🔐 {m.text}</div>
            ) : m.role === "user" ? (
              <div key={i} className={`ms-auto w-fit max-w-[80%] rounded-lg px-3 py-1.5 text-sm shadow-sm ${wa ? "bg-[#DCF8C6] text-ink" : "bg-brand text-white"}`}>
                <span dir="auto">{m.voice && "🎙️ "}{m.text}</span>
                <span className="ms-2 inline-flex items-center gap-1 align-bottom text-[10px] opacity-70">
                  {m.at}{wa && <span className="text-sky-600">✓✓</span>}{listenButton(i, m.text)}
                </span>
              </div>
            ) : (
              <div key={i} data-test="agent-reply" className={`w-fit max-w-[85%] rounded-lg px-3 py-1.5 text-sm shadow-sm ${m.blocked ? "border-2 border-status-stop bg-status-stop/5" : "bg-white"}`}>
                {m.blocked && <div className="mb-1 text-xs font-bold text-status-stop">⛔ {l.stop}</div>}
                <p dir="auto" className="whitespace-pre-wrap text-ink">{m.text}</p>
                <div className="mt-0.5 flex items-center gap-2 text-[10px] text-ink-soft">
                  <span>{m.at}</span>{m.ms !== undefined && <span>{(m.ms / 1000).toFixed(1)} s</span>}{listenButton(i, m.text)}
                </div>
              </div>
            ))}
            {busy && <Spinner label={l.working} />}
            <div ref={end} />
          </div>
          <ErrorNote error={error} />
          {!wa && <div className="flex justify-center border-t border-line bg-white pt-3">{micButton("size-16 text-2xl shadow")}</div>}
          <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) say(q); }} className={`flex gap-2 p-3 ${wa ? "bg-[#F0F0F0]" : "bg-white"}`}>
            {wa && micButton("px-4 text-lg")}
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={rec ? l.recording : l.say} dir="auto" className="flex-1 rounded-full border border-line bg-white px-4 py-2 text-sm" />
            <Button type="submit" disabled={busy || !q.trim()}>{l.send}</Button>
          </form>
        </div>
      </section>

      <aside className="space-y-4">
        <div className="rounded-[2rem] border-8 border-ink bg-white p-4 shadow-lg">
          <div className="mb-2 text-center text-xs font-semibold text-ink-soft">📱 {l.phone}</div>
          {sms ? (
            <div className="rounded-2xl bg-canvas p-3 text-sm">
              <div className="text-xs text-ink-soft">{BRAND.short} · {sms.to}</div>
              <div dir="rtl" className="mt-1">رمز التحقق الخاص بك هو</div>
              <div className="my-1 text-center text-3xl font-bold tracking-[0.4em] text-brand">{sms.code}</div>
              <div className="text-xs text-ink-soft">لا تشارك هذا الرمز مع أي شخص. (mock SMS)</div>
              {/* The keypad: what is typed here goes to the bank's check, not into the conversation */}
              <form onSubmit={(e) => { e.preventDefault(); if (pin) enterCode(pin); }} className="mt-3 border-t border-line pt-2">
                <div className="mb-1 text-xs font-semibold text-ink-soft">🔐 {l.keypad}</div>
                <div className="flex gap-2">
                  <input data-test="keypad" value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 4))} inputMode="numeric" placeholder="• • • •" dir="ltr"
                         className="w-full rounded-lg border border-line bg-white px-3 py-1.5 text-center text-lg font-bold tracking-[0.4em]" />
                  <Button type="submit" disabled={busy || pin.length < 4}>{l.enterCode}</Button>
                </div>
              </form>
            </div>
          ) : <p className="py-6 text-center text-sm text-ink-soft">{l.noSms}</p>}
        </div>

        <div className="rounded-xl border border-line bg-white p-4">
          <h3 className="mb-2 text-sm font-bold uppercase text-ink-soft">{l.lane}</h3>
          <ol className="max-h-80 space-y-2 overflow-y-auto">
            {lane.filter((e) => e.type !== "sms").map((e, i) => e.type === "guardrail" ? (
              <li key={i} className="rounded-lg bg-status-stop px-3 py-2 text-xs font-bold text-white">⛔ STOP · {e.stage} guardrail · {e.rail}</li>
            ) : e.type === "otp" ? (
              <li key={i} data-test="otp-check" className={`rounded-lg px-3 py-2 text-xs font-semibold ${e.verified ? "bg-brand/10 text-brand" : "bg-status-stop/10 text-status-stop"}`} dir="auto">
                🔐 {l.bankChecked} · {e.verified ? "✓" : "✗"} · {e.ms} ms
              </li>
            ) : (
              <li key={i} className="rounded-lg bg-canvas px-3 py-2 text-xs">
                <div className="font-mono font-semibold text-brand" dir="ltr">🔧 {e.name}({Object.entries(e.args ?? {}).map(([k, v]) => `${k}=${v}`).join(", ")}) · {e.ms} ms</div>
                <pre dir="ltr" className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap text-[11px] text-ink">{JSON.stringify(e.result)}</pre>
              </li>
            ))}
          </ol>
        </div>

        <Block label={l.account}>
          <Chip tone={state?.verified ? "green" : "neutral"}>{state?.verified ? l.verified : l.notVerified}</Chip>
          {state?.cards?.map((c) => <div key={c.last4} className="mt-1 text-xs">💳 •••• {c.last4} · {c.type} · <b className={c.status === "blocked" ? "text-status-stop" : "text-brand"}>{c.status}</b></div>)}
          {state?.tickets.map((t) => <div key={t.id} className="mt-1 text-xs" dir="auto">🎫 {t.id} · {t.category}</div>)}
          {state?.handoffs.map((h) => <div key={h.id} className="mt-1 text-xs">🙋 {h.id} · {h.status}</div>)}
        </Block>
      </aside>
    </div>
  );
}
