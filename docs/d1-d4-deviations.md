# D1 and D4: deviations from the Dell GB10 reference design, and why

| | |
|---|---|
| **Subject** | Doc Verification for Credit Lending (D1) and AI Virtual Agent (D4) |
| **Reference** | *Seven AI Use Cases, Running Live on One Dell Pro Max with GB10*, customer presentation, October 2026 (30 slides), referred to below as "the deck" |
| **Compared with** | Branch `Efada_AI_Team`, commits `f5c11a9`, `857a39a`, `5ebcde2` (the "workstation build") |
| **Prepared by** | Efada AI Team |
| **Date** | 11 October 2026 |
| **Status** | For review. Section 8 lists what is not yet measured. |

---

## Models at a glance

**D1 · Document verification**

| Job | Deck (GB10) | Efada build | Why |
|---|---|---|---|
| Read the document | Gemma 4 26B (general, no training) | Qwen3-VL-8B + fine-tuned adapter v18 | Trained on Egyptian documents; runs on the machine, so real documents never leave it |
| Find forgery | OpenCV checks + rules (no model) | Same, re-tuned for real photos | The old noise check gave false alarms on 64 of 80 real photos |
| Write the explanation | Gemma 4 26B | No model (built from the flags) | Nothing can be invented, and no field value is sent out |

**D4 · Virtual agent**

| Job | Deck (GB10) | Efada build | Why |
|---|---|---|---|
| The brain (LLM) | Gemma 4 26B-A4B, on the box | Same model, hosted on OpenRouter | It needs 35 GB; the workstation GPU has 32 GB. Temporary: goes back on the box for the GB10 |
| Speech to text | Whisper large-v3 | QwenCleo-ASR | Built for Egyptian Arabic mixed with English |
| Text to speech | Piper (Jordanian voice) | VoiceTut-TTS | Egyptian voice |
| Knowledge search | bge-m3 + bge-reranker-v2-m3 | Same | No change |
| Safety | NeMo Guardrails | Same | No change |

Three models swapped (reader, speech to text, text to speech), one moved (the LLM), the rest unchanged.

---

## 1. Purpose

The deck specifies, for each of NBE's seven use cases, the models and controls that run on the Dell Pro Max with GB10. For D1 and D4 the Efada build differs from that specification in the document reader, the voice models, where the language model runs, and several agent and verification rules.

This document lists every difference, states the reason for each, gives the measurements that support it, and states plainly where a change is a constraint of the development machine and not an improvement. D2, D3, D5, D6 and D7 are unchanged and are out of scope.

## 2. Summary of deviations

| # | Demo | Role | Deck, as built on GB10 | Efada build | Nature of the change |
|---|---|---|---|---|---|
| 1 | D1 | Document reading | Gemma 4 26B-A4B vision, zero-shot (slides 13, 19) | Qwen3-VL-8B with fine-tuned adapter v18, on the machine (`nbe-docvlm`) | Model replaced |
| 2 | D1 | Input documents | 40 synthetic SPECIMEN documents | Synthetic packs kept; added an upload flow for an applicant's own documents (image or PDF) | Scope extended |
| 3 | D1 | Image forensics | Noise consistency, duplicate stamps, metadata, ELA heatmap | On uploads: copied region, typed-over patch, content added after first save, stamps, metadata, PDF record. Noise check off for uploads | Checks replaced for real photos |
| 4 | D1 | Cross-document rules | Names, address, salary, employer, dates, ID digits, register expiry, invoice maths | The same, plus ID-number self-check, per-field confidence, "confirm the reading first", officer correction, second reading | Extended |
| 5 | D1 | Explanation of the verdict | Written by the language model | Written from the flags, no model | Model removed from the step |
| 6 | D4 | Language model | Gemma 4 26B-A4B, FP8, on the GB10 | **The same model, hosted (OpenRouter), four pinned providers** | Location changed |
| 7 | D4 | Speech to text | Whisper large-v3 (slide 15) | QwenCleo-ASR, on the machine | Model replaced |
| 8 | D4 | Text to speech | Piper on CPU, voice `ar_JO-kareem` (slide 15) | VoiceTut-TTS (Egyptian Arabic and English), on the machine, with a pronunciation table | Model replaced |
| 9 | D4 | One-time code | Code withheld from the model | Code never reaches any model: digits are masked, the bank checks the entry, the agent receives only the verdict | Control strengthened |
| 10 | D4 | Card block | Agent instructed to confirm | Confirmation enforced in code before `block_card` runs | Control strengthened |
| 11 | D4 | Reply language | Follows the customer's language | Arabic replies in Egyptian colloquial Arabic | Behaviour changed |
| 12 | D4 | Knowledge base | Synthetic articles | 16 of 41 articles are NBE's public product information, with source and date | Data changed |
| 13 | D4 | Channels | One chat or voice screen | WhatsApp and IVR conversations, keypad for the code | Interface extended |

