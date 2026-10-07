# Riyad Bank AI Demos on GB10: Build Plan

**Source brief:** Dell Technologies *AI demos on GB10* deck, draft of 6 Oct 2026 (17 slides): seven banking use cases, adapted here for Riyad Bank
**Target:** seven live demos (D1 to D7), one per use case, on one Dell Pro Max with GB10, fully offline and fully containerised
**Repo:** https://github.com/tamereissa77/NBE-demo · **Local:** `~/NBE-demo`
**Status (7 Oct):** all seven demos built and passing the end-to-end UI walkthrough; platform, data, hardening and docs done (§13). Open items: blind human scoring for the Arabic gate (`/eval`), then `make models-lock`; Riyad Bank inputs in §10 item 7.

---

## 0. Ground rules

These come straight from the brief. Every phase below is checked against them.

1. **One demo per use case, no merging.** D2 and D5 share a RAG pipeline but have separate UIs and separate stories.
2. **Fully containerised.** Every component runs in a container started by `docker compose`. Nothing is installed on the host apart from Docker, the NVIDIA runtime and `make`.
3. **Fully offline at demo time.** Model weights and images are pulled ahead of time. Model and data services sit on an `internal: true` Docker network with no route out. `HF_HUB_OFFLINE=1` is set everywhere. `make offline-check` proves this by running the full smoke test with the uplink down.
4. **Synthetic data only**, unless Riyad Bank approves masked samples in writing. No real customer IDs on the box.
5. **Honest framing.** Every screen shows a "Single-user PoC on one GB10" badge. Wherever it applies, the demo says "flags for review" and "human decides". The demos never claim production throughput, regulatory approval or accuracy that hasn't been measured.
6. **House conventions** (same as Money2020, ai-debate-arena and the others): root `docker-compose.yml`, `docker/<service>/Dockerfile`, a `Makefile` with `.DEFAULT_GOAL := help`, `.env` for machine-specific values, explicit `container_name`, `image: nbe-<svc>:latest` and `restart: unless-stopped`. Model servers are the exception and use `restart: "no"` (see §6).

---

## 1. What is already on this GB10 (checked 6 Oct)

| Asset | Where | Use in Riyad Bank demo |
|---|---|---|
| Gemma 4 26B-A4B-it weights (BF16, 49 GB) | `/opt/models/gemma-4-26B-A4B-it` | Workhorse LLM, served FP8 (online quantisation) to fit ~29 GB |
| gpt-oss-120b weights (84 GB on disk, MXFP4 ~65 GB loaded) | `/opt/models/gpt-oss-120b` | D6 hero model, on demand |
| Qwen2.5-VL-7B-Instruct + an earlier fine-tune project | `~/APPS/Money2020/loan-automation` (`hf-cache`, `nbe_finetune/`) | D1 document VLM (fallback or primary, decided in week 1) |
| Loan-document generator from an earlier project (national ID, HR letter, forms; now Saudi via `locale.py`) | `loan-automation/generator_service`, `hr_letter_service`, `national_id_service` | D1 synthetic loan packs, including forged variants |
| whisper-large-v3 | `/opt/huggingface-cache` | D4 speech-to-text |
| facebook/mms-tts-ara; `ai-debate-arena-tts-ar` image | HF cache / Docker | D4 TTS fallback if Piper Arabic falls short |
| vLLM images (`vllm/vllm-openai:gemma4-cu130`, `nvcr.io/nvidia/vllm:26.05-py3`) | Docker | Model serving |
| `qdrant/qdrant:latest` | Docker | Vector store |
| Gemma 4 31B-IT NVFP4 | **not on disk** (~20 GB download, needs the HF token from `~/gemma-gb10/.env`) | Quality LLM for D5 |
| bge-m3, bge-reranker-v2-m3, SDXL, Piper voices, NeMo safety model | **not on disk** | Download in Phase 0 |

**Contention warning.** This GB10 is shared. `gemma4-gb10-vllm` (restart `always`, ~74 GB) and the six `galene` containers (`/etc/galene`, restart `always`) take most of the memory at boot. vLLM sizes itself from whatever memory is free *when it starts*, so `make preflight` has to stop **all** competitors in one go before the demo's model servers start (§6). Galene auto-start was disabled on 6 Oct (§10), so after a reboot only `gemma4-gb10-vllm` comes back by itself.

---

## 2. Architecture

```
 Browser ──► :8200  nbe-gateway (Caddy) ─────────────── the only published port
                │
                ├── /            nbe-portal      React + Vite SPA: landing page and D1–D7 screens, AR/EN, RTL
                ├── /api/d1..d7  nbe-d1 … nbe-d7 FastAPI, one container per demo
                ├── /assistant   nbe-openwebui   Open WebUI front end for D6
                └── /v1          nbe-router      OpenAI-compatible endpoint (D6 + Dataiku LLM Mesh)
                                     │
 ── shared services (network nbe-core) ──────────────────────────────────────────
   nbe-llmgw      LiteLLM proxy: aliases workhorse · quality · hero · vision · safety
   nbe-embed      bge-m3 embeddings + bge-reranker-v2-m3 (FastAPI, FlagEmbedding)
   nbe-qdrant     vector store (collections per demo)
   nbe-postgres   tickets, complaints, campaigns, audit log, review decisions
   nbe-guardrails NeMo Guardrails server (rails for D4, D6, D7)
   nbe-mockbank   mock OTP, card block/unblock, balance, complaint tickets, handoff queue
   nbe-docling    Docling conversion (PDF/scan to structured text, Arabic)
 ── model serving (network nbe-models, internal: true) ──────────────────────────
   nbe-llm        vLLM  Gemma 4 26B-A4B FP8          [profile: core]
   nbe-llm-q      vLLM  Gemma 4 31B NVFP4            [profile: quality]
   nbe-vlm        vLLM  Qwen2.5-VL-7B (or Gemma 4 vision via nbe-llm)  [profile: core]
   nbe-asr        whisper-large-v3 (transformers on NGC PyTorch)       [profile: voice]
   nbe-tts        Piper Arabic/English (fallback mms-tts-ara)          [profile: voice]
   nbe-sdxl       SDXL via diffusers                 [profile: image]
   nbe-hero       vLLM  gpt-oss-120b                 [profile: hero, exclusive]
```

