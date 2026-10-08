# D2 · Chat with Document: scanned documents, visual citations and roles

What was changed in the NBE demo to bring the nbe-working knowledge assistant into D2, how it works,
how it was verified, and what to do when it moves back to the fully local deployment on the GB10.

| | |
|---|---|
| Owner | Ahmed Soliman (D2, later D7) |
| Branch | `asoliman/d2-d7`, cut from `Efada_AI_Team` at `e8287b6` |
| Commits | `f6ab844` data · `6468718` backend · `59ce0c7` portal · `892ee00` API setup and docs |
| Written | 8 October 2026 |
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
the crop images of the scan beside each citation, and limits what each role may read.

Three rules kept the change from disturbing the rest of the demo:

1. **Two collections, never one.** Procedures stay in `d2_procedures`; scanned passages go to `d2_circulars`.
2. **Switched on by data.** Without the folder `data/seed/d2/circulars`, D2 behaves exactly as before.
3. **No shared file edited.** `packages/nbe_core`, `docker-compose.yml`, `config/litellm.yaml`, the `Makefile`, the existing scripts and the README are untouched.

Measured on the development setup with Gemma 4 26B-A4B:

| Test | Result |
|---|---|
| Procedures golden set, 52 questions | 51/52, the same as the README baseline |
| Scanned-corpus golden set, 25 questions | 25/25 |

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

### 3.6 API

All paths are under `/api/d2` through the gateway.

| Endpoint | Change | Purpose |
|---|---|---|
| `POST /ask` | Accepts `role` (default `manager`). Response adds `restricted`; each citation adds `kind` | Answer a question |
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
| `data/seed/golden/d2_circulars.json` | New | 25 test questions for the scanned corpus and the role rules | | |

### Service

| Path | Kind | What and why | Dev | GB10 |
|---|---|---|---|---|
| `services/d2_chatdoc/app/scans.py` | New | Loads the corpus, builds passages, converts tables, defines the roles (sections 3.1 and 3.2) | Same code | Same code |
| `services/d2_chatdoc/app/main.py` | Modified | Loads the corpus when present; ingests `d2_circulars`; `/ask` takes a role, merges both searches, applies the access rule, keeps scans out of the version logic; new `/crop` and `/corpus`; citations gain `kind`; the early "not found" reply now carries `lang` and `total_ms` (the portal printed "NaN s") | Same code | Same code |
| `tests/golden_d2_circulars.py` | New | Runs the 25 questions and prints the top reranker scores for calibration | Run by `scripts/dev_api.sh golden` | Run directly (section 7) |

The prompt for a procedure-only question is byte-identical to the previous version. One sentence about
tables and lists is added to the system prompt only when a scanned source is in the context.

### Portal

| Path | Kind | What and why | Dev | GB10 |
|---|---|---|---|---|
| `services/portal/src/workspaces/D2Chat.tsx` | Modified | Role selector, shown only when `/corpus` reports roles; scanned sources with page, relevance and preview; the detail block with image and text tabs; source chips; the restricted marker. Arabic and English. The `data-test` hooks used by the UI walkthrough are unchanged | Same code | Same code |

### Development setup only

| Path | Kind | What and why | GB10 |
|---|---|---|---|
| `docker-compose.api.yml` | New | Compose override. The model gateway joins a second network that has a route out and loads the API config; the embedding and reranker services run from a CPU image | Not used |
| `config/litellm.api.yaml` | New | Same aliases as `config/litellm.yaml`; the four chat aliases point at the model named by `NBE_API_MODEL` | Not loaded |
| `docker/dev-cpu-models/` | New | bge-m3 and bge-reranker-v2-m3 on CPU behind the same `/v1/embeddings` and `/v1/rerank` endpoints as the vLLM servers | Not built |
| `scripts/dev_api.sh` | New | `models`, `up`, `ingest`, `golden`, `down` | Not used |
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
| Cloud NemoGuard safety calls and the keyword topic gate | Removed | They needed the internet, and the keyword gate blocked "البنك الأهلي" and "سياسة". Off-topic questions fall under the "not found" cut-off |
| 540 block-level chunks | 143 merged passages | Retrieval quality (section 3.2) |
| Citation markers `[1]` | `[S1]` | The portal, the cited-source detection and the golden test use this form |
| Always answers in Arabic | Answers in the language of the question | D2 behaviour |
| Token streaming | One response with the trace drawer | Decision: keep D2's single response |
| Teller refusal written by the model | Fixed sentence chosen by rule | Deterministic, and no forbidden text is shown to the model |
| Unknown role sees everything | Unknown role is rejected | Fail closed |
| Standalone React app with login screen | A panel inside the portal's D2 screen, portal theme | One portal for all demos |
| Chandra OCR, orchestrator, upload | Not ported | Out of scope: the pre-extracted pages are shipped as seed data |
| SQLite document catalog | `manifest.json` | |