Unchanged in both demos: NeMo Guardrails on input and output, the tool set, the mock bank, bge-m3 and bge-reranker-v2-m3, the audit log, the trace panel, and the rule that a person takes every material decision.

**Deviation 6 is the only one that conflicts with a stated principle of the deck** ("Nothing leaves the box", slide 3). It is a constraint of the development workstation, it is not proposed for the customer demonstration, and section 5.1 and section 9 describe how it is reversed.

## 3. Context: why a workstation build exists

The deck's design is sized for 128 GB of unified memory. Development of D1 and D4 was done on a workstation with one 32 GB GPU that is shared with other work.

- The workhorse alone was measured at 35.4 GB on the GB10 (25.7 GB of weights). It does not fit in 32 GB.
- The workstation build is therefore an overlay (`docker-compose.local.yml`), not a fork. Its services answer under the GB10 service names (`nbe-asr`, `nbe-tts`, `nbe-embed`, `nbe-rerank`), and the demos still address models by role (`workhorse`, `vision`, `embed`). The D1 and D4 application code is the same on both platforms.

The changes below fall into two groups: those forced by this hardware (deviation 6), and those made because the deck's own open items or the team's assets allowed a better result (all others).

## 4. D1: Doc Verification for Credit Lending

### 4.1 Document reader: Gemma 4 vision replaced by fine-tuned Qwen3-VL-8B (deviation 1)

**What the deck specifies.** Gemma 4 26B-A4B reads every field directly, "with zero per-template configuration" and adding "zero second model to memory" (slide 13). The deck gives the reason for not training: "No labelled NBE forgeries, contracts, or customer complaints exist yet" (principle 4, slide 11).

**What was built.** Uploaded documents are read by Qwen3-VL-8B-Instruct with LoRA adapter v18, served by the code of the project that trained and measured it, mounted read-only so that prompts, image sizing and ID-number handling are exactly those that were measured.

**Reasons.**

1. **The premise of principle 4 does not hold for document reading.** The team holds a labelled set of Egyptian documents and an adapter already trained on it, covering 18 document types including the national ID (front and back), HR letter, utility and electricity bills, commercial register and bank statement. Principle 4 still holds for forgery detection, where no labelled forgeries exist, and there the deck's approach (rules and image forensics, no trained classifier) is kept.
2. **It is measured on real documents.** The deck states that accuracy on real data is "zero tested to date" (slide 27). The adapter has figures on real photographs (section 4.5).
3. **It reports how sure it is of each field.** D1 uses this to hold back a mismatch that rests on an uncertain reading until the officer confirms it. The zero-shot reader gives no such signal, so every misreading becomes a flag against the applicant.
4. **It keeps real documents on the machine.** On the workstation the only available Gemma is hosted. A real applicant's ID or salary letter must not be sent to a hosted model. `nbe-docvlm` has no route out.
5. **It is within NBE's own candidate list.** NBE's deck names Qwen-VL among its vision candidates (slide 12). The change returns to a model family NBE proposed, in a newer version and adapted to Egyptian documents.

**Cost.** A second model in memory: about 17.5 GB on the workstation GPU. This departs from principle 3 ("one shared workhorse"). On the GB10 it would sit beside the workhorse within the roughly 100 GB usable in show mode by arithmetic, but this has not been run on the GB10 (section 8).

### 4.2 Real documents through an upload flow (deviation 2)

The deck's D1 runs on generated SPECIMEN documents and says so: the result "proves technical pipeline validity" (slide 19). A lending officer's question is whether it reads the papers on the desk. The build adds a second tab in which the officer opens a loan file, types what the applicant declared, uploads each document and names its type. The synthetic packs remain as the first tab.

Controls on this flow: uploads never reach the model gateway; the audit log and the trace carry no field value; images are stored in a git-ignored folder and deleted with their loan file. The deck's rule that real bank data enters "only as masked samples approved in writing" (slide 10) is unaffected: the flow makes real documents possible, it does not authorise them.