### Key design decisions

- **Demos never talk to a model directly.** They call aliases (`workhorse`, `quality`, `vision`, `hero`) through **LiteLLM** (`nbe-llmgw`). The week-1 Arabic bake-off can then swap models by editing `config/litellm.yaml`, with no code changes. This is also how the brief's original model list stays available as fallbacks (slide 13).
- **One shared Python package, `nbe_core`,** copied into every demo image. It holds the LLM client (with structured JSON output), the retrieval client (embed, Qdrant, rerank), the guardrails client, the audit logger, Arabic text utilities (normalisation, RTL-safe formatting) and Pydantic schemas. D2 and D5 share the RAG code through it.
- **One portal, seven screens.** A single SPA keeps the look consistent and makes moving between demos one click. Each demo screen has its decision card from the brief: Review Decision Panel, Branch Answer Card, Bilingual Campaign Card, Conversation + Tool-call Lane, Legal Summary Card, Model-Selection Panel and Triage Dashboard.
- **Every screen has a "Show the work" drawer** with retrieved chunks, tool calls, the model alias used, latency and tokens/s. This answers "is it real?" without opening a terminal.
- **Compose profiles fit the 128 GB budget.** `core` is always on. `voice`, `image`, `quality` and `hero` are switched on as needed (§6).

---

## 3. Repository layout

```
NBE-demo/
├── PLAN.md                     this file
├── README.md                   quick start and runbook
├── Makefile                    single control surface (§7)
├── docker-compose.yml          all services, profiles, networks
├── .env.example                copy to .env (machine-specific, not portable)
├── brand/                    logo.png, mark.png, theme.css (Riyad Bank colour tokens), brand.json
├── config/
│   ├── litellm.yaml            model aliases → endpoints
│   ├── guardrails/             NeMo Guardrails configs (colang + yaml) per demo
│   ├── caddy/Caddyfile
│   └── models.lock             pinned model IDs + revisions + sha256
├── docker/<service>/Dockerfile one per built service
├── packages/nbe_core/          shared Python library
├── services/
│   ├── d1_docverify/           FastAPI: extraction, forensics, cross-checks, verdict
│   ├── d2_chatdoc/             FastAPI: cited RAG + version delta
│   ├── d3_campaigns/           FastAPI: segment → interest → merchant → copy → compliance → banner/A-B
│   ├── d4_agent/               FastAPI + WebSocket: voice/chat agent, tool calling
│   ├── d5_legal/               FastAPI: map-reduce summary, clause schema, risk flags, template diff
│   ├── d6_assistant/           router service + Open WebUI pipelines
│   ├── d7_complaints/          FastAPI: classify, SLA route, draft, trends
│   ├── embed/  mockbank/  asr/  tts/  sdxl/  docling/
│   └── portal/                 React + Vite + Tailwind (brand theme tokens), i18n AR/EN
├── data/
│   ├── generators/             synthetic data scripts (run in the nbe-datagen container)
│   ├── seed/                   small committed seed files (templates, policies, prompts)
│   └── generated/              (git-ignored) generated corpora, documents, images
├── eval/
│   ├── arabic_gate/            30 Saudi retail-banking prompts (MSA + Saudi dialect), scoring rubric, runner
│   └── golden/<demo>/          golden Q&A / expected outputs per demo
├── tests/                      smoke and e2e tests (pytest + Playwright, in containers)
├── scripts/                    preflight, gpu-free, offline-check, record-backup
└── docs/                       runbook, demo scripts (talk track per demo), architecture
```

Git-ignored: `.env`, `models/`, `data/generated/`, `recordings/`, `*.safetensors`. Weights stay in `/opt/models` and are mounted read-only.

---

## 4. Per-demo build specs

Each spec lists **story** (what Riyad Bank sees), **pipeline**, **models**, **data**, **UI**, **acceptance criteria** and **effort** (from the brief).

### D1 · Doc verification for credit lending (Wave 2, 8 days)

