# Talk tracks: seven demos for NBE

One page per demo: the setup line, what to click, what to say, the honest caveat, and likely questions. Each demo takes about 4 to 6 minutes. Open the "Show the work" drawer at the end of any demo: it lists every step behind the answer, the model used and the timings.

**Opening (1 minute).** "Everything you'll see runs on this one Dell Pro Max with GB10, with no internet connection: models, data and all seven demos. It's a single-user proof of concept: the point is what the AI can do with NBE's use cases, not production throughput, which we size separately on PowerEdge. All data is synthetic."

---

## D1 · Doc verification for credit lending

**Setup.** "A loan officer receives a pack: ID, utility bill, employer letter and bank statement, plus a commercial register and invoice for SMEs."

**Click.** A01 → Verify pack (about 25 s). Then open the HR letter tile.

**Say.**
- The vision model reads every field, Arabic included, with no OCR templates.
- Then two kinds of evidence. Image forensics found a region of the HR letter with no scanner noise, which is where someone typed over the salary. The cross-checks found that the salary on the letter, 26,300, doesn't match the bank statement's salary credits of 12,800 or the declared salary.
- Click the red box on the scan: that's the exact area.
- The officer decides, and the decision is logged.

**Then A04.** It's a clean pack with one flag: a utility bill re-saved by a phone scanning app. Clear it with "Documents OK" and a note. "The system raises flags; it never decides. This is why."

**Caveat.** It flags for review and is never fraud-proof. On our 40 synthetic documents, all 10 forgeries were flagged, and the other flags were the partner document in a mismatch plus the planned false positive.

**Q&A.**
- *Do you need labelled forgeries?* No. We dropped the ViT forgery classifier for exactly that reason; these checks need no training data.
- *Real scans?* The next step is NBE-masked samples, approved in writing.

---

## D2 · Chat with Document

**Setup.** "A branch employee needs an answer from procedures that change often."

**Click.** The first suggested question (card replacement fee). Then the Egyptian-dialect question about transfer limits. Then "Can the replacement card be posted to the customer's home?"

**Say.**
- Every sentence carries a citation. Click a chip to see the exact section.
- It uses the current version, and the side panel shows what changed from the previous one: the fee went from 75 to 100.
- Asked in dialect, it answers in clear Arabic from the right procedure.
- The last question isn't covered by any procedure, so it says so instead of guessing.

**Caveat.** It answers only from the indexed procedures. On our 52-question golden set it got 51 right, including all "what changed" and "not found" questions.

**Q&A.**
- *Scanned Arabic PDFs?* Text-layer PDFs scramble Arabic, so Arabic PDFs are read page by page by the vision model.
- *Updates?* Re-ingest the new version; the comparison is automatic.

---

## D3 · Campaigns & Offers

**Setup.** "Marketing wants a personalised offer for a segment, without touching live customer data."

**Click.** Young professionals → Build campaign (about 30 s). Then tick "Stress-test compliance" and build again.

**Say.**
- The interest profile comes from 50,000 synthetic transactions: which categories this segment over-spends on compared with everyone.
- The merchant match is a partner merchant where they actually spend.
- The copy comes in Arabic and English for SMS, email and an Egyptian-dialect social post, every SMS under 160 characters.
- The banner is generated on the box; the Arabic headline is overlaid in the design.
- The A/B plan is sized to the real audience: with 1,224 opted-in customers, it can detect a 65% lift.
- Stress test: we planted "guaranteed 100%". Compliance caught it and fixed it before anything was shown.

**Caveat.** It's a mock-up on synthetic data. Merchant contracts and deal costing are out of scope.

---

## D4 · AI Virtual Agent

**Setup.** "A customer contacts the bank: they've lost their card."

**Click.** Script buttons 1 to 6 in order, or speak if the browser runs on the GB10. Tick "Speak replies" for voice.

**Say.**
1. Lost card: it sends an OTP straight away. The code appears on the customer's phone, never in the chat.
2. Enter the code on the phone's keypad: it goes to the bank's check, not to the AI. The lane shows the bank's verdict; the agent is told only "verified", finds the card and asks before blocking, because that's irreversible.
3. Confirm: the card is blocked in the bank system (a mock). Watch the tool lane and the account state.
4. Complaint: a ticket is logged with a number.
5. Jailbreak, in Egyptian dialect, asking for another customer's data: STOP. The guardrail blocks it before the model even sees it.
6. Human: handed off with a summary.

**Caveat.** All banking actions hit mock APIs. It handles Modern Standard Arabic first and dialect as a bonus. A backup video exists for this demo.

**Q&A.**
- *WhatsApp or IVR?* The same backend; those are channel integrations for later.
- *Why ask before blocking?* Irreversible actions need consent.

---

## D5 · Legal Documents Summarisation

**Setup.** "Legal reviews a contract that's supposed to follow NBE's approved template."

**Click.** C01 → Analyze (about 45 s). Open article 6 in the template comparison. Then R02 (a ruling).

**Say.**
- The summary is built part by part and then combined, not from one huge prompt.
- Each clause comes with a verbatim quote, and a ✓ means the quote was found word for word in the document.
- The template comparison: only article 6 deviates. The default period dropped from 90 to 60 days, the 15-day notice disappeared, and the penalty rose from at most 2% to 3%. All are flagged high risk.
- The ruling summary gets the parties, amounts and the 60/40 split of liability right.

**Caveat.** The clauses and rulings are synthetic; NBE legal validates outputs before demo day. All planted deviations in our five test contracts were found.

---

## D6 · NBE AI Assistant

**Setup.** "One assistant for every employee task, with the right model for each."

**Click.** The suggested prompts in turn: email, translation, summary, code. Attach a PDF and ask about it.

**Say.**
- The model-selection panel shows the language, the task, the chosen model and why.
- Drafting and translation go to the fast workhorse. Code goes to gpt-oss-120b, with answers grounded in the real pandas/numpy documentation to avoid invented APIs.
- Dataiku connects through LLM Mesh to the same endpoint (`/v1`, model `nbe-auto`).

**Optional hero moment.** `make hero` beforehand. If it's off, the panel shows the fallback honestly.

**Caveat.** The Dataiku version and host are still to be confirmed with NBE.

---

## D7 · Complaints Personalisation

**Setup.** "Complaints arrive from email, social media, chat and calls, in Arabic, dialect and English."

**Click.** Triage all (about 75 s). Pick a severity-4 complaint. Edit a word in the draft and approve it. Then open the Trends and Accuracy tabs.

**Say.**
- Each complaint gets a topic, severity, SLA and team.
- Similar past complaints are shown for context.
- The draft is empathetic, makes no promises, and passed the policy check and the output guardrail.
- Nothing is sent until a person approves it.
- Trends: ten themes found across 500 complaints.
- Accuracy: 94% topic agreement on 100 held-out complaints, zero-shot, with no training.

**Caveat.** The policy rules are placeholders until NBE shares its real ones, and the labels are synthetic.

---

## Do not claim

Production throughput, regulatory approval, unmeasured accuracy, or that GB10 replaces data-centre infrastructure.
