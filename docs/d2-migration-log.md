# D2 migration log

Record of every change made to bring nbe-working into D2: what changed, why, and what it means for
the temporary API setup and for the return to the fully local deployment on the big machine (GB10).
Plan: [d2-migration-plan.md](d2-migration-plan.md).
Reference documentation (how it works, every change, the GB10 move): [D2/ahmedsoliman/documentation/README.md](../D2/ahmedsoliman/documentation/README.md).

| | |
|---|---|
| Branch | `asoliman/d2-d7`, based on `Efada_AI_Team` at `e8287b6` |
| Entry date | 8 October 2026 |
| State | Committed on `asoliman/d2-d7`: four commits (data, backend, portal, API override with docs) one documentation commit, and one commit for the guardrails of 9 October (section 7). Not pushed |
| Shared files edited | None. `packages/nbe_core`, `docker-compose.yml`, `config/litellm.yaml`, `Makefile`, existing `scripts/*`, `README.md` are untouched |

## 1. Where things stand

| Phase | State | Evidence |
|---|---|---|
| 0. Temporary API environment | Running on the workstation | Chat on OpenRouter `google/gemma-4-26b-a4b-it` (the same model the GB10 serves locally); bge-m3 and bge-reranker-v2-m3 local on CPU |
| 1. Data import | Done | 6 documents, 62 pages, 541 blocks, 541 crops, 36 MB |
| 2. Backend | Done | Offline check 37/37; real stack: section 5 |
| 3. Portal citation panel | Done | Type-checks, builds, checked in a browser on the running stack in Arabic and English |
| 4. Quality | First pass done | Procedures golden set 51/52 (unchanged from the README baseline); scanned-corpus golden set 25/25; cut-offs confirmed, section 4 |
| Guardrails (added after the plan) | Done on 9 October | Section 7: scanned golden set 32/32, procedures 51/52 |
| 5. Big machine | Not started | |

## 2. Change log

"API" is the temporary setup (chat model on an external API). "Local" is the final GB10 deployment.