## 6. The temporary development setup

The workstation cannot hold the workhorse model, and its GPU is shared with other users, so D2 was developed
with the chat model on a hosted API. This setup exists only to make progress; nothing in it is used on the GB10.

| Component | Development workstation | GB10 |
|---|---|---|
| Chat model (`workhorse` alias) | OpenRouter `google/gemma-4-26b-a4b-it` | The same model, local, vLLM, FP8 |
| Embeddings | bge-m3 on CPU (`docker/dev-cpu-models`) | bge-m3 on GPU, vLLM |
| Reranker | bge-reranker-v2-m3 on CPU | bge-reranker-v2-m3 on GPU, vLLM |
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
| `scripts/dev_api.sh up` | Builds and starts Postgres, Qdrant, the two CPU model servers, the model gateway, D2, the portal and the web gateway; then ingests D2 | Every start, and after any code change |
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
| Scanned golden set | 25/25, or close | The second output line prints the top reranker scores. Answer-bearing passages scored 0.92 to 1.00 on the development setup |
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
| Procedures golden set | `tests/golden_d2.py` on the running stack | 51/52: current values 36/37, what changed 12/12, not found 3/3 |
| Scanned golden set | `tests/golden_d2_circulars.py` on the running stack | 25/25: answers 14/14, restricted 4/4, open 2/2, unanswerable 5/5 |

The first two checks used throw-away scripts that are not in the repository. The two golden tests are the
checks anyone can re-run.

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

No value needed adjusting after the runs. The evidence is 25 questions and one model, so the golden sets
should be re-run after any model change. Changing `MAX_CHARS` or `MIN_TAIL` requires an ingest.

## 10. Maintenance

**Add or replace a scanned document**

1. Extract it with nbe-working's extraction service, so that its page JSON and crops are in nbe-working's output folder.
2. Give it a title, type and roles in `DOCS` in `services/d2_chatdoc/tools/import_nbe_working.py` (documents named `legal_circular_N` get defaults).
3. Run the import, then rebuild D2 if code changed, then ingest.

   ```bash
   python3 services/d2_chatdoc/tools/import_nbe_working.py --source ~/projects/nbe-working
   ```

4. Add questions for it to `data/seed/golden/d2_circulars.json`.

**Change who may read a document:** edit `roles` in `data/seed/d2/circulars/manifest.json`, restart D2, ingest.

**Switch the scanned corpus off:** remove or rename `data/seed/d2/circulars`, restart D2, ingest. D2 returns to the procedures-only behaviour.

**Change the hosted model on the workstation:** set `NBE_API_MODEL` and `NBE_API_KEY` in `.env`, then `scripts/dev_api.sh up`.

## 11. Known limits and open items

- **Not yet run on the GB10.** Everything in section 7 is the expected path, not an observed one.
- **Small evidence base.** One model, 25 scanned questions.
- **The role is not authenticated.** It is a value the browser sends. A real deployment needs sign-on at the gateway.
- **No live upload.** New scanned documents go through nbe-working's OCR offline (section 10).
- **OCR quality.** The RTGS text has systematic misspellings ("الحظية", "الخطية" for "اللحظية"). Retrieval coped in testing, but exact-word matching would not.
- **Sample personal data.** `legal_circular_1` contains a phone number and a 14-digit national-ID-style number in its text. They read like planted test values, but they are now in the repository.
- **No highlight on the full page.** Page images were not shipped, and the stored bounding boxes are not in one coordinate space, so the citation shows crops only.
- **`make ui-test` has not been run** with these changes. The hooks it uses are unchanged.
- **Shared documents are not updated** (section 7.4).
- **D7** has not been started.