- **Story:** a loan officer uploads a synthetic loan pack. The system extracts fields, cross-checks them across documents and runs forensics, then shows an evidence-backed "flagged for review" verdict. The officer approves or overrides. One clean document is flagged on purpose (the false positive) to show that a human decides.
- **Pipeline:** upload → page split → VLM field extraction to a JSON schema per document type (national ID, utility bill, invoice, commercial register, HR letter) → Docling text layer → forensics (OpenCV ELA, copy-move detection with ORB keypoint clustering, EXIF/PDF metadata checks, font-consistency heuristics) → deterministic cross-document rules (name/ID/address/employer/salary consistency, date sanity) → LLM writes the explanation, citing each rule hit → review decision stored in Postgres.
- **Models:** `vision` alias. Candidates are Gemma 4 26B vision (no extra memory) and Qwen2.5-VL-7B (the fine-tuned checkpoint from loan-automation if it beats the base model). The ViT forgery classifier is dropped, as the brief recommends.
- **Data:** about 40 documents (8 applicants × 5 docs), 10 forged in documented ways: edited salary, swapped photo, mismatched address, altered date, cloned stamp. Built by reusing the loan-automation generators plus a forgery script. A ground-truth manifest records every forgery.
- **UI:** document thumbnails with heatmap overlays (ELA), a document card per file, an evidence list linked to image regions, a risk verdict and an approve/override panel.
- **Accept:** all 10 forgeries flagged, exactly 1 planned false positive, every flag links to visible evidence, a full pack takes under 60 s.

### D2 · Chat with Document (Wave 1, 6 days)

- **Story:** a branch employee asks in Arabic about a procedure that changed last month. The answer cites the current version and shows "what changed since v1".
- **Pipeline:** Docling ingest (PDF, DOCX, scans via VLM OCR) → structure-aware chunking (by section, keeping the clause numbering) → bge-m3 dense+sparse into Qdrant, with `doc_id`, `version` and `effective_date` metadata → hybrid search → bge-reranker-v2-m3 → `workhorse` answers using only the context, with an inline citation for each claim → version delta: if a cited section has an older version, a section-level diff plus an LLM summary of the change.
- **Data:** about 12 synthetic Riyad Bank-style working procedures (account opening, transfers, KYC refresh, card replacement, etc.) in Arabic and English, each with v1 and v2. Two or three sample contracts. If Riyad Bank supplies public procedure documents, they are swapped in.
- **UI:** chat with citation chips that open the source page with the passage highlighted, plus a version-delta side panel.
- **Accept:** on a 25-question golden set (AR/EN), at least 90% of answers carry a correct citation. A question with no answer in the documents gets "not found in documents". Time to first token under 2 s.

### D3 · Campaigns & Offers hyper-personalisation (Wave 2, 6 days)

- **Story:** marketing picks a synthetic segment. The system profiles interests from transactions, matches merchants, and writes AR+EN offer copy for SMS, email and ad. The copy passes a compliance check, and the system produces a banner mock-up and an A/B test plan.
- **Pipeline:** Postgres synthetic data → SQL feature aggregation (MCC spend shares, recency, frequency) → interest profile → bge-m3 match of profile against merchant descriptions → `workhorse` produces copy in a structured format (channel × language × tone variants) → compliance check (rule list: required disclaimers, banned claims, rate disclosure, opt-out wording) checked by rules first, then the LLM → SDXL banner (profile `image`, pre-generated cache as fallback) → A/B plan (hypothesis, split, sample size from a standard power calculation, success metric).
- **Data:** 5,000 customers, 50,000 transactions and 100 merchants, all synthetic and Saudi-flavoured (SAR, Riyadh/Jeddah/Dammam). Merchant contracts and deal costing are out of scope, as the brief says.
- **UI:** segment picker → interest chart → merchant list → bilingual campaign card with compliance badge, synthetic-data badge and "AI-generated mock-up" label → banner and A/B plan.
- **Accept:** copy is produced in both languages for 3 channels in under 30 s. A planted non-compliant draft is caught and fixed. The banner renders (live or cached).

### D4 · AI Virtual Agent (Wave 2, 9 days, highest risk)

- **Story:** a customer speaks Arabic in the browser: "I lost my card." The agent authenticates with a mock OTP, blocks the card, logs a complaint ticket, then hands off to a human on request. A jailbreak attempt is blocked live and a STOP marker is shown.
- **Pipeline:** browser microphone (WebRTC/MediaRecorder) → WebSocket → `nbe-asr` (whisper-large-v3, language forced to `ar`/auto) → NeMo Guardrails input rails (jailbreak, PII masking, off-topic) → `workhorse` with tool calling (`send_otp`, `verify_otp`, `get_cards`, `block_card`, `get_balance`, `create_ticket`, `handoff_to_human`, `search_kb`) → mock-bank API → output rails → `nbe-tts` (Piper Arabic) → audio streamed back. A text-only chat mode uses the same backend.
- **Data:** a mock bank with 20 synthetic customers, cards and balances. A KB of about 30 FAQ articles in AR/EN in Qdrant.
- **UI:** transcript on the left, live tool-call lane in the middle (every call with arguments and result), guardrail events with a red STOP marker, and a handoff queue view.
- **Accept:** the scripted happy path works 10 times in a row in MSA, voice round-trip under 4 s per turn, 5/5 scripted jailbreaks blocked, no real banking endpoint reachable (enforced by the network). The **recorded backup video is mandatory.** Saudi dialect is a bonus.

### D5 · Legal Documents Summarisation (Wave 1, 5 days)

- **Story:** legal uploads a ruling or contract and gets a structured summary, the key clauses (governing law, indemnity, termination, SLAs, liability caps), risk flags, and a diff against Riyad Bank's standard template.
- **Pipeline:** Docling → section chunks → map step (`workhorse`, per-chunk summary and clause candidates) → reduce step (`quality` = Gemma 4 31B, final summary) → schema-guided clause extraction (JSON schema per clause type, each with a quote and page reference) → risk rules + LLM rationale → template diff (clause alignment by embedding similarity, then a text diff of aligned pairs).
- **Data:** synthetic Banking Disputes Committee decisions plus synthetic tawarruq personal-finance contracts written against a synthetic Riyad Bank-style template with planted deviations. **Riyad Bank's legal and Sharia teams validate outputs before demo day.**
- **UI:** legal summary card with key points, a clause table (clause, quote, page, deviation), risk flags with severity, and a side-by-side template diff.
- **Accept:** all planted deviations detected on 5 test contracts, every clause has a verifiable quote, a 30-page document finishes in under 90 s.