| # | Path | Kind | What changed | Why | Impact on API setup | Impact on local deployment |
|---|---|---|---|---|---|---|
| 1 | `data/seed/d2/circulars/` | New, 604 files | `manifest.json` (6 documents with titles, type, roles), `extractions/<doc>/page_NNN.json` (OCR blocks), `crops/<doc>/page_NNN/*.png` (one image per block) | The scanned corpus and its crop images, taken from nbe-working. Under `data/seed` because seed data is committed and mounted read-only into D2 at `/data` | Passage text of these documents is sent to the external chat API when cited (approved) | Ships with the repo; no copying by hand. Adds 36 MB to the repository |
| 2 | `services/d2_chatdoc/tools/import_nbe_working.py` | New | Host-side script that produced item 1 from nbe-working's two extraction folders. Normalises document ids to underscores, corrects the document type of circulars 3 to 5, drops machine-specific page image paths | Reproducible import; nbe-working mixes `legal_circular_3` and `legal-circular_4` and types circulars as SOP | None (run once on the workstation) | None. D2 never needs nbe-working at run time |
| 3 | `services/d2_chatdoc/app/scans.py` | New | Loads the corpus and merges OCR blocks into passages: the run of blocks under one heading on one page, capped at 1,000 characters; a table is its own passage. Each passage keeps the ids of its blocks. Converts table HTML to plain rows (prompt) and a Markdown table (display). Drops footers, letterheads and page counters. Defines the three roles | Decision 1: merged passages for retrieval quality, with a mapping back to crops. A remainder under 250 characters left by the cap joins the passage before it. 541 blocks become 143 passages (median 602 characters, against a median block of 95) | None: pure Python | None: same code path |
| 4a | `services/d2_chatdoc/app/main.py` | Modified | `load_docs()` also loads the scanned corpus when `data/seed/d2/circulars/manifest.json` exists | The feature switches on by data; without the folder D2 is unchanged | None | None |
| 4b | same | Modified | `/admin/ingest` also builds collection `d2_circulars` (one point per passage; payload carries document, page, heading, display text, block list, roles) | Separate collection so the procedure payload shape is never mixed with scans | Embeddings are local in both modes | `make ingest` loads both collections. **On a box that already ran `make up`, run `make ingest` once after pulling**: `scripts/up.sh` only ingests on first run |
| 4c | same | Modified | `/ask` accepts `role` (default `manager`). With the corpus present it searches both collections, keeps the best six by reranker score, and builds the answer from the mix | One question must reach both corpora; scores are comparable because the reranker and query are the same | One extra embedding and rerank call per question, both local | Same |
| 4d | same | Modified | Role-based access: the scanned search is filtered by the role; for a role that cannot read everything, a second unfiltered search yields only the best score among forbidden passages. If that score is at least `RESTRICTED_MIN` (0.3) and nothing permitted matches as well, or the model finds no answer in permitted sources, the reply is a fixed "outside your access" sentence with no citations | Decision 4: keep teller / legal counsel / manager. Forbidden text never reaches the model or the browser | Forbidden passages are never sent to the external API | Same |
| 4e | same | Modified | Three guards so scans cannot enter the version logic: the "what changed" branch runs only when the top hit is a procedure; the current-version sort treats scans as neutral; version delta is skipped when the primary citation is a scan | D2 reads `version`, `procedure` and `file.split("_")[0]` on every hit; a scan has none of them | None | None |
| 4f | same | Modified | Prompt: scanned sources are labelled with title, page and heading; one sentence about tables and lists is appended to the system prompt **only when a scanned source is in the context** | Keeps procedure-only prompts byte-identical (verified), so the 52-question golden set is not disturbed | None | None |
| 4g | same | Modified | Citations gain `kind` (`procedure` or `scan`); scan citations also carry `doc_id`, `page`, `block_type`, `crops` (block ids) and reuse the existing fields (`file`, `title`, `section`, `text`, ...) | The portal and `tests/golden_d2.py` read the existing fields; nothing they rely on moved | None | None |
| 4h | same | New endpoints | `GET /crop/{doc_id}/{block_id}?role=` serves one crop image after checking the role; ids are looked up in the manifest, never used as file paths. `GET /corpus` lists roles and scanned documents | Replaces MinIO and the nginx proxies of nbe-working. `/documents` is left as is because `scripts/up.sh` greps its output | None | Works offline; nothing to deploy besides D2 |
| 4i | same | Modified | The early "not found" reply now includes `lang` and `total_ms`; `/suggested` appends two scanned-corpus questions after the original five when the corpus is present | The portal printed "NaN s" on that reply. The first suggestion stays a procedure question because the UI walkthrough clicks it | None | None |
| 5 | `services/portal/src/workspaces/D2Chat.tsx` | Modified | Role selector (shown only when `/corpus` returns roles). Scanned sources in the answer card show page, relevance band and a preview. Selecting one opens a detail block with two tabs: the crop images of the scan (loading skeleton, error state) and the text (tables as tables), plus an "open original image" link. Source chips under answers that cite scans. A red "outside this role's access" marker. Procedure sources keep the Markdown viewer | Decision 2: nbe-working's citation panel, same elements and behaviour, in the portal's theme and both languages. `data-test="suggested"` and `data-test="answer"` are unchanged for the UI walkthrough | None | None |
| 6 | `docker-compose.api.yml` | New | Compose override: `nbe-llmgw` loads `config/litellm.api.yaml` and joins a new network `nbe-egress` (the only route out); `nbe-embed` and `nbe-rerank` run the CPU image of item 11 instead of vLLM, with no GPU reservation and no wait for `nbe-llm` | The workstation cannot hold the workhorse, and its GPU is shared: two other virtual machines on the server held about 30 of 32 GB during setup. The base compose file is not edited | Required. `make offline-check` and the offline part of `make verify` fail by design in this mode | **Not used.** Start with `make up` as documented; the file is inert unless passed with `-f` |
| 7 | `config/litellm.api.yaml` | New | Same aliases as `config/litellm.yaml`; `workhorse`, `vision`, `quality`, `hero` point at one external model named by `NBE_API_MODEL`; `embed` stays on local bge-m3 | Demo code addresses aliases only, so switching models is configuration | Required | Not loaded |
| 8 | `.env.api.example` | New | The three variables the API setup adds to `.env`: `NBE_API_MODEL`, `NBE_API_KEY`, `MODELS_DIR` | Keeps `.env.example` (shared) untouched | Copy into `.env` and fill in | Not needed |
| 9 | `scripts/dev_api.sh` | New | `models`, `up`, `ingest`, `golden` (both golden sets), `down` for the API setup, starting only what D2 needs | `make up` cannot be used on the workstation: it waits for local model servers and its preflight stops every other GPU container | Entry point | Not used |
| 10 | `docs/d2-migration-plan.md`, `docs/d2-migration-log.md`, `D2/ahmedsoliman/documentation/README.md` | New | Plan, this log, and the reference documentation: how D2 works now, every change, the development setup, the steps and checks for the GB10 | Documentation directive | | |
| 11 | `docker/dev-cpu-models/` (`Dockerfile`, `server.py`) | New | A small CPU server with the two endpoints the demo calls on the vLLM pooling servers, `/v1/embeddings` and `/v1/rerank`, loading the same weights | No free GPU memory on the workstation. vLLM's x86 CPU build targets AVX-512, which this processor does not have, so it was not tried. Same models, so vectors, reranker scores and cut-offs carry over | Required. Retrieval takes about 9 s per question on CPU (18 s for a limited role), against well under a second on GPU | **Not used.** The GB10 serves both models with vLLM as before |
| 12 | `data/seed/golden/d2_circulars.json`, `tests/golden_d2_circulars.py` | New | 25-question golden set for the scanned corpus: 14 answers (expected document cited with crops, expected phrase present), 4 restricted, 2 procedure questions from a limited role, 5 unanswerable. Prints top reranker scores for calibration | Phase 4: measure the scanned corpus and the role rules the way the procedures are measured. `tests/golden_d2.py` is untouched | Run by `scripts/dev_api.sh golden` | Run with `python tests/golden_d2_circulars.py` next to the existing golden test |