The officer chooses the document type. Automatic detection was built and measured (right on 113 of 133 pages, no answer on 20, wrong on none) and removed, so that no page is checked under a type nobody confirmed.

### 4.3 Image checks rebuilt for photographs (deviation 3)

The deck's noise-consistency check was tuned on generated scans. Measured on 80 untouched real photographs it raised a false alarm on 64. It is switched off for uploads and replaced by three checks measured on the same 80 photographs and on copies with planted edits:

| Check | False alarms | Planted edits caught |
|---|---|---|
| Copied region (exact copy, grain included) | 0 of 80 | a copied block on 23 |
| Typed-over patch (writing without the surrounding camera noise) | 4 of 80 | a typed-over value on 14 |
| Content added after the first JPEG save | 1 of 80 | 23 to 26 per kind of edit |
| All three together | | typed-over 35, careful typed-over 23, copied block 37, pasted block 28 |

A PDF is also checked for the program that wrote it, a later modification date and more than one save.

Stated limit: about half to two thirds of planted edits on real photographs are not caught by the image checks alone, and 33 of the 80 photographs were too heavily compressed for two of the checks to apply (the screen says so). The checks are indicators for a reviewer, which is the position the deck already takes.

### 4.4 Rules, confidence and the written summary (deviations 4 and 5)