### D6 · Riyad Bank AI Assistant (Wave 1, 5 days)

- **Story:** an employee uses one assistant for file chat, email drafting, summarisation, translation and code explanation. A visible panel shows which model the router chose and why. Dataiku can use the same endpoint.
- **Pipeline:** `nbe-router` exposes OpenAI-compatible `/v1` with model `auto`. For each request it detects the language and classifies the task (file-chat / drafting / translation / summarise / code), picks an alias by rule table, and returns the choice in response headers and metadata. Code answers are grounded in a local documentation corpus (Python, pandas, SQL and Dataiku API docs indexed in Qdrant) to cut hallucinated APIs. Open WebUI is the front end, with a pipeline that shows the router decision. The portal's D6 screen embeds it and adds the Model-Selection Panel.
- **Hero model:** `hero` = gpt-oss-120b under the `hero` profile. It only fits when `quality`, `image` and `voice` are down (§6), or on a second GB10 (LiteLLM points the `hero` alias at the second unit's IP). If hero is down, the router falls back to `workhorse` and says so on screen.
- **Dataiku:** documented config for LLM Mesh, "Custom OpenAI-compatible" connection → `http://<gb10>:8200/v1`, model `auto`. A Dataiku version and host (likely x86) are needed from Riyad Bank. No Dataiku is installed on the GB10.
- **Accept:** each of the 5 task types routes correctly on a 20-prompt test, automatic AR↔EN translation works, PDF upload and chat works, and an OpenAI SDK client call to `/v1` works from another machine.

### D7 · Complaints Personalisation (Wave 1, 7 days)

- **Story:** 20 incoming complaints (email, social, chat, voice transcript) are classified by topic, severity and sentiment, given SLAs, and routed to a team. Each gets an empathetic, policy-compliant draft reply that waits for human approval. A trend view shows emerging themes.
- **Pipeline:** ingest → `workhorse` zero-shot classification with few-shot examples into a structured schema (topic, sub-topic, severity 1–4, sentiment, language, vulnerable-customer flag) → SLA rules → routing table → bge-m3 similar-complaint search (shows precedent replies) → draft reply with tone controls and policy-rule checks → status `awaiting_human` (nothing is ever auto-sent) → trend clustering (embeddings + HDBSCAN, LLM-named clusters).
- **Classifier:** LLM zero-shot first. If time allows, a small Arabic BERT fine-tune (e.g. CAMeLBERT or multilingual-e5 with a linear head) on the 500 synthetic labels, shown side by side with the LLM for cost and latency.
- **Data:** 500 labelled synthetic complaints in AR/EN (LLM-generated from a topic × severity × channel × dialect grid, then spot-checked). The 20-complaint demo queue is curated. Policy rules are synthetic placeholders until Riyad Bank supplies real ones, and the UI labels them that way.
- **Accept:** at least 85% topic agreement on a held-out 100, every draft passes policy checks, nothing can be sent without the approve button, the trend view renders.

---

## 5. Model stack and memory budget

Budget is about 100 GB usable out of 128 GB unified.

| Alias | Model | Serving | Approx. memory | Profile |
|---|---|---|---|---|
| workhorse | Gemma 4 26B-A4B-it, FP8 online quant | vLLM `gemma4-cu130`, `--quantization fp8`, max-len 16k | ~29 GB weights + ~10 GB KV | core |
| vision | Gemma 4 26B vision (same server) **or** Qwen2.5-VL-7B | same / separate vLLM | 0 / ~10 GB | core |
| embed / rerank | bge-m3 + bge-reranker-v2-m3 | FastAPI + FlagEmbedding (GPU) | ~4 GB | core |
| safety | NeMo Guardrails, self-check rails on `workhorse` (+ optional Nemotron safety guard 8B) | guardrails server | 0 (+~8 GB) | core |
| quality | Gemma 4 31B-IT NVFP4 | vLLM | ~18 GB + KV | quality |
| asr | whisper-large-v3 | transformers, FP16 | ~3 GB | voice |
| tts | Piper ar_JO / en voices (CPU) | piper | ~0.5 GB RAM | voice |
| image | SDXL base 1.0 | diffusers, FP16 | ~10 GB | image |
| hero | gpt-oss-120b (MXFP4) | vLLM | ~65 GB + KV | hero (exclusive) |

**Measured on this GB10 (Phase 1, 7 Oct).** The table above was the plan; these are the real numbers. `make gpu` reproduces them.

| Service | Model and serving | Memory used | Speed (single user) |
|---|---|---|---|
| nbe-llm | Gemma 4 26B-A4B, FP8 online quant, 32k context, util 0.30 | 35.4 GB (25.7 GB weights) | ~30–40 tok/s; Arabic chat, tool calls and **vision** all verified |
| nbe-embed | bge-m3 (vLLM pooling runner, dense) | 1.7 GB | 3 texts in 40 ms |
| nbe-rerank | bge-reranker-v2-m3 (vLLM pooling runner) | 1.7 GB | 20 ms per query |
| nbe-llm-q | Gemma 4 31B NVFP4 (attention kept in BF16, so 31 GB of weights), 16k context, util 0.33 | 37.7–43 GB | **6.7 tok/s** (dense 31B is bandwidth-bound) |
| nbe-asr | whisper-large-v3 FP16 | 3.4–4.9 GB | 1.2 s for 7.8 s of Arabic audio (warm) |
| nbe-tts | Piper ar_JO-kareem / en_US-lessac, CPU | none on GPU | ~0.3 s per sentence |
| nbe-sdxl | SDXL base 1.0 FP16, cuDNN off (see §11) | 7–16 GB | 11 s for 1216×832 at 25 steps (warm) |
| nbe-hero | gpt-oss-120b MXFP4, 16k context, util 0.575 | ~71 GB (66 GB weights) | **37–39 tok/s** |

| Operating point | Command | Used / free | Notes |
|---|---|---|---|
| Show: core + quality + voice | `make up` | 87–97 GB / 24–33 GB | Cold start to ready **4 min 14 s** |
| Show + live banners | `make image-on` | ~106 GB / ~15 GB | SDXL loads in 11 s |
| Hero moment | `make hero` | ~114 GB / 6–7 GB | Swap 70 s (repeated 3×); back to show with `make hero-off` in 111 s |

- The separate document VLM is **not needed**: Gemma 4 26B reads documents itself (invoice fields extracted correctly), which saves ~10 GB. The `vision` alias points at `nbe-llm`; Qwen2.5-VL-7B remains a fallback.
- The hero model fits **alongside** the workhorse on one GB10, so D6 can show real routing between two models. A second GB10 is not required.
- Model servers start strictly one after another (`scripts/up.sh`), because vLLM sizes its cache from memory free at start time.

**Week-1 Arabic gate (slide 13).** `eval/arabic_gate` holds 30 Saudi retail-banking prompts: 15 MSA, 10 Saudi dialect, 5 code-switching/English, covering QA, summarisation, drafting, classification and tool-call selection. Candidates are Gemma 4 26B-A4B vs Gemma 4 31B, with Qwen2.5-14B (already on disk) and the brief's Llama-3-8B as references. Each output is scored on a 1–5 rubric (correctness, fluency, dialect handling, format adherence) by a human, with an LLM-judge pre-score to speed it up. The result is frozen into `config/models.lock` by **16 Oct**. The gate must also settle one question raised by Phase 1: Gemma 4 31B runs at 6.7 tok/s, so a 400-token legal summary takes about a minute. If the 26B is close on legal quality, drop the `quality` profile and give its ~40 GB to SDXL and the hero model.

---

## 6. Runtime control and GPU contention

- `make preflight` lists GPU consumers (nvidia-smi PID → cgroup → container), then stops `gemma4-gb10-vllm` and any running `galene`/`appliance-*` containers **together**, and checks free memory meets the budget. Galene no longer auto-starts (§10); the Gemma restart policy is left as is.
- The demo's model servers use `restart: "no"`, so they never grab memory at boot. App containers use `unless-stopped`.
- `make up` = preflight → start the model servers one by one, waiting on health → start shared services → start the apps → warm-up (one request per alias, so the first live request isn't a cold start).
- Profiles: `make voice-on|off`, `make image-on|off`, `make quality-on|off`, `make hero|hero-off`.

---

## 7. Makefile targets (house convention)

`help` (default) · `up` `down` `start` `stop` `restart` `build` `rebuild` `ps` `status` `logs` `logs-%` `clean`
plus: `preflight` `gpu` (memory per container) `models` (download and verify weights into `/opt/models`, the only online step) `pull` (all images) `data` (run synthetic generators) `ingest` (load Qdrant/Postgres) `warm` `verify` (smoke test every demo) `eval-arabic` `eval` (golden sets) `offline-check` `record` (Playwright backup videos per demo) `demo-reset` (restore seed state between audiences) `voice-on|off` `image-on|off` `quality-on|off` `hero` `hero-off` `d1`…`d7` (open or health-check one demo).

---

## 8. Execution phases

The brief's calendar (slide 14) is the external commitment. The build phases below are the order I'll implement in. Each phase ends with a commit and pushes to `main` once push access is set up (§10).

| Phase | Scope | Exit criteria | Brief milestone |
|---|---|---|---|
| **0. Scaffold** ✅ | Repo layout, compose skeleton, Makefile, `.env.example`, Caddy, Postgres, Qdrant, portal shell with 7 empty screens, CI-free smoke test | `make up` brings up the shell, portal reachable on :8200 | Kickoff 12 Oct |
| **1. Platform** ✅ | vLLM workhorse (FP8), embed/rerank service, LiteLLM aliases, guardrails, mock-bank, `nbe_core`, preflight/gpu scripts, model downloads. **Validate every component on aarch64**: Docling, Piper, whisper, SDXL, FlagEmbedding, OpenCV, NeMo Guardrails | All aliases answer; memory budget measured against §5; aarch64 gap list closed or worked around | Platform + Arabic test 12–23 Oct |
| **2. Arabic gate** 🟡 run; awaiting human scores | Run `eval/arabic_gate`, pick models, write `models.lock` | Stack frozen and documented | **Model stack frozen 16 Oct** |
| **3. Synthetic data** ✅ | All generators: D1 docs + forgeries, D2 procedures v1/v2, D3 customers/txns/merchants, D4 bank + KB, D5 contracts + templates, D6 doc corpus, D7 500 complaints | `make data && make ingest` repeatable and deterministic (seeded) | Synthetic data 12–30 Oct |
| **4. Wave 1** ✅ | D2 → D5 (reuses D2 RAG) → D7 → D6 | Each passes its §4 acceptance criteria and `make verify` | Wave 1 19–30 Oct |
| **5. Wave 2** ✅ | D1 → D3 → D4 (voice last, most risk) | Same | Wave 2 26 Oct–13 Nov |
| **6. Hardening** ✅ | `offline-check`, `demo-reset`, warm-up, failure drills (kill a model mid-demo, cold boot to ready time), talk tracks in `docs/`, backup videos via `make record` | Cold boot to all 7 demos ready measured and documented; 3 consecutive clean full run-throughs | Hardening + videos 9–18 Nov |
| **7. Dry run** | Customer dry run, fixes | Sign-off | **Dates to be agreed with Riyad Bank** |

---

## 9. Risks and mitigations (slide 16, made concrete)

| Risk | Mitigation in this build |
|---|---|
| aarch64 package gaps (OCR, TTS, ONNX) | NGC base images (`nvcr.io/nvidia/pytorch`, `vllm`) first; Phase 1 runs a container test for every component; documented fallbacks (Piper → mms-tts-ara / existing tts-ar image; Docling → VLM-only OCR) |
| Weak Arabic, dialect in voice | Arabic gate before freezing; MSA script for D4; dialect shown only when it works reliably |
| Memory contention on the shared box | `make preflight`; sequential model start; `restart: "no"` on model servers; hero profile exclusive |
| Demo speed read as production numbers | PoC badge on every screen; "Show the work" drawer shows real tokens/s labelled as single-user |
| Forgery detection over-trusted | Language says "flagged for review"; planned false positive; human approve/override |
| Real customer data on the box | Synthetic only; datagen manifests; masked samples only with written approval |
| Live failure on the day | Fully offline, warmed, `demo-reset`, backup video per demo, cached SDXL banners |
| Gemma 4 vision or tool-calling quality is not good enough | LiteLLM alias swap to Qwen2.5-VL-7B / Qwen 2.5 14B / Nemotron 3 Nano (all already on disk) |

---

## 10. Decisions

| # | Decision | Status |
|---|---|---|
| 1 | GitHub push | **Decided:** push with a PAT supplied 6 Oct. The token is used for one push at a time and never written to disk or the remote URL. Repo is currently **public**, see note below. |
| 2 | Port | `:8200` (default) |
| 3 | Galene auto-start | **Done 6 Oct:** all 33 `/etc/galene` containers set to `restart=no`. Original policies saved in `ops/galene-restart-policies.txt` (git-ignored). Undo: `while read c p; do docker update --restart=$p $c; done < ops/galene-restart-policies.txt`. `gemma4-gb10-vllm` (restart `always`) is unchanged; `make preflight` stops it during demo runs. |
| 4 | Branding | **Decided: Riyad Bank theme.** Logo from the user-supplied Riyad Bank logo (`brand/logo.png`, `mark.png`, `logo-full.png`). Colours sampled from riyadbank.com and the logo in `brand/theme.css`: primary indigo `#1f0973`, accent teal `#00ae9a`, gradient `#1f0973 → #553e99 → #00ae9a`, page background `#f6f7f8`, amber `#f2a900` for "flagged for review". UI font IBM Plex Sans Arabic, bundled locally because the demo is offline (the site's own font is proprietary). A small "Powered by Dell Pro Max with GB10" footer mark stays for the hardware story. |
| 5 | Model downloads | **Done 7 Oct** (`make models`): Gemma 4 31B NVFP4, bge-m3, bge-reranker-v2-m3, SDXL base fp16, Piper voices, and the 3 gpt-oss-120b shards that were missing on disk |
| 6 | Second GB10 | **Not needed** (measured, §5). The `hero` alias can still point at a second unit |
| 7 | Riyad Bank inputs (slide 17) | Pending from Riyad Bank: demo date and audience, use-case ranking, masked vs synthetic data, language priority, Dataiku version/host, mock APIs, output validators |

**Repo visibility.** The source deck is marked *Commercial in Confidence*, and this repo carries the plan derived from it plus the bank's logo. Keep the repo private.

---

## 11. Phase 1 findings (7 Oct)

Things the plan did not anticipate, found by running every component on this GB10:

1. **cuDNN convolutions are wrong on GB10 in `nvcr.io/nvidia/vllm:26.05`.** SDXL produced pure noise; a VAE encode/decode round trip had error 0.65 with cuDNN and 0.004 without. SDXL runs with `torch.backends.cudnn.enabled = False` (11 s per banner). Whisper and Gemma vision outputs were checked and are correct. Any new GPU service that uses convolutions must be checked the same way.
2. **Docling scrambles Arabic from PDF text layers** (reversed digits "٦٢٠٢", wrong line-wrap order, reversed table cells). It is exact on source formats (DOCX/HTML/MD). Rule: our synthetic corpora are authored in source formats; uploaded Arabic PDFs (`rtl_pdf: true` from `/convert`) are rendered with `/render` and transcribed by the `vision` alias (~6 s per page, verified exact). D5's live-upload target of 30 pages in 90 s therefore needs parallel page transcription, or pre-ingested documents.
3. **Embeddings are dense only.** bge-m3 and the reranker are served by vLLM (pooling runner), which avoids a separate PyTorch image but does not expose bge-m3's sparse vectors. Retrieval is dense search + bge-reranker-v2-m3, which ranked correctly in tests. Revisit only if D2's golden set shows retrieval misses.
4. **vLLM's CUDA-graph memory estimate varies between runs** (3.4 → 7.3 GiB for gpt-oss), which intermittently left no KV cache. Fixed by capping graph capture at 16 tokens and batched tokens at 4096 for the hero model.
5. **LiteLLM now refuses to start without a master key.** `make .env` generates `LITELLM_MASTER_KEY`; demos pass it automatically.
6. **Piper Arabic is understandable but not perfect without diacritics** (Whisper heard "الاعتمانية" for "الائتمانية"). For D4, add automatic diacritisation before TTS or compare with MMS-TTS Arabic (already on disk) in Wave 2.
7. **gpt-oss-120b on disk was incomplete** (3 of 15 shards missing); `make models` now fetches anything missing.
8. **Guardrails:** NeMo self-check rails on the workhorse passed 8/8 cases (English and dialect jailbreaks blocked, angry complaints allowed, leaked card number and PIN blocked) in 120–600 ms.

---

## 12. Arabic gate: provisional result (7 Oct, LLM judge only)

`make arabic-gate` ran the 30 prompts in `eval/arabic_gate/prompts.yaml` (first run, on the earlier prompt set: 15 MSA, 10 Egyptian dialect, 5 mixed; all seven demos) on five models, temperature 0, one GB10. gpt-oss-120b pre-scored every answer (correctness / Arabic quality / format, 1–5). **Human blind scoring at `/eval` decides the result;** the guide is `docs/arabic_gate.md`.

| Model | tok/s | Mean latency | Auto-checks | Judge C / A / F | Judge mean | MSA / Egyptian / mixed | D5 legal |
|---|---|---|---|---|---|---|---|
| **Gemma 4 26B-A4B (FP8)**, workhorse | **40.0** | 5.4 s | 12/13 | 4.70 / 4.97 / 4.50 | 4.72 | 4.71 / 4.63 / 4.93 | 4.44 |
| Gemma 4 31B (NVFP4), quality | 10.3 | 26.1 s | 12/13 | 4.63 / 4.90 / 4.03 | 4.52 | 4.67 / 4.20 / 4.73 | 4.56 |
| gpt-oss-120b, hero (and judge) | 37.2 | 7.3 s | **10/13** | 4.80 / 5.00 / 4.87 | 4.89 | 4.93 / 4.77 / 5.00 | 4.78 |
| Qwen2.5-14B-Instruct, reference | 8.6 | 18.4 s | 12/13 | 4.43 / 4.77 / 4.50 | 4.57 | 4.71 / 4.27 / 4.73 | 4.22 |
| Mistral-7B-Instruct v0.3, original brief's list | 15.8 | 24.8 s | 8/13 | 3.20 / 3.23 / 3.67 | 3.37 | 3.71 / 3.17 / 2.73 | 3.22 |

**Provisional recommendation (by the rule in `services/eval/app/main.py`, fixed before scoring):**
- **Workhorse: keep Gemma 4 26B-A4B.** Best of the models fast enough for interactive demos, strongest in dialect among them (measured on Egyptian; re-run for Saudi), and the best tool caller.
- **Drop Gemma 4 31B** (quality): only +0.12 over the workhorse on the D5 legal items against the +0.5 threshold, at a quarter of the speed. Dropping it frees ~40 GB.
- **Keep gpt-oss-120b as the hero model** for D6 code explanation and reasoning, but **not as an agent**: it failed all three tool-calling prompts, describing the action ("I'll transfer you") without calling the tool. It may be vLLM's gpt-oss tool parser rather than the model; recheck before using it in any agent flow.
- **Mistral-7B (from the original brief's list) is not suitable** for Arabic banking use: weak Arabic, refused to help on a lost card, and told an angry customer to "stop harassing" (egy-04).

**Saudi re-run (7 Oct 2026, Riyadh-Bank branch).** `make arabic-gate` on the Saudi prompt set (15 MSA, 10 Saudi dialect, 5 mixed), same five models, judge gpt-oss-120b:

| Model | tok/s | Mean latency | Auto-checks | Judge C / A / F | Judge mean | MSA / Saudi / mixed | D5 legal |
|---|---|---|---|---|---|---|---|
| Gemma 4 26B-A4B (workhorse) | 39.2 | 5.5 s | 11/13 | 4.77 / 4.87 / 4.17 | 4.60 | 4.53 / 4.57 / 4.87 | 3.67 |
| Gemma 4 31B (quality) | 10.1 | 26.2 s | 11/13 | 4.70 / 5.00 / 4.00 | 4.57 | 4.58 / 4.43 / 4.80 | 4.11 |
| gpt-oss-120b (hero) | 37.4 | 7.2 s | 9/13 | 4.60 / 4.90 / 4.83 | 4.78 | 4.80 / 4.67 / 4.93 | — |
| Qwen2.5-14B (reference) | 8.6 | 18.9 s | 13/13 | 4.50 / 4.63 / 4.63 | 4.59 | 4.87 / 4.03 / 4.87 | — |
| Mistral-7B (reference, original brief's list) | 15.7 | 26.7 s | 9/13 | 3.00 / 2.97 / 3.13 | 3.03 | 3.27 / 2.80 / 2.80 | — |

Decision unchanged: Gemma 4 26B stays the workhorse (best judge mean at ≥20 tok/s, and the strongest of the fast models on Saudi dialect); Gemma 31B stays optional (+0.44 on legal, below the +0.5 rule); gpt-oss-120b stays the hero for reasoning, not agents (missed the OTP/handoff tool calls on dia-02, dia-10 and msa-11). All candidates missed the tool call on dia-02 or msa-11; D4 enforces it in code. Human blind scoring at `/eval` still decides the final lock.


**Caveats.**
- The judge rates Arabic quality near the ceiling for every model except Mistral, including Qwen answers that a human reader would mark down (broken dialect verb forms, a hallucinated hotline number in egy-01).
- The judge also scores its own answers, so gpt-oss-120b's top row is not independent.
- Both are why human scores lead.

**Findings that change the demo builds (not only the model choice):**
1. **Tool calls must be enforced by the agent loop.** On egy-02 (dialect: "block my card ending 4821") the Gemma models and gpt-oss all *said* they would send the OTP but did not call `send_otp`. D4 will use `tool_choice` when an action is pending, plus a check that rejects "I will do X" replies with no call.
2. **Customer-facing drafts need a "reply text only" instruction.** Both Gemma models wrap replies and SMS copy in a preamble and offer several alternatives, which costs format points (msa-07, egy-04, egy-09). D3 and D7 prompts will ask for exactly one output with no preamble, and validate length.
3. **Judge reliability:** the first judge prompt over-applied a "JSON only" example to every task (fixed: only constraints the task states), and gpt-oss sometimes loops on whitespace inside the JSON schema (fixed: one retry at temperature 0.7, and old scores are cleared before a re-judge).

---

## 13. Build complete: measured results (7 Oct)

All seven demos run live on the GB10, fully offline (`make offline-check`: 22 containers on the internal network, no egress), and pass the scripted end-to-end walkthrough in the real UI with real models (`make ui-test`: 7/7, Arabic and English). Operator guide: `docs/runbook.md`; presenter guide: `docs/talk-tracks.md`; backup videos: `make record` → `recordings/video/`.

| Demo | Acceptance check (§4) | Measured |
|---|---|---|
| D1 Doc verification | all 10 forgeries flagged, exactly one planned false positive, evidence linked | **10/10 forgeries flagged**, 0 missed. Other flags are the genuine partner document in a cross-check mismatch (5) plus the planned false positive (A04); no unexplained flags. ~25 s per pack. |
| D2 Chat with Document | ≥90% correct citation on the golden set; "not found" when absent | **51/52** on the 52-question golden set from the fact sheets (current values 36/37, version deltas 12/12, unanswerable 3/3). ~4-7 s per answer. |
| D3 Campaigns | AR/EN copy for 3 channels < 30 s; planted claim caught | copy for SMS (A/B), email and social in AR/EN/dialect; **planted "guaranteed 100%" caught and auto-fixed**; SMS ≤ 160 chars; ~30 s including a live SDXL banner |
| D4 Virtual Agent | scripted happy path, jailbreaks blocked, mock APIs only | lost card → OTP → verify → block → ticket → handoff works in Arabic and English; dialect jailbreak blocked by the input rail in ~0.1 s; 2-5 s per turn; OTP never reaches the model |
| D5 Legal | all planted deviations found; verifiable quotes | **all 8 planted deviations found across C01-C05, no false deviations**; quotes checked verbatim; ~45 s per contract, ~18 s per ruling |
| D6 Assistant | task routing, AR↔EN translation, file chat, OpenAI-compatible endpoint | rule + LLM routing with on-screen reason and honest fallback; `/v1` (model `nbe-auto`, bearer key) for Dataiku LLM Mesh and Open WebUI |
| D7 Complaints | ≥85% topic agreement on held-out 100; nothing sent without approval | **94% topic accuracy, 98% severity within ±1** on 100 held-out complaints (zero-shot); drafts pass policy check and output guardrail and wait for a human |

**Changes from the plan, and why.**
- **Gemma 4 26B does vision too**, so there is no separate document VLM (saves ~10 GB).
- **Show mode is core + voice + image.** The Arabic gate provisionally drops Gemma 4 31B, which stays optional (`MODE=full`, `make quality-on`). D5's reduce step uses `D5_REDUCE_ALIAS` (default workhorse).
- **Open WebUI is not deployed.** D6's own portal screen carries the Model-Selection Panel; the `/v1` endpoint is ready for Open WebUI or Dataiku if Riyad Bank wants either.
- **D1 forensics are noise consistency, duplicate-stamp detection and metadata,** with ELA shown as a visual aid only. Classic ELA and generic copy-move detection both misfired on text documents and the SPECIMEN watermark (measured), so they would have flagged every page.
- **D5 contract clauses are written deterministically** (`data/generators/d5_clauses.py`): the LLM paraphrased the exact terms the comparison depends on. Rulings, procedures, the knowledge base and complaints are LLM-authored from fact sheets and committed (`data/seed/`, with `fact_check.json`).
- **The D7 demo queue** is a realistic severity mix (4/6/6/4), not the 20 most severe complaints.

**Fixes found by testing the real thing,** each verified after the fix:
- D4 enforces tool calls when the model promises an action.
- The output rail allows asking for the bank's own OTP.
- The agent replies in the language of the customer's latest turn.
- Gemma's thinking-channel text is stripped from replies.
- Malformed JSON is retried once with sampling.
- D5 changes are structured fields: arrows are ambiguous in RTL text, and the model reversed them.
- D3's A/B plan states the detectable lift for the real audience.
- D1 invoices print the pre-tax subtotal, so the vision model no longer adds up line items itself.