Outside the repository (workstation only): `.env` was created with `make .env` and holds the API settings; `NBE_PORT` is set to **8210** there because port 8200 on this server is published by another user's copy of the demo; the Docker daemon in WSL was started by hand (it does not start on boot); the two model folders are in `/home/asoliman/models/nbe`.

## 3. Deliberate differences from nbe-working

| nbe-working | D2 now | Reason |
|---|---|---|
| 540 block-level chunks | 143 passages; a citation shows the crops of all its blocks, stacked | Decision 1 |
| Footers dropped; letterheads and page counters indexed | All three dropped | Repeated on every page, never an answer |
| Cloud NemoGuard safety before and after | Local guardrails service with a D2 policy, plus a pattern rule that masks personal identifiers (added 9 October, section 7) | Offline; tailored to a staff assistant |
| Keyword topic gate | Removed | It blocked "البنك الأهلي" and "سياسة". Off-topic questions fall under the "not found" cut-off |
| Citation markers `[1]` | `[S1]` | The portal, the cited-source detection and the golden test use `[S n]` |
| Always answers in Arabic | Answers in the question's language | D2 behaviour; nbe-working's rule was a defect |
| Token streaming with stage events | One response with the trace drawer | Decision 5 |
| Teller refusal written by the model from a prompt instruction | Fixed sentence chosen by rule, same wording | Deterministic; no forbidden text is shown to the model to produce it |
| Unknown role gets access to everything | Unknown role is rejected (HTTP 400) | Fail closed |
| Crops in world-readable MinIO buckets | Crop endpoint checks the role | The role is still a client-supplied string, as in nbe-working: there is no login in the demo |
| Relevance labels at reranker scores 6 and 2 | Provisional bands at 0.5 and 0.1 | Different reranker scale (0 to 1) |
| Document labels hardcoded in the UI for 3 documents | Titles in the manifest for all 6, Arabic and English | |

## 4. Calibration and what is still open

Measured on the running stack (section 5):

| Cut-off | Value | Evidence | Verdict |
|---|---|---|---|
| `FOUND_MIN` (nothing relevant retrieved) | 0.02 | All 8 unanswerable questions across both golden sets came back "not found"; every answerable question scored far above | Keep |
| `RESTRICTED_MIN` (a forbidden passage counts as the answer) | 0.3 | The top source of the 14 answerable scanned questions scored 0.92 to 1.00; unrelated passages scored under 0.01. 4/4 restricted cases caught, and no false "restricted" in the 4 open and unanswerable cases asked as teller | Keep |
| Relevance bands in the portal | 0.5 / 0.1 | Same distribution: answers sit above 0.9, weak matches around 0.2, unrelated under 0.01 | Keep |