- **ID number checked against itself** (length, birth date, gender) and front against back, before it is compared with anything else.
- **A mismatch resting on an unsure field asks the officer to confirm the reading first.** The officer can correct any field and the checks run again without re-reading. This puts the deck's "a person decides" control one step earlier, at the reading and not only at the verdict.
- **Second reading.** A page with unsure text fields is read again as two enlarged halves. On 130 labelled pages (690 fields), correct fields rose from 89.0% to 90.3%.
- **Fields the adapter was not trained on** (salary rows of a statement, a letter's date, an invoice) are read by the plain base model and labelled "general reading" on screen. On 13 statements with known rows: salary rows right 37 times in 39, paying company 10 times in 13, so the company is always confirmed by the officer before it counts.
- **The summary is assembled from the flags, with no language model.** On the workstation this keeps field values away from the hosted model. On any platform it removes the possibility of a summary that says something the flags do not.

### 4.5 Results compared

| Measure | Deck, GB10 | Efada build, workstation |
|---|---|---|
| Planted forgeries flagged, 40 synthetic documents | 10 of 10 | 10 of 10 |
| Planted forgeries flagged, upload flow, 27 documents | not applicable | 10 of 10 |
| Genuine documents flagged | every other flag is the partner in a mismatch or the planned false positive | the same: 3 of 17 (upload), 6 of 30 (packs) |
| Time | about 25 s per pack | 32 s per pack; 33 s per three-document file |
| Reading accuracy on real documents | not tested | national ID front 92.9% of 196 fields (49 photos); back 92.3% of 271 fields (55 photos) |
| Reading accuracy on held-out generated pages | not reported per field | HR letter 99.9% of 1,278; utility bill 100% of 485; electricity bill 90.5% of 348; commercial register 87.9% of 439 |

The build is 7 to 8 seconds slower per pack. The benchmark pages for the upload flow are drawn and made to look photographed; they are not photographs.

## 5. D4: AI Virtual Agent

### 5.1 The language model is hosted on the workstation (deviation 6)

**What the deck specifies.** "Zero external cloud API calls" and a network cable that can be unplugged in front of the audience (slide 3).

**What was built.** The same model, Gemma 4 26B-A4B, reached through OpenRouter. Only the model gateway has a route out; every other container stays on the internal network.

**Reason.** The model does not fit the development GPU (section 3). The alternative was a smaller local model, which would have meant developing and testing the agent against a different model from the one the deck selected in the Arabic gate. Keeping the model and moving its location was judged the smaller departure.

**What leaves the machine, and what does not.**

| Leaves, to the hosted model | Stays on the machine |
|---|---|
| The customer's typed or transcribed message, with one-time-code digits masked | Audio in and out |
| Tool results from the mock bank (synthetic customers only) | The one-time code and its check |
| Knowledge-base passages (synthetic, or NBE's public web pages) | Every D1 upload, reading and check |
| Guardrail self-check prompts | Embeddings, reranking, the vector store, the audit log |

**Consequences that must be stated to the customer.**

- The workstation build cannot support the deck's air-gap claim, and must not be presented as if it did.
- Only synthetic data may be used in anything that calls the hosted model.
- The hosted providers do not behave alike. Four were pinned after passing D4's tool-calling trials, with no fallback to others, and D4 handles the hosted model's defects in code (a reply written beside a tool call, a tool call returned as raw text, planning notes, a reply in the wrong language). Three of the four serve the model at BF16 and one at FP8, so results may differ slightly from the GB10's FP8 build.

**Reversal.** One file. `config/litellm.yaml` points `workhorse` at the local vLLM server; `config/litellm.local.yaml` points it at the hosted one. No demo code changes.

### 5.2 Speech to text: Whisper large-v3 replaced by QwenCleo-ASR (deviation 7)

The deck lists "Egyptian dialect voice" as an open item (slide 27), and the build plan calls Egyptian dialect in voice "a bonus". D4's customers speak Egyptian Arabic with English banking terms mixed in ("الـ OTP", "credit card"). QwenCleo-ASR is built for that mixture; Whisper large-v3 is a general multilingual model.

Evidence: the choice rests on the model's stated design and on the team's own listening tests. **No word-error-rate comparison with Whisper has been run** (section 8).

### 5.3 Text to speech: Piper replaced by VoiceTut-TTS (deviation 8)

The deck chooses Piper because it "runs on CPU, saving GPU memory for LLM" (slide 15). The build chooses the voice the customer hears over the memory saved.

1. **Piper's Arabic voice is Jordanian** (`ar_JO-kareem`). An NBE customer hears a non-Egyptian accent from their own bank.
2. **The reference build recorded the defect itself.** Finding 6 of the build plan: Piper's Arabic "is understandable but not perfect without diacritics"; a round trip returned «الاعتمانية» for «الائتمانية» ("credit").
3. **Banking speech needs control over pronunciation.** `data/seed/d4/pronunciation.ini` maps written terms to spoken forms per language (`OTP`, `EGP`), spells amounts the Egyptian way, and reads card endings, codes, ticket and phone numbers digit by digit. It is re-read on change, so a presenter can correct a word without a restart.

Evidence: judged by ear by an Egyptian speaker on the team, including amounts (100, 200, 500 pounds). No listening panel or scored comparison has been run.

Cost: VoiceTut uses GPU memory where Piper used none. The three local services (retrieval, speech in, speech out) need about 10 GB together.

### 5.4 Agent rules strengthened (deviations 9 to 11)

| Rule | Deck | Efada build | Reason |
|---|---|---|---|
| One-time code | "OTP verification bypassing the model"; the model "never sees secrets" (slides 10, 22) | Digits entered by keypad, chat or voice go straight to the bank's check. The agent and the guardrail receive the message with digits masked, and a system note with the verdict only. The agent has no tool that verifies a code | Makes the deck's claim true for every entry path, including a customer who types or speaks the code into the conversation. More important, not less, while the model is hosted |
| Blocking a card | Irreversible actions need confirmation | `block_card` is refused in code until the customer has been shown that card and agreed | A prompt instruction can be skipped by the model; a code check cannot |
| Promised action without a tool call | Retried with a mandatory tool call | The same, once, and never after an action has already been taken | Prevents a second, unintended action |
| Reply language | Customer's language | Arabic replies in Egyptian colloquial Arabic; one greeting per conversation | Matches the voice and the customer; formal Arabic read aloud by an Egyptian voice sounds wrong |

### 5.5 Knowledge base and channels (deviations 12 and 13)

- **Knowledge base.** With synthetic articles only, the agent had nothing on card withdrawal limits and answered loan questions from invented figures. Sixteen of the 41 articles now carry NBE's public product information from nbe.com.eg (accounts on 9 October 2026; card limits, credit cards, personal loans, mortgage finance and the doctors' loan on 11 October 2026), each marked with `source` and `as_of`. This is public information, not customer data, so the deck's "synthetic data only" control on customer data is intact. The figures are a dated snapshot and need NBE's confirmation before they are shown as current.
- **Channels.** The deck describes a "realistic WhatsApp/IVR lost card scenario" (slide 22). The portal now shows those two channels as separate conversations, with a phone keypad for the code.

### 5.6 Results compared

| Measure | Deck, GB10 | Efada build, workstation |
|---|---|---|
| Lost card, code, block, ticket, handoff in Arabic and English | Works | Works (`tests/d4_script.py`, against the running stack) |
| Agent rules without any model | not present | `tests/d4_rules.py`: scripted model and bank |
| Time per turn | 2 to 4 s | not recorded; depends on the hosted provider |
| Jailbreak stopped by the input guardrail | about 0.1 s | not recorded; the self-check now calls the hosted model |

## 6. Assessment against the deck's five principles (slide 11)

| Principle | D1 | D4 |
|---|---|---|
| 1. Arabic first | Reader adapted to Egyptian documents | Egyptian speech in and out, Egyptian replies. Advances the principle and closes the deck's own open item |
| 2. Fit GB10 bandwidth | An 8B reader is small and fast; about 5 s a reading | Not applicable on the workstation |
| 3. One shared workhorse | **Departs.** A second model (about 17.5 GB) is added, justified by accuracy on real documents and per-field confidence | Same workhorse model; **hosted on the workstation only** |
| 4. Work without training data | The premise no longer holds for reading (a labelled set and a trained adapter exist). Still holds for forgery detection, where the deck's approach is kept | Holds; nothing is trained |
| 5. Measure, don't assume | Followed: every figure in section 4 was measured, including the unfavourable ones | Partly: function is tested; speech quality and latency are not yet scored |

## 7. What did not change

- The application design: one service per demo, models addressed by role, the trace on every response.
- NeMo Guardrails on input and output; the tool set; the mock bank; the audit log.
- Embedding and reranking models (bge-m3, bge-reranker-v2-m3); only the server that hosts them differs.
- The verdict wording ("flagged for review"), and the officer's authority over it.
- D2, D3, D5, D6 and D7.

## 8. Limits of the evidence

These are stated so that no claim in this document is read as stronger than it is.

1. **No head-to-head between the two readers.** Gemma 4 vision and the v18 reader have not been run on the same real documents. The case for v18 rests on its own measured accuracy, its confidence output and data locality, not on a measured margin over Gemma.
2. **Unfamiliar layouts.** On three real HR letters in other companies' layouts the reader got about 15 of 24 fields, taking the signer's title for the employee's and a bonus for the salary, and marked only some as unsure. Real electricity bills and commercial registers outside the training set were also weak (2 of 7 and 9 of 14 fields, on one and two photographs).
3. **Small real samples.** No real utility bill, bank statement with salary rows, or invoice was available to measure on.
4. **No speech comparison.** QwenCleo-ASR against Whisper, and VoiceTut against Piper, have been judged by ear only.
5. **No D4 latency on the workstation**, and the 0.1 s guardrail figure does not carry over while the self-check is hosted.
6. **Not run on the GB10.** `nbe-docvlm`, VoiceTut-TTS and QwenCleo-ASR were built and run on an x86 CUDA image. Their operation on the GB10's Arm platform, and their combined memory beside the workhorse, are not verified.
7. **Provenance of the real documents** used for the D1 measurements should be recorded before those figures are shown to NBE.

## 9. Recommendation for the GB10 demonstration

1. **Run the workhorse locally.** Restore `config/litellm.yaml` so that deviation 6 disappears and the air-gap claim and `make offline-check` hold. Re-run `tests/d4_script.py` against the local FP8 model.
2. **Carry over the remaining D1 and D4 changes**, subject to item 6 of section 8: build the three new services for Arm and measure their memory beside the workhorse. If the reader does not fit in a given mode, D1 falls back to the `vision` alias for the demo packs, as the code already allows (`DOCVLM=0`).
3. **Close the two comparisons** that would turn judgement into measurement: both readers on one set of real documents, and both speech pairs on one set of Egyptian recordings.
4. **Ask NBE to confirm** the public product figures in the knowledge base, and to approve in writing any real document used in front of an audience.

## Sources

- The deck: slides 3, 10, 11, 12, 13, 15, 19, 22, 27.
- [docs/workstation.md](workstation.md): setup, D1 accuracy by document type, image-check false alarms, the forgery benchmark.
- [PLAN.md](../PLAN.md): measured memory on the GB10, finding 6 (Piper), D4 acceptance criteria.
- [config/litellm.local.yaml](../config/litellm.local.yaml), [docker-compose.local.yml](../docker-compose.local.yml): what is hosted and what has a route out.
- `tests/d1_rules.py`, `tests/d1_bench.py`, `tests/d4_rules.py`, `tests/d4_script.py`.
