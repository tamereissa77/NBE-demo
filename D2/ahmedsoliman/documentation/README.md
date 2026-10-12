# D2 · Chat with Document: scanned documents, visual citations and roles

What was changed in the NBE demo to bring the nbe-working knowledge assistant into D2, how it works,
how it was verified, and what to do when it moves back to the fully local deployment on the GB10.

| | |
|---|---|
| Owner | Ahmed Soliman (D2, later D7) |
| Branch | `asoliman/d2-d7`, cut from `Efada_AI_Team` at `e8287b6` |
| Commits | `f6ab844` data · `6468718` backend · `59ce0c7` portal · `892ee00` API setup and docs |
| Written | 8 October 2026; guardrails added 9 October 2026 |
| Current state | Running on the development workstation with a hosted chat model. Not yet run on the GB10. Not pushed |
| Dated records | [docs/d2-migration-plan.md](../../../docs/d2-migration-plan.md) (the agreed plan) and [docs/d2-migration-log.md](../../../docs/d2-migration-log.md) (change-by-change log) |

## Contents

1. [Summary](#1-summary)
2. [What D2 does now](#2-what-d2-does-now)
3. [How it works](#3-how-it-works)
4. [Every change, file by file](#4-every-change-file-by-file)
5. [What was dropped from nbe-working and what replaced it](#5-what-was-dropped-from-nbe-working-and-what-replaced-it)
6. [The temporary development setup](#6-the-temporary-development-setup)
7. [Moving to the GB10](#7-moving-to-the-gb10)
8. [Verification and results](#8-verification-and-results)
9. [Tuning values and where they live](#9-tuning-values-and-where-they-live)
10. [Maintenance](#10-maintenance)
11. [Known limits and open items](#11-known-limits-and-open-items)

## 1. Summary

D2 used to answer from 12 synthetic working procedures written as Markdown. It now also answers from
six scanned documents taken from nbe-working (five legal circulars and the RTGS procedures guide), shows
the crop images of the scan beside each citation, limits what each role may read, and screens questions
and answers with guardrails that run on the demo's own guardrails service.

Three rules kept the change from disturbing the rest of the demo:

1. **Two collections, never one.** Procedures stay in `d2_procedures`; scanned passages go to `d2_circulars`.
2. **Switched on by data.** Without the folder `data/seed/d2/circulars`, D2 behaves exactly as before.
3. **No shared file edited.** `packages/nbe_core`, `docker-compose.yml`, `config/litellm.yaml`, the `Makefile`, the existing scripts and the README are untouched.

Measured on the development setup with Gemma 4 26B-A4B:

| Test | Result |
|---|---|
| Procedures golden set, 52 questions | 51/52 before the guardrails, the same as the README baseline; 51/52 with them (section 8 explains the difference) |
| Scanned-corpus golden set, 32 questions | 32/32, including the guardrail and role cases |

## 2. What D2 does now

| Capability | Before | Now |
|---|---|---|
| Sources | 12 procedures in two versions (Markdown) | The same, plus 6 scanned documents (62 pages) |
| Citation view | Markdown text of the procedure in a pop-up | For scanned sources: the crop images of the page, a text tab, and a link to the original image. Procedures unchanged |
| Version comparison | Yes | Unchanged, procedures only |
| Follow-up questions | Yes | Unchanged, both corpora |
| Languages | Arabic, Egyptian dialect, English | Unchanged, both corpora |
| Access by role | None | Teller, legal counsel, manager |
| "Not found" | Yes | Unchanged, plus a separate "outside your access" reply |
| Guardrails | None | A check on every question, a rule that masks personal identifiers in answers, and a check on every generated answer |

Roles and what they may read:

| Role | Procedures | RTGS guide | Legal circulars 1 to 5 |
|---|---|---|---|
| Teller | Yes | Yes | No |
| Legal counsel | Yes | Yes | Yes |
| Manager (default) | Yes | Yes | Yes |

The role is chosen on the D2 screen and sent with each question. It is a client-supplied value, as in
nbe-working: the demo has no login.

## 3. How it works

```
question + role
   │
   ├─► input guardrail ─ stop ..............................................► "I can't help with that request"
   │
   ├─► search d2_procedures ───────────────────────────┐
   ├─► search d2_circulars, filtered by role ──────────┼─► best six by reranker score
   └─► (limited role only) search d2_circulars         │        │
       unfiltered: keep only the best score among      │        ├─ nothing relevant ........► "not found"
       passages the role may NOT read  ─► "hidden"     │        ├─ hidden is strong and
                                                       │        │  nothing permitted is ....► "outside your access"
                                                       │        └─ otherwise
                                                       │              │
                                                       ▼              ▼
                                              workhorse writes a cited answer [S1]…[S5]
                                                       │
                              model says "not found" and hidden is strong ► "outside your access"
                                                       │
                                                       ▼
                       mask personal identifiers (pattern rule) ─► output guardrail ─ stop ► "answer withheld"
                                                       │
                                                       ▼
                         answer + citations (procedure: text, version delta · scan: page, crops)
```

### 3.1 The scanned corpus

Location: `data/seed/d2/circulars/`.

| Part | Content |
|---|---|
| `manifest.json` | One entry per document: id, Arabic and English title, type, page and block counts, the roles allowed to read it |
| `extractions/<doc>/page_NNN.json` | The OCR blocks of each page in reading order: type (text, header, footer, table), text, table HTML, crop path |
| `crops/<doc>/page_NNN/*.png` | One image per block, cut from the page scan. 541 images, 36 MB |

| Document id | Type | Pages | Blocks | Passages | Roles |
|---|---|---|---|---|---|
| `legal_circular_1` | Legal circular | 2 | 15 | 3 | legal counsel, manager |
| `legal_circular_2` | Legal circular | 31 | 244 | 61 | legal counsel, manager |
| `legal_circular_3` | Legal circular | 8 | 58 | 18 | legal counsel, manager |
| `legal_circular_4` | Legal circular | 1 | 10 | 2 | legal counsel, manager |
| `legal_circular_5` | Legal circular | 1 | 8 | 2 | legal counsel, manager |
| `rtgs` | Procedures guide | 19 | 206 | 57 | all three |

The pages were read by nbe-working's OCR service before this migration. D2 does not run OCR; it loads the result.

### 3.2 From blocks to passages

nbe-working indexed each OCR block on its own. The median block is 95 characters (a salutation, a clause
number), which is too little to retrieve or to ground an answer on. `services/d2_chatdoc/app/scans.py`
merges blocks into passages at ingest time:

- A passage is the run of blocks under one heading on one page.
- It is capped at 1,000 characters. A remainder shorter than 250 characters stays with the passage before it.
- A table is always its own passage. Its HTML becomes plain rows for the prompt and a Markdown table for display.
- Footers, letterheads ("البنك المركزي المصري") and page counters ("صفحة ٣ من ٢٠") are dropped.
- Every passage keeps the ids of the blocks it was built from. That list is what lets a citation show the crops.

Result: 541 blocks become 143 passages with a median of 602 characters.

### 3.3 Retrieval and ranking

Both collections are searched with the shared `nbe_core.retrieval.search` (bge-m3, Qdrant, bge-reranker-v2-m3).
The reranker and the query are the same for both, so the scores are comparable; the best six overall are kept
and the top five go to the model. Among procedure hits the current version still sorts first. Scanned hits
never enter the version logic.

### 3.4 Role-based access

- Each scanned passage is stored with the `roles` list of its document. The role search uses the existing
  equality filter of `nbe_core`; Qdrant matches a value against any member of a list.
- A passage the role may not read is never sent to the model and never returned to the browser.
- To tell "the answer does not exist" from "the answer exists but you may not see it", a limited role triggers
  one extra search without the filter. Only one number is kept from it: the best score among forbidden passages.
- If that score is at least 0.3 and either nothing permitted matches as well, or the model finds no answer in
  the permitted sources, the reply is a fixed sentence (the wording nbe-working used for the teller) with no citations.
- The crop endpoint checks the role again, so a forbidden image cannot be fetched by guessing its address.

### 3.5 Visual citations

A scanned citation carries the document, page, heading, display text and the list of block ids. The portal
builds each image address as `/api/d2/crop/<doc_id>/<block_id>?role=<role>`. D2 serves the file itself from
`/data`, which it already mounts read-only. Ids are looked up in the manifest and are never used as file paths.

On the D2 screen:

- Scanned sources in the answer card show the page, a relevance band (high, medium, low) and a short preview.
- Selecting one opens a detail block with two tabs: the crop images, stacked in reading order, and the text.
- A link opens the original image in a new tab. Source chips under the answer do the same selection.
- Procedure sources still open the Markdown viewer, and the version-delta block is unchanged.

### 3.6 Guardrails

nbe-working screened every question and answer through NVIDIA's cloud. D2 does the same job on the demo's
local guardrails service (`nbe-guardrails`, NeMo Guardrails), so it works offline. Three layers:

| Layer | When | How | On a stop |
|---|---|---|---|
| Input check | Before retrieval | The guardrails service judges the question with the `d2` policy | Fixed refusal, no sources, no retrieval and no answer model call |
| Identifier mask | On every generated answer and on the text shown for a scanned source | A pattern rule, not a model: card numbers (16 digits), national IDs (14 digits) and Egyptian mobile numbers, in Western or Arabic digits, are replaced by `[محجوب]` / `[redacted]` | The answer is kept; the response reports how many values were masked |
| Output check | After the mask | The guardrails service judges the answer with the `d2` policy | Fixed "answer withheld" reply, no sources |

The `d2` policy (`config/guardrails/d2/`) is separate from the `banking` policy that D4 and D7 use. `banking` is
written for customer service and blocks legal content and anything outside customer service, which in D2 is
the subject matter.

| The `d2` policy blocks | It explicitly allows |
|---|---|
| Attempts to override or reveal the assistant's instructions (jailbreaks) | Questions about procedures, fees, limits, documents and deadlines |
| Requests to see documents outside the user's role, or to bypass access rules | Questions about what a law, circular or regulation requires, including anti-money-laundering, KYC and fraud rules |
| Requests for help committing or concealing fraud, money laundering or other illegal acts | Off-topic or unanswerable questions (they get "not found") |
| Requests for a named individual's personal data | Answers stating fees, dates, article numbers, SWIFT message types, and redaction markers |
| Abusive, hateful or sexual content; answers that reveal identifiers, secrets or the system prompt | |

Design points:

- The guardrails switch on with the scanned corpus, like the roles. Without `data/seed/d2/circulars` D2 makes no guardrail call.
- The fixed replies ("not found", "outside your access", the refusals) are not sent to the output check.
- If the guardrails service is down, `/ask` fails instead of answering unchecked, as in D4 and D7.
- Each model-based check is one call to the workhorse: two extra calls for an answered question.

### 3.7 API

All paths are under `/api/d2` through the gateway.

| Endpoint | Change | Purpose |
|---|---|---|
| `POST /ask` | Accepts `role` (default `manager`). Response adds `restricted`, `blocked` (a guardrail stopped it) and `masked` (identifiers replaced in the answer); each citation adds `kind` | Answer a question |
| `POST /admin/ingest` | Also builds `d2_circulars`; response adds `scanned_passages`, `scanned_documents` | Load both collections |
| `GET /crop/{doc_id}/{block_id}?role=` | New | One crop image, role-checked |
| `GET /corpus` | New | Roles and scanned documents; empty lists when the corpus is absent |
| `GET /suggested` | Two scanned-corpus questions appended after the original five | Starter questions |
| `GET /documents`, `GET /doc/{file}`, `GET /health`, `GET /info` | Unchanged | |

Fields of a citation:

| Field | Procedure | Scan |
|---|---|---|
| `label`, `title`, `section`, `text`, `lang`, `rerank`, `cited` | As before | Same meaning |
| `kind` | `procedure` | `scan` |
| `file` | Markdown file name | Document id |
| `version`, `effective` | Set | `null` |
| `doc_id`, `page`, `block_type`, `crops` | Absent | Set. `crops` is a list of `{id, page, type}` |

## 4. Every change, file by file

"Dev" is the temporary development setup. "GB10" is the final local deployment.

### Data

| Path | Kind | What and why | Dev | GB10 |
|---|---|---|---|---|
| `data/seed/d2/circulars/` | New, 604 files | The scanned corpus (section 3.1). Under `data/seed` because seed data is committed and mounted into D2 | Passage text is sent to the hosted chat model when retrieved (approved) | Arrives with `git pull`; nothing to copy by hand |
| `services/d2_chatdoc/tools/import_nbe_working.py` | New | Produced the folder above from nbe-working. Normalises document ids to underscores, corrects the type of circulars 3 to 5, drops machine-specific paths | Run once | Not needed unless documents are added (section 10) |
| `data/seed/golden/d2_circulars.json` | New | 32 test questions for the scanned corpus, the role rules and the guardrails | | |

### Service

| Path | Kind | What and why | Dev | GB10 |
|---|---|---|---|---|
| `services/d2_chatdoc/app/scans.py` | New | Loads the corpus, builds passages, converts tables, defines the roles (sections 3.1 and 3.2) | Same code | Same code |
| `services/d2_chatdoc/app/main.py` | Modified | Loads the corpus when present; ingests `d2_circulars`; `/ask` takes a role, merges both searches, applies the access rule, keeps scans out of the version logic; new `/crop` and `/corpus`; citations gain `kind`; the early "not found" reply now carries `lang` and `total_ms` (the portal printed "NaN s"); the input check, the identifier mask and the output check (section 3.6) | Same code | Same code |
| `tests/golden_d2_circulars.py` | New | Runs the 32 questions and prints the top reranker scores for calibration | Run by `scripts/dev_api.sh golden` | Run directly (section 7) |
| `config/guardrails/d2/` (`config.yml`, `prompts.yml`) | New | The guardrail policy for D2 (section 3.6). A new folder beside `banking`; nothing in `banking` was changed | Loaded by `nbe-guardrails` | Loaded by `nbe-guardrails`, which already mounts `config/guardrails` |

The prompt for a procedure-only question is byte-identical to the previous version. One sentence about
tables and lists is added to the system prompt only when a scanned source is in the context.

### Portal

| Path | Kind | What and why | Dev | GB10 |
|---|---|---|---|---|
| `services/portal/src/workspaces/D2Chat.tsx` | Modified | Role selector, shown only when `/corpus` reports roles; scanned sources with page, relevance and preview; the detail block with image and text tabs; source chips; markers for a restricted reply, a guardrail stop and masked identifiers. Arabic and English. The `data-test` hooks used by the UI walkthrough are unchanged | Same code | Same code |

### Development setup only

| Path | Kind | What and why | GB10 |
|---|---|---|---|
| `docker-compose.api.yml` | New | Compose override. The model gateway joins a second network that has a route out and loads the API config; the embedding and reranker services run from a CPU image | Not used |
| `config/litellm.api.yaml` | New | Same aliases as `config/litellm.yaml`; the four chat aliases point at the model named by `NBE_API_MODEL` | Not loaded |
| `docker/dev-cpu-models/` | New | bge-m3 and bge-reranker-v2-m3 on CPU behind the same `/v1/embeddings` and `/v1/rerank` endpoints as the vLLM servers | Not built |
| `scripts/dev_api.sh` | New | `models`, `up`, `ingest`, `golden`, `down`. `up` also starts `nbe-guardrails` | Not used |
| `.env.api.example` | New | The three variables this setup adds to `.env` | Not needed |

### Documentation

| Path | Content |
|---|---|
| `D2/ahmedsoliman/documentation/README.md` | This document |
| `docs/d2-migration-plan.md` | The plan as agreed, the decisions, and where the build departed from it |
| `docs/d2-migration-log.md` | The dated log: each change with its reason and its effect on both setups, calibration evidence, verification record |

## 5. What was dropped from nbe-working and what replaced it

| nbe-working | In D2 | Reason |
|---|---|---|
| Milvus, etcd, Attu | Qdrant, already in the demo | One vector store for all seven demos |
| MinIO and nginx proxies for crops | D2 serves the crop files from `/data` | No extra service; also removes the world-readable bucket and the broken image addresses |
| NIM containers: Llama 3.1 8B, nemotron embedding and reranker | The demo's role aliases: Gemma 4 26B-A4B, bge-m3, bge-reranker-v2-m3 | The demo addresses models by role |
| LangChain, LangServe | Plain Python on `nbe_core` | Not installed in the demo image; no new dependency was added |
| Cloud NemoGuard safety calls on the question and the answer | The demo's local guardrails service with a D2 policy, plus a pattern rule that masks personal identifiers | Works offline; the checks are tailored to a staff knowledge assistant |
| Keyword topic gate | Removed | It blocked "البنك الأهلي" and "سياسة". Off-topic questions fall under the "not found" cut-off |
| 540 block-level chunks | 143 merged passages | Retrieval quality (section 3.2) |
| Citation markers `[1]` | `[S1]` | The portal, the cited-source detection and the golden test use this form |
| Always answers in Arabic | Answers in the language of the question | D2 behaviour |
| Token streaming | One response with the trace drawer | Decision: keep D2's single response |
| Teller refusal written by the model | Fixed sentence chosen by rule | Deterministic, and no forbidden text is shown to the model |
| Unknown role sees everything | Unknown role is rejected | Fail closed |
| Standalone React app with login screen | A panel inside the portal's D2 screen, portal theme | One portal for all demos |
| Chandra OCR extraction service | Ported on 12 October as a back-office service, off by default (section 12) | A client may ask for a new document to be added |
| Orchestrator, MinIO bucket and webhook as the upload trigger | `POST /upload` on D2, manager only (section 12) | No MinIO in the demo; one endpoint does the same job |
| SQLite document catalog | `manifest.json` | |

## 6. The temporary development setup

The workstation cannot hold the workhorse model, and its GPU is shared with other users, so D2 was developed
with the chat model on a hosted API. This setup exists only to make progress; nothing in it is used on the GB10.

| Component | Development workstation | GB10 |
|---|---|---|
| Chat model (`workhorse` alias) | OpenRouter `google/gemma-4-26b-a4b-it` | The same model, local, vLLM, FP8 |
| Embeddings | bge-m3 on CPU (`docker/dev-cpu-models`) | bge-m3 on GPU, vLLM |
| Reranker | bge-reranker-v2-m3 on CPU | bge-reranker-v2-m3 on GPU, vLLM |
| Guardrails | `nbe-guardrails`, judging through the hosted chat model | `nbe-guardrails`, judging through the local workhorse |
| Network | The model gateway can reach the internet | No container can |
| Start command | `scripts/dev_api.sh up` | `make up` |
| Published port | 8210 (8200 is used by another user on the same server) | 8200 |
| Retrieval time per question | About 9 s (18 s for the teller) | Well under a second expected |

The models are the same on both sides on purpose: vectors, reranker scores and the cut-offs carry over, and
the hosted chat model is the one the GB10 serves.

Workstation facts worth knowing:

- Docker in WSL does not start on boot: `sudo service docker start`.
- `.env` holds `NBE_API_MODEL`, `NBE_API_KEY`, `MODELS_DIR=/home/asoliman/models/nbe` and `NBE_PORT=8210`. It is git-ignored.
- `make up` must not be used there: it waits for local model servers, and its preflight stops other containers that hold GPU memory.

### 6.1 Setting it up from a fresh copy

For a teammate starting from a clone of the branch or from the shared zip (section 6.3), on a Linux or WSL
machine with Docker. Run from the project folder.

1. Start Docker if it is not running.

   ```bash
   sudo service docker start
   ```

2. Create the local settings file with fresh passwords, then add the development variables.

   ```bash
   make .env
   ```

   ```bash
   cat .env.api.example >> .env
   ```

   Edit `.env`: set `NBE_API_MODEL` (for example `openrouter/google/gemma-4-26b-a4b-it`), `NBE_API_KEY` (your own key),
   `MODELS_DIR` (any folder with 5 GB free), and `NBE_PORT` if 8200 is taken on your machine.

3. Download the two small local models (about 4.4 GB, once).

   ```bash
   scripts/dev_api.sh models
   ```

4. Start the stack. This builds the images, starts the services D2 needs and loads D2's data into the search index.

   ```bash
   scripts/dev_api.sh up
   ```

5. Run both golden sets (about 19 minutes on CPU), then open `http://localhost:<NBE_PORT>/d2`.

   ```bash
   scripts/dev_api.sh golden
   ```

### 6.2 Commands of the development setup

| Command | What it does | When |
|---|---|---|
| `scripts/dev_api.sh models` | Downloads bge-m3 and bge-reranker-v2-m3 into `MODELS_DIR` | Once per machine |
| `scripts/dev_api.sh up` | Builds and starts Postgres, Qdrant, the two CPU model servers, the model gateway, the guardrails service, D2, the portal and the web gateway; then ingests D2. Wait for it to finish before asking: answers come back "not found" while the index is being rebuilt | Every start, and after any code change |
| `scripts/dev_api.sh ingest` | Rebuilds D2's two collections from the seed files | After changing seed data, or if the index was wiped |
| `scripts/dev_api.sh golden` | Runs `tests/golden_d2.py` and `tests/golden_d2_circulars.py` | After any change to retrieval, prompts or data |
| `scripts/dev_api.sh down` | Stops and removes the containers; the index and database volumes are kept | When finished |

### 6.3 What the project folder holds and what lives outside it

The project folder, and therefore a clone or the shared zip, holds the code, the documentation and the seed
data: the 29 procedure files, the scanned-corpus manifest, 62 page files and 541 crop images, and both golden sets.

Three things are not in it and are recreated on each machine:

| Not in the project folder | Where it lives | How it is recreated |
|---|---|---|
| The search index (Qdrant collections `d2_procedures`, `d2_circulars`) and the Postgres data | Docker volumes on the machine | Ingest: `scripts/dev_api.sh up` on a workstation, `make ingest` on the GB10 |
| Model weights | `MODELS_DIR` on the workstation; `/opt/models` on the GB10 | `scripts/dev_api.sh models` on a workstation; already present on the GB10 (`make models` otherwise) |
| `data/generated/` (synthetic data of other demos) and `.env` (keys and passwords) | Git-ignored local files | `make data` (run automatically by `make up` on first start); `make .env`. D2 does not use `data/generated/` |

The zip shared with the team on 8 October 2026 (`NBE-demo_asoliman-d2-d7_2026-10-08.zip`) is a snapshot of the
working tree: every tracked file plus this documentation. It contains no `.env` and no git history, so it
cannot be used to pull the four commits; those arrive when the branch is pushed.

## 7. Moving to the GB10

### 7.1 What changes and what does not

| Area | On the GB10 |
|---|---|
| D2 service, passage builder, portal screen, corpus, golden sets | Used as they are. No code change is expected |
| Development-only files (section 4) | Ignored. They take effect only when passed to Compose with `-f` or run by hand |
| Model aliases | `config/litellm.yaml` as it is today: `workhorse` and `embed` already point at the local servers |
| Extra GPU memory | None. D2 adds no model; it makes one more embedding call and one more reranker call per question |
| Offline operation | Preserved. Crops are served by D2 inside the internal network; nothing in the D2 code calls out |
| Guardrails | `make up` already starts `nbe-guardrails`, and it already mounts `config/guardrails`, so the new `d2` policy folder is picked up on first use. No image rebuild is needed for it |
| `.env` | The GB10's own. None of the `NBE_API_*` variables |
| Model weights | Already in `/opt/models` on the GB10. Nothing new to download for D2 |
| Search index | Not carried over from the workstation. It is rebuilt on the GB10 by `make ingest` (step 4 below) |

### 7.2 Steps

Run on the GB10, in the repository folder.

1. Get the branch (through a pull request into `Efada_AI_Team`, or by checking out `asoliman/d2-d7`).
2. Rebuild the two images that changed. `make up` does not rebuild images that already exist.

   ```bash
   docker compose build nbe-d2 nbe-portal
   ```

3. Start the stack the usual way.

   ```bash
   make up
   ```

4. Load D2's data. This is required on a box that has run before, because the start script ingests only on first run.

   ```bash
   make ingest
   ```

   The D2 line should report `"scanned_passages":143,"scanned_documents":6`.

5. Run the checks.

   ```bash
   make verify
   ```

   ```bash
   docker run --rm --network nbe-core -v "$(pwd)/tests:/tests:ro" -v "$(pwd)/data:/data:ro" nbe-d2:latest python /tests/golden_d2.py http://nbe-d2:8000
   ```

   ```bash
   docker run --rm --network nbe-core -v "$(pwd)/tests:/tests:ro" -v "$(pwd)/data:/data:ro" nbe-d2:latest python /tests/golden_d2_circulars.py http://nbe-d2:8000
   ```

   ```bash
   make ui-test
   ```

   ```bash
   make offline-check
   ```

6. Open `http://localhost:8200/d2`, pick the teller role and ask the last suggested question; then repeat as legal counsel.

### 7.3 What to expect and what to re-check

| Item | Expectation | If it differs |
|---|---|---|
| Procedures golden set | 51/52 | Compare the misses with the one known miss (a KYC question the model declines). Any new miss that cites a scanned source points at the merge of the two corpora |
| Scanned golden set | 32/32, or close | The second output line prints the top reranker scores. Answer-bearing passages scored 0.92 to 1.00 on the development setup |
| Guardrail cases | 4/4 stopped, 4/4 legitimate questions allowed, identifiers masked | A legitimate question that is stopped points at the policy prompts in `config/guardrails/d2/prompts.yml`. Restart `nbe-guardrails` after editing them |
| Time per answer | Two extra workhorse calls: the README measures 120 to 600 ms for each check on the GB10 | |
| Reranker scores | The same scale, 0 to 1. Small differences from GPU half precision | If the scale differs, the three cut-offs in section 9 must be re-tuned together |
| Answers | Locally served Gemma is quantised to FP8, the hosted one is not. Wording can differ; a few borderline answers may flip | Check the scanned golden misses first; adjust prompts before cut-offs |
| Speed | Retrieval far faster than the 9 s seen on CPU | Not a D2 problem if slow: check the embedding and reranker servers |
| `make offline-check` | Passes | It fails only if the development override was started by mistake |

### 7.4 Before the branch is merged into the team branch

| Decision | Options |
|---|---|
| Development-only files | Keep them as an opt-in tool for anyone without a GB10, or remove them from the branch. They are inert either way |
| "Synthetic data only" | The README and the portal footer say it. The circulars and the RTGS guide are not synthetic. The team has to decide the wording |
| Shared documents | The README (D2 design, service reference, data table), `docs/talk-tracks.md` (the D2 presenter script) and `docs/runbook.md` do not describe scanned documents or roles yet |
| Published port | 8200 on the GB10; the 8210 setting lives only in the workstation's `.env` |

## 8. Verification and results

| Check | How | Result |
|---|---|---|
| Procedure behaviour unchanged | Old and new service code run side by side without the corpus, with stand-ins for the model and the vector store | Identical ingest result, identical prompts, identical answers apart from added fields |
| Service logic | 37 checks with the real code and seed data and the same stand-ins: mixed retrieval, citations, crops, every role rule, the version guards | 37 pass |
| Portal | Type check and production build; then by hand in a browser, Arabic and English | Pass |
| Service logic with guardrails | The same stand-ins plus a stand-in guardrails service, 48 checks | 48 pass, including: no guardrail call without the corpus, a jailbreak stopped before retrieval, both identifiers masked in the answer and in the source text, a withheld answer returning no sources |
| Procedures golden set, before guardrails | `tests/golden_d2.py` on the running stack, two runs on 8 October | 51/52 both times: current values 36/37, what changed 12/12, not found 3/3 |
| Procedures golden set, with guardrails | Same test, two runs on 9 October | 50/52, then 51/52 on the final code |
| Scanned golden set, before guardrails | `tests/golden_d2_circulars.py`, 25 questions | 25/25 |
| Scanned golden set, with guardrails | Same test, 32 questions | 32/32 on the final code: answers 14/14, restricted 4/4, open 4/4, unanswerable 5/5, guardrail stops 4/4, masked 1/1 |

The checks with stand-ins used throw-away scripts that are not in the repository. The two golden tests are the
checks anyone can re-run.

**About the 50/52.** No guardrail stopped or masked any of the 49 answerable procedures questions. The extra miss was a question about
urgent complaints: the test expects the answer to contain "24" (hours), and the hosted model sometimes writes
the shorter sentence without it. Asked four more times with the identical prompt, it included the 24 hours in
three and left it out in one. The hosted model is not fully repeatable from run to run; the locally served
model on the GB10 at temperature 0 should be. Treat 50 to 51 as the range on this setup.

One defect was found and fixed by the scanned golden set: the size cap had cut the last sentence of circular 4
("effective from 17 August 2025") into a passage of its own, and the question about that date failed. Short
remainders now stay with the passage before them.

## 9. Tuning values and where they live

| Value | Now | File | Meaning | Evidence |
|---|---|---|---|---|
| `FOUND_MIN` | 0.02 | `services/d2_chatdoc/app/main.py` | Below this reranker score nothing relevant was retrieved | All 8 unanswerable questions came back "not found" |
| `RESTRICTED_MIN` | 0.3 | same | From this score up, a forbidden passage counts as the answer | 4/4 restricted cases caught, no false "restricted" |
| Relevance bands | 0.5 and 0.1 | `services/portal/src/workspaces/D2Chat.tsx` | High, medium, low label on a scanned source | Answers score above 0.9, unrelated passages under 0.01 |
| `MAX_CHARS` | 1000 | `services/d2_chatdoc/app/scans.py` | Size cap of a passage | 143 passages, median 602 characters |
| `MIN_TAIL` | 250 | same | A shorter remainder joins the passage before it | Fixed the circular 4 miss |
| `DEFAULT_ROLE` | `manager` | `services/d2_chatdoc/app/main.py` | Role when a caller sends none | Keeps the existing golden test unchanged |
| `PII` pattern | 16 digits, 14 digits, Egyptian mobile numbers | same | What the identifier mask replaces | Both planted values in circular 1 are masked; amounts, dates, law numbers and SWIFT types are not touched |
| `GUARD_CONFIG` | `d2` | same | Which policy folder the guardrails service uses for D2 | |
| Policy wording | | `config/guardrails/d2/prompts.yml` | What the input and output checks block and allow | 4/4 stops, no legitimate question stopped among the 77 others that the tests can tell |

No value needed adjusting after the runs. The evidence is 25 questions and one model, so the golden sets
should be re-run after any model change. Changing `MAX_CHARS` or `MIN_TAIL` requires an ingest.

## 10. Maintenance

**Add or replace a scanned document**

There are two ways. Section 12 describes the intake path (upload a PDF, nothing else is re-ingested). The
steps below are the original way, through nbe-working, and end in a full ingest.

1. Extract it with nbe-working's extraction service, so that its page JSON and crops are in nbe-working's output folder.
2. Give it a title, type and roles in `DOCS` in `services/d2_chatdoc/tools/import_nbe_working.py` (documents named `legal_circular_N` get defaults).
3. Run the import, then rebuild D2 if code changed, then ingest.

   ```bash
   python3 services/d2_chatdoc/tools/import_nbe_working.py --source ~/projects/nbe-working
   ```

4. Add questions for it to `data/seed/golden/d2_circulars.json`.

**Change what the guardrails block:** edit `config/guardrails/d2/prompts.yml`, then restart `nbe-guardrails` (it caches a policy after first use) and re-run the scanned golden set.

**Change who may read a document:** edit `roles` in `data/seed/d2/circulars/manifest.json`, restart D2, ingest.

**Switch the scanned corpus off:** remove or rename `data/seed/d2/circulars`, restart D2, ingest. D2 returns to the procedures-only behaviour.

**Change the hosted model on the workstation:** set `NBE_API_MODEL` and `NBE_API_KEY` in `.env`, then `scripts/dev_api.sh up`.

## 11. Known limits and open items

- **Not yet run on the GB10.** Everything in section 7 is the expected path, not an observed one.
- **Small evidence base.** One model, 25 scanned questions.
- **The role is not authenticated.** It is a value the browser sends. A real deployment needs sign-on at the gateway.
- **The mask covers text, not images.** The answer and the text shown for a source are masked. The crop image of the scan still shows whatever is printed on the page.
- **The mask is a pattern.** It catches unbroken digit runs. A number written with spaces or dashes inside it is left to the output check.
- **The model-based checks are judgements.** They passed every test case here, but a differently worded attack or an unusual legitimate question can be misjudged. 4 stop cases is a small sample.
- **No answer without the guardrails service.** If `nbe-guardrails` is down, D2 returns an error, by design.
- **Upload is back-office only, and the OCR model has not been run from this repository.** Section 12 lists what was and was not verified.
- **OCR quality.** The RTGS text has systematic misspellings ("الحظية", "الخطية" for "اللحظية"). Retrieval coped in testing, but exact-word matching would not.
- **Sample personal data.** `legal_circular_1` contains a phone number and a 14-digit national-ID-style number in its text. They read like planted test values, but they are now in the repository.
- **No highlight on the full page.** Page images were not shipped, and the stored bounding boxes are not in one coordinate space, so the citation shows crops only.
- **`make ui-test` has not been run** with these changes. The hooks it uses are unchanged.
- **Shared documents are not updated** (section 7.4).
- **D7** has its own documentation: `D7/ahmedsoliman/documentation/README.md`.

## 12. Adding a new scanned document (intake, added 12 October 2026)

For the case where the client asks for a new document to be added. It is a back-office task, not part of the
demo flow, and only a manager may do it. Nothing has to be re-ingested and no collection is rebuilt.

### 12.1 What happens to an uploaded PDF

| Step | Where | What |
|---|---|---|
| 1. Upload | D2, `POST /upload` | The PDF is saved on the uploads volume. The document id is the file name without `.pdf`, as nbe-working's orchestrator derived it |
| 2. Extraction | `nbe-d2-extract` | nbe-working's extraction service: pages rendered at about 200 dpi, Chandra OCR-2 reads each page into typed blocks, one crop image per block, one JSON file per page, in nbe-working's output layout |
| 3. Normalisation | D2, `app/intake.py` | That output is rewritten into the layout of `data/seed/d2/circulars`, by the same rules as `tools/import_nbe_working.py` |
| 4. Passages | D2, `app/scans.py` | The existing passage builder, unchanged: blocks under one heading on one page become one passage that keeps its list of crops |
| 5. Index | D2, `index_doc()` | The document's old passages are deleted from `d2_circulars`, its new ones are embedded and added, and the in-memory corpus is reloaded. No other document is touched |

A document with a page the OCR could not read is not indexed; the job fails and names the pages.

### 12.2 What replaced MinIO

| MinIO's job in nbe-working | Here |
|---|---|
| A PDF dropped in the `nbe-ingestion` bucket fired a webhook to the orchestrator | `POST /upload` starts the same sequence; one document at a time |
| Crops and page images were uploaded and served by address | Crops stay on the volume and are served by the existing `/crop` endpoint, with the role check |

### 12.3 Files

| File | Status | Purpose |
|---|---|---|
| `services/d2_extraction/` | new | The extraction service. `extractor.py`, `cropper.py`, `coords.py` and `schemas.py` are nbe-working's files with imports renamed. Changed: the model is loaded from a local folder with no login; the service takes a PDF and renders it itself; nothing is forwarded to an indexing service; a new submission clears that document's earlier output |
| `services/d2_chatdoc/app/intake.py` | new | The upload endpoints, the call to the extraction service, and the normalisation |
| `services/d2_chatdoc/app/main.py` | changed | Loads the seed corpus plus uploaded documents; `scan_points()` and `index_doc()`; registers the intake endpoints |
| `services/d2_chatdoc/app/scans.py` | changed | `load_all()` reads several corpus folders as one; a block with no crop no longer breaks loading |
| `docker-compose.d2-extract.yml` | new | The uploads volume, the extraction service (profile `extract`), and the two settings D2 needs |
| `scripts/d2_upload.sh` | new | Upload a file and wait; list; remove |
| `tests/d2_intake_equivalence.py` | new | Proves the intake output equals the seed corpus (section 12.6) |
| `tests/stub_d2_extraction.py` | new | Stand-in for the extraction service that replays an existing extraction; for testing without a GPU |

No shared file was edited. Without `docker-compose.d2-extract.yml`, D2 has no uploads volume and no extraction
address: `/upload` answers 404 and D2 behaves as before.

### 12.4 How to use it

```bash
# once, on a machine with internet (the model is gated: the account must have accepted its terms)
hf download datalab-to/chandra-ocr-2 --local-dir "$MODELS_DIR/chandra-ocr-2"

C="docker compose -f docker-compose.yml -f docker-compose.d2-extract.yml"   # workstation: add -f docker-compose.api.yml
$C --profile core up -d --wait nbe-d2                         # D2 with the uploads volume
$C --profile extract up -d --wait --build nbe-d2-extract      # only while adding documents

scripts/d2_upload.sh circular_12.pdf "تعميم قانوني رقم 12" "Legal circular no. 12"
scripts/d2_upload.sh rtgs_v2.pdf "دليل ..." "RTGS guide v2" sop teller,legal_counsel,manager
scripts/d2_upload.sh --list
scripts/d2_upload.sh --remove circular_12

$C --profile extract stop nbe-d2-extract                      # frees the GPU memory
```

- Uploading a file with the same name again replaces that document.
- Uploading a file named like a seed document (for example `legal-circular_4.pdf`) replaces the seed copy for as
  long as the upload exists; removing the upload brings the seed copy back.
- Default readers are legal counsel and manager. The manager is always added.
- A full `make ingest` keeps uploaded documents: it now reads both folders.

### 12.5 API

| Endpoint | Notes |
|---|---|
| `POST /upload` | Multipart: `file`, `role` (must be `manager`), `title_ar`, `title_en`, `doc_type` (`legal_circular` or `sop`), `roles`. Returns a job, HTTP 202 |
| `GET /upload/jobs/{id}?role=manager` | `accepted`, `extracting`, `indexing`, `complete` or `failed` with the reason |
| `GET /upload/jobs?role=manager`, `GET /upload/documents?role=manager` | Jobs since D2 started; documents added by upload |
| `DELETE /upload/{doc_id}?role=manager` | Removes an uploaded document and its passages |

### 12.6 What was verified, and what was not

Verified on the workstation, 12 October, without the OCR model:

| Check | Result |
|---|---|
| `tests/d2_intake_equivalence.py`: all six seed documents taken from nbe-working's extraction output through `intake.normalise` | Identical to the seed corpus: 6 manifest entries, 62 page files and 541 crop images byte for byte, and the same 143 passages |
| Upload of circular 4 (already in the corpus), with the stand-in extraction service | Collection stays at 143 passages; the document's 2 stored passages have identical payloads and embedding vectors (cosine 1.000000) to the seed copy; the 57 RTGS passages are untouched; the golden question about circular 4 is answered with the same four crops |
| Upload of the same pages as a new document (`legal-circular_9`) | 143 to 145 passages, 6 to 7 documents, no ingest; its crop is served to a manager; a teller asking about it gets the restricted reply |
| Procedures collection during all of this | 203 sections throughout |
| A teller uploads; a non-PDF is uploaded | Refused: HTTP 403; HTTP 400 |
| Full ingest with an uploaded document present | 145 scanned passages, 7 documents: the upload is kept |
| Removing both uploads | Back to 143 passages and 6 documents; circular 4 falls back to its seed copy with identical payloads |
| Upload while the extraction service is not running | The job fails with a reason; nothing is indexed |
| Both golden sets on the rebuilt D2, after the uploads were removed | Procedures 51/52 (current value 36/37, delta 12/12, unanswerable 3/3); scanned 32/32. The same totals as before the change |

Not verified:

- **The extraction service image has not been built and the Chandra model has not been run from this
  repository.** The workstation's GPU was fully in use by other users (31.5 of 32.6 GB). The Python files
  compile; nothing more is known.
- **Whether a fresh OCR run reproduces the stored blocks exactly.** Circulars 3, 4 and 5 were extracted by
  this same service code with the same settings (render scale 2.7, longest side 2000). Circulars 1 and 2 and
  the RTGS guide came from the earlier notebook, which fed the model full-size pages (for example 2480 by
  3509), so re-extracting those three with the service settings may split blocks differently. A real run on a
  free GPU is needed to know; the passage logic after that point is proven identical.
- **Chandra on the GB10.** It is loaded 4-bit through bitsandbytes on a CUDA 12.4 x86 image, as in nbe-working.
  Its memory need next to the other model servers, and whether that stack runs on the GB10's hardware, are open.
- **The portal has no upload screen.** The script is the interface.

### 12.7 Effect on the two setups

**Workstation setup.** D2 now runs with both override files (section 12.8): the uploads volume exists and is
empty, and D2 points at the GB10 for extraction. `scripts/dev_api.sh up` does not include the overrides; if
documents have been uploaded, start D2 with them, or run an ingest without them to drop the uploads from the
collection.

**GB10.** `make up` alone is unchanged. To offer intake there: copy the model folder to `$MODELS_DIR`, build
`nbe-d2-extract` (it needs internet once for the Python packages, or a pre-built image), and start D2 with the
override file. Run one real document and compare its passages before promising this to a client.

### 12.8 Extraction on the GB10, D2 on the workstation (changed later on 12 October)

The model will live on the GB10, which has the GPU memory for it; D2 stays on the workstation. The first
version of the intake passed file paths on a volume both services mounted, which cannot work across two
machines, so the exchange now goes over HTTP in every setup:

| | First version | Now |
|---|---|---|
| D2 to the service | A path to the PDF on a shared volume | The PDF itself, in a multipart request |
| The service to D2 | Page JSON and crops written to the shared volume | `GET /v1/jobs/{id}/result`: one zip, unpacked by D2 after checking every path in it |
| The service's files | On D2's uploads volume | In its own working volume |

| File | Status | Purpose |
|---|---|---|
| `services/d2_extraction/app/main.py` | changed | Multipart submit, result as a zip, optional bearer token (`EXTRACTION_TOKEN`) |
| `services/d2_extraction/app/extractor.py`, `config.py` | changed | `LOAD_IN_4BIT=0` loads the model without bitsandbytes |
| `services/d2_extraction/Dockerfile` | changed | Build arguments for the base image and the torch wheel index |
| `services/d2_extraction/docker-compose.yml`, `README.md` | new | Stand-alone start on the GB10 (port 8010) and the steps for it. The folder is self-contained |
| `services/d2_chatdoc/app/intake.py` | changed | Sends the file, fetches and unpacks the result, sends the token if one is set |
| `docker-compose.d2-extract-remote.yml` | new | Workstation only: D2 also joins `nbe-egress` to reach the GB10, address `http://100.69.85.46:8010` |
| `docker-compose.d2-extract.yml` | changed | The same-machine service keeps its own working volume; the address and token can be set in `.env` |
| `tests/stub_d2_extraction.py` | changed | Same new API |

Steps on the GB10 and on the workstation: `services/d2_extraction/README.md`.

Verified on the workstation with the stand-in service placed on the egress network only, as the GB10 is, and
protected by a token:

| Check | Result |
|---|---|
| `tests/d2_intake_equivalence.py` | Still identical to the seed corpus |
| Upload of circular 4 | 143 passages; identical payloads; vectors equal to the stored ones (cosine 0.999999, embeddings now on the GPU) |
| Upload of a new document, then removal of both | 145, crop served, then back to 143 with circular 4 on its seed copy |
| Wrong token | The job fails with "401 missing or wrong token"; nothing is indexed |

Still not verified: the image build, the model load and a real extraction, now on the GB10's hardware. The
service has only ever been built for an x86 workstation. `services/d2_extraction/README.md` lists the settings
for the likely failures (no GPU build of torch, bitsandbytes not running).

Side effect to know: with the remote override, D2 on the workstation has a route out of the internal network,
which it did not have before. That is a property of the workstation setup only.