No cut-off needed adjusting. One chunking fix came out of the run: a question about circular 4 failed because the size cap had split off its last sentence ("effective from 17 August 2025") into a passage of its own. Short remainders now stay with the passage before them (item 3), and the set went from 24/25 to 25/25.

Confirmed on the first real run: Qdrant matches the role against a list payload field; LiteLLM resolves the model name from the environment; the override starts cleanly.

Still open:

1. **Small sample.** 25 scanned questions and one hosted model. Re-run both golden sets on the big machine, where a locally served Gemma answers.
2. **Speed is not representative.** Retrieval is on CPU here; these timings are not the demo's.
3. **`make ui-test`** (Playwright) has not been run; the hooks it uses are unchanged.
4. **The one procedures miss** (51/52) is a KYC question ("what is the new channel?") that the model declines although the right section is retrieved. All six sources for it are procedures, so it is independent of this migration and matches the README's 36/37.

Observations for the team:

- `legal_circular_1` contains a phone number and a 14-digit national-ID-style number inside its text (they read like planted test values). That text is now in the repository and can be sent to the external API.
- The RTGS guide's OCR text has systematic misspellings ("الحظية", "الخطية" for "اللحظية"). Retrieval depends on the embedding model tolerating them.
- The README and the portal footer state "synthetic data only". With this corpus that is no longer accurate. Both are shared files and were not changed; the team should decide the wording.

## 5. Verification record (8 October 2026)

**Running stack** (OpenRouter Gemma 4 26B-A4B for chat, local bge-m3 and bge-reranker-v2-m3 on CPU, Qdrant, portal on port 8210):

- Ingest: 203 procedure sections, 143 scanned passages from 6 documents.
- `tests/golden_d2.py`: **51/52** (current values 36/37, what changed 12/12, not found 3/3), identical to the README baseline, with the scanned corpus loaded.
- `tests/golden_d2_circulars.py`: **25/25** (answers 14/14, restricted 4/4, open 2/2, unanswerable 5/5).
- Portal in the browser: role selector, suggested questions, an RTGS answer with its crops, a circular answer for legal counsel with three crops and the text tab, the restricted reply for the teller on the same question.

**Offline service check** (real `main.py`, `scans.py` and seed data; Qdrant, reranker and model replaced by in-memory fakes with lexical scoring). 37 checks, all pass:

- Corpus absent, new code against the committed version: identical ingest result (203 sections, 29 documents), identical `/documents` and `/suggested`, **identical prompts sent to the model** over six questions, identical answers apart from the added fields.
- Corpus present: ingest loads the passages of all 6 documents; mixed retrieval; scan citations carry every field the portal and golden test read; crops served as PNG; wrong-document and path-like ids return 404.
- Roles: teller reads the RTGS guide; teller asking a circular question gets the restricted reply with no titles or content, and no restricted passage reaches the model (both routes: weak permitted match, and model finding no answer); teller fetching a circular crop gets 403; legal counsel gets 200; unknown role gets 400; manager never gets "restricted".
- Version logic: "what changed" wording on a scanned top hit returns a normal answer; a procedure question still returns its version delta with the corpus present; a missing `d2_circulars` collection leaves procedure answers working.

**Portal:** `tsc -b` and `vite build` pass. Browser check against the real service code with a fake model, Arabic and English: role selector, seven suggestions, source list with page and relevance, crop images loading in the detail block, text tab, "open original image", restricted marker for the teller, mixed scanned and procedure sources in one answer.

**Compose:** base file alone and base plus override both pass `docker compose config`; in the merged result `nbe-llmgw` is on `nbe-core` and `nbe-egress`, `nbe-d2` on `nbe-core` only, and the embed and rerank services have no `depends_on`.

## 6. Documentation coverage

Checked on 8 October 2026 by listing every file changed since `e8287b6` against section 2: all 15 paths (the corpus folder counted once) have an entry, and each of the four commits carries a message stating what changed, why, and its effect on both setups.

Known gaps:

| Gap | Detail | Owner |
|---|---|---|
| Two verification tools are not in the repository | The 37-check offline script and the mock-model portal preview cited in section 5 were written in a temporary session folder. They are evidence of what was checked, but nobody else can re-run them. The checks that can be reproduced are `tests/golden_d2.py` and `tests/golden_d2_circulars.py` | D2 |
| Shared documents do not describe the new D2 | `README.md` (D2 design in section 7, service reference, data table, "synthetic data only"), `docs/talk-tracks.md` (the D2 presenter script has no scanned documents or roles), `docs/runbook.md` and `PLAN.md` are untouched because they are shared files | Team |
| Unused settings in the workstation's `.env` | `NBE_EMBED_GPU_UTIL` and `NBE_RERANK_GPU_UTIL` are set there but have no effect, since both models run on CPU in this setup | D2 |

## 7. Guardrails (added 9 October 2026)

nbe-working checked every question and answer through NVIDIA's cloud. The first pass of this migration removed
those calls without a replacement. This entry restores the function on the demo's local guardrails service.

| # | Path | Kind | What changed | Why | Impact on API setup | Impact on local deployment |
|---|---|---|---|---|---|---|
| 13 | `config/guardrails/d2/config.yml`, `prompts.yml` | New | A guardrail policy for D2: input and output self-check prompts for a staff knowledge assistant | The existing `banking` policy is written for customer service and blocks legal content and anything outside customer service. `banking` is not edited | Loaded by `nbe-guardrails`; the judging model is the hosted chat model | Loaded by `nbe-guardrails` through the existing `config/guardrails` mount; no rebuild. The judging model is the local workhorse |
| 14 | `services/d2_chatdoc/app/main.py` | Modified | Input check before retrieval; a pattern rule that masks card numbers, national IDs and Egyptian mobile numbers in the answer and in the text shown for scanned sources; output check on every generated answer (both the normal and the version-comparison branch). New response fields `blocked` and `masked`. Active only when the scanned corpus is installed | Restores nbe-working's safety function; the mask is a rule because a pattern is more dependable than a model for identifiers | Two extra hosted-model calls per answered question | Two extra workhorse calls per answered question (the README measures 120 to 600 ms each). Stays fully offline |
| 15 | `services/portal/src/workspaces/D2Chat.tsx` | Modified | Markers for an answer stopped by a guardrail and for masked identifiers | Make the guardrail visible on screen, as the trace drawer already does | None | None |
| 16 | `scripts/dev_api.sh` | Modified | `up` also builds and starts `nbe-guardrails` | D2 now needs it | Required | Not used; `make up` already starts the service |
| 17 | `data/seed/golden/d2_circulars.json`, `tests/golden_d2_circulars.py` | Modified | 7 new cases (32 in total): 4 that must be stopped (two jailbreaks, a request to bypass the role, a request to hide suspicious transfers), 1 where the source holds a phone number and a national ID that must not appear, 2 legitimate questions that must pass. New case types `blocked` and `masked` | Measure the guardrails the way retrieval is measured | Run by `scripts/dev_api.sh golden` | Run next to the existing golden test |
| 18 | `D2/ahmedsoliman/documentation/README.md`, `docs/d2-migration-plan.md`, this log | Modified | Guardrails documented: design, policy, files, GB10 notes, results, limits | Documentation directive | | |

Behaviour notes:

- Without `data/seed/d2/circulars`, D2 makes no guardrail call and is still identical to the team baseline (checked against `e8287b6`).
- The fixed replies are not sent to the output check. A restricted reply costs one input check only.
- If `nbe-guardrails` is unreachable, `/ask` returns an error instead of an unchecked answer (as D4 and D7 do).
- After editing `prompts.yml`, restart `nbe-guardrails`: it caches a policy after first use.

Results on the running stack, 9 October:

| Test | Result |
|---|---|
| Offline service check with a stand-in guardrails service | 48/48 |
| `tests/golden_d2_circulars.py`, 32 questions | 32/32 on the final code: answers 14/14, restricted 4/4, open 4/4, unanswerable 5/5, stopped 4/4, masked 1/1 |
| `tests/golden_d2.py`, 52 questions | 50/52 on the first run with guardrails, 51/52 on the final code. It was 51/52 in both runs before the guardrails |
| Portal | Stop marker on a jailbreak; "identifiers masked" marker and `[محجوب]` in the answer about circular 1 |

The procedures score moved without any guardrail acting on those answers: none of the 49 answerable questions was stopped or masked. The
question about urgent complaints is answered with or without "within 24 hours" from one run to the next (three
with, one without, in four repeats of the identical prompt), and the test requires the number. This is the
hosted model's run-to-run variation, not an effect of the change; it should not occur with the local model on
the GB10 at temperature 0.

Known limits: the mask covers text, not the crop image; it catches unbroken digit runs only; the model-based
checks are judgements measured on a small sample (4 stop cases).

## 8. Running it

Temporary API setup (workstation):

1. Start the Docker daemon in WSL (`sudo service docker start`); it does not start on boot.
2. `.env` needs the three variables of `.env.api.example`. On a shared server, also pick a free `NBE_PORT`.
3. `scripts/dev_api.sh models` once, then `scripts/dev_api.sh up`.
4. `scripts/dev_api.sh golden` runs both golden sets (about 19 minutes on CPU). The portal is at `http://localhost:<NBE_PORT>/d2`.
5. After changing `services/d2_chatdoc/app/scans.py` or the seed data: `scripts/dev_api.sh up` (rebuilds D2 and reloads its data).

Return to the local deployment (big machine): pull the branch, `make up` (no override file), `make ingest`, `make verify`, `python tests/golden_d2.py`, `python tests/golden_d2_circulars.py`, `make ui-test`, `make offline-check`. Nothing from section 2 items 6 to 9 and 11 is involved.

## 9. Document intake (added 12 October 2026)

**What changed.** A new scanned PDF can be added to D2 by upload, without an ingest and without rebuilding
either collection. nbe-working's Chandra extraction service was ported as `services/d2_extraction`
(compose profile `extract`, off by default). D2 gained `app/intake.py` (`POST /upload`, manager only), a
loader that reads the seed corpus plus uploaded documents, and `index_doc()`, which replaces one
document's passages in `d2_circulars` and touches nothing else. The parts are wired by a new override file,
`docker-compose.d2-extract.yml`, and driven by `scripts/d2_upload.sh`.

**Why.** The owner asked for the extraction step to be available in case a client wants a new document
added, as a back-office task, with the same passages and crop citations as the six existing documents.
D2 has no MinIO, which nbe-working used as the upload trigger and as the crop store: the upload endpoint
replaces the first, the existing `/crop` endpoint already replaced the second.

**Evidence.** `tests/d2_intake_equivalence.py` takes nbe-working's extraction output for all six seed
documents through the intake code and gets the seed corpus back exactly: 62 page files and 541 crops byte
for byte, 143 identical passages. An end-to-end upload on the running D2, with a stand-in that replays an
existing extraction in place of the OCR model, left the collection at 143 passages for a document already
present (identical payloads and vectors) and took it to 145 for a new one, with the procedures collection at
203 throughout. Full table: reference documentation, section 12.6.

**Not done.** The extraction image was not built and the OCR model was not run: the workstation GPU was full.
A fresh OCR run may not reproduce circulars 1 and 2 and the RTGS guide block for block, because those were
extracted by the earlier notebook at full page size. No portal screen.

**Effect on the temporary API setup.** D2 runs with the override; the uploads volume is empty. No shared file
was edited. `scripts/dev_api.sh` does not include the override.

**Effect on the GB10.** None unless the override file is used. To use it there: the model folder under
`$MODELS_DIR/chandra-ocr-2`, a build of `nbe-d2-extract`, and one real document checked before relying on it.

**Later on 12 October: the service made ready to run on the GB10 while D2 stays on the workstation.** The
owner will download the model on the GB10. A shared volume cannot span two machines, so D2 and the service
now exchange the PDF and the result (a zip) over HTTP, with an optional token. New:
`services/d2_extraction/docker-compose.yml` and `README.md` (stand-alone start on the GB10, port 8010) and
`docker-compose.d2-extract-remote.yml` (workstation: D2 joins the egress network and points at the GB10).
Re-tested with the stand-in on the egress network: same results as above, and a wrong token is refused.
Not verified: build, model load and a real extraction on the GB10. Detail: reference documentation, section 12.8.

## 10. Where the models run (changed 12 October 2026)

**What changed.** The development stack no longer uses the hosted API. The chat models are served by the
GB10 over the network, and the embedding and reranker models run on this workstation's GPU.

| Model role | Before | Now |
|---|---|---|
| workhorse, vision | OpenRouter, `google/gemma-4-26b-a4b-it` | GB10, `gemma-4-26b-a4b` at `http://100.69.85.46:8000/v1` |
| hero | same hosted model | GB10, `gpt-oss-120b` at `http://100.69.85.46:8001/v1` |
| quality | same hosted model | GB10 workhorse model (the 31B server is not running there) |
| embed (bge-m3), reranker (bge-reranker-v2-m3) | this workstation, CPU | this workstation, GPU, half precision |

| File | Status | Purpose |
|---|---|---|
| `config/litellm.gb10.yaml` | new | The aliases mapped to the two GB10 servers |
| `docker-compose.gb10.yml` | new | Makes `nbe-llmgw` load that config. Used on top of `docker-compose.api.yml` |
| `docker-compose.gpu-models.yml` | new | Builds the embedding and reranker server with the CUDA build of torch (`nbe-dev-gpu-models`, 11.9 GB) and gives both containers the GPU |
| `docker/dev-cpu-models/server.py` | changed | `DEVICE` setting: `cpu` (default, as before), `cuda`, or `auto` (GPU if the model fits, else CPU). `/health` reports the device used and why |
| `docker/dev-cpu-models/Dockerfile` | changed | A build argument for the torch wheel index; the default is still the CPU build |

No shared file was edited, `.env` was not changed, and nothing was started on the GB10: both servers were
already running there.

**Why.** The owner asked for the GB10 to serve the chat models and for retrieval to be faster. The GB10
serves the same model the final deployment uses, with no hosted service involved.

**What the GB10 endpoint supports** (called directly): JSON-schema output, tool calling, and identical text on
a repeated prompt at temperature 0. Image input was not tested. It generates 22 to 40 tokens per second, against
about 60 from the hosted API.

**Results.**

| Measure | Hosted API, CPU retrieval | GB10, GPU retrieval |
|---|---|---|
| `tests/golden_d2_circulars.py` | 32/32 | 32/32 |
| `tests/golden_d2.py` | 51/52 | 51/52 (the one miss is the customer-data-update question, answered "not found") |
| Both golden sets, duration | about 19 minutes | 3 minutes 36 seconds |
| Reranker score range on scanned answers | 0.9153 to 0.9999 | 0.9152 to 0.9999 |
| One D2 question, end to end | 17 to 27 s | 1.8 to 4.5 s |
| D7 queue of 20: topic, severity exact; policy and guardrail pass | 20, 17; 20, 20 | 20, 17; 20, 20 |
| D7 accuracy on 100: topic; severity within one | 96%; 99% | 95%; 98% |
| D7 triage of one complaint | 8 s | 8.3 s |
| D7 trends rebuild (500 embeddings) | 36 to 50 s | 5.6 s |

The collections were not re-embedded: stored vectors came from the CPU in full precision, questions are now
embedded on the GPU in half precision. The reranker score range shows the effect is in the fourth decimal.

**Commands.**

```bash
C="docker compose -f docker-compose.yml -f docker-compose.api.yml"
$C -f docker-compose.gb10.yml --profile core up -d --wait --no-deps nbe-llmgw                  # chat models from the GB10
$C -f docker-compose.gpu-models.yml --profile core up -d --wait --no-deps nbe-embed nbe-rerank # retrieval on the GPU
$C --profile core up -d --wait --no-deps nbe-llmgw nbe-embed nbe-rerank                        # back to hosted API and CPU
```

**Limits.**

- `scripts/dev_api.sh up` does not include the new override files: it puts the gateway back on the hosted API
  and retrieval back on CPU.
- The workstation GPU is shared. The two models went onto it when about 11 GB was free; an hour earlier 330 MB
  was. If the memory is not there when the containers start, they run on CPU and say so in `/health`; restart
  them when memory is free.
- The stack now depends on the GB10 being reachable at that address and on its two servers staying up.
- The GB10 address is in `docker-compose.gb10.yml` as a default; `NBE_GB10_LLM_BASE` and `NBE_GB10_HERO_BASE`
  in `.env` override it.

**Effect on the GB10 deployment.** None. These files are for the workstation; on the GB10 the stack starts
from `docker-compose.yml` alone and every alias points at a local server.
