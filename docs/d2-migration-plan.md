# D2 migration plan: bringing nbe-working into "Chat with Document"

Status: agreed on 8 October 2026 and built through Phase 4 (first pass). Sections 1 to 5 are kept as agreed; where the build departed from them, section 7 lists the difference and [d2-migration-log.md](d2-migration-log.md) is the authoritative record. The reference documentation is [D2/ahmedsoliman/documentation/README.md](../D2/ahmedsoliman/documentation/README.md).
Scope: D2 only. D7 follows after D2 runs on the big machine.
Sources read: `NBE-demo` at `e8287b6` (branch `asoliman/d2-d7`), `nbe-working` at `3410e74` plus its uncommitted changes.

## 1. Target state

D2 keeps its current shape (one FastAPI service on `nbe_core`, Qdrant, role aliases, trace drawer) and gains a second corpus: the scanned circulars and the RTGS procedures from nbe-working, with their crop-image citations. Everything nbe-working needed that the demo does not have (Milvus, etcd, MinIO, Attu, NIM containers, LangChain, the separate frontend, cloud NemoGuard) is dropped.

Three rules hold the integration together:

1. **Two collections, never one.** Procedures stay in `d2_procedures` untouched. Scanned content goes to a new `d2_circulars`. The two payload shapes never mix.
2. **The feature switches itself on by data.** If `data/seed/d2/circulars/manifest.json` is absent, D2 behaves exactly as it does today. Teammates and the existing tests are unaffected until the data is present.
3. **No shared file changes.** All edits stay in `services/d2_chatdoc`, `services/portal/src/workspaces/D2Chat.tsx`, D2 seed data and new files. `packages/nbe_core`, `docker-compose.yml`, `config/litellm.yaml`, `Makefile` and `scripts/` are not edited.

## 2. What is being moved

### Corpus (all of it is inside `nbe-working`)

| Document | Pages | Blocks | Tables | Location in nbe-working |
|---|---|---|---|---|
| `legal_circular_1` | 2 | 15 | 0 | `data/legacy/pipeline_output` |
| `legal_circular_2` | 31 | 244 | 18 | `data/legacy/pipeline_output` |
| `rtgs` | 19 | 206 | 2 | `data/legacy/pipeline_output` |
| `legal_circular_3` | 8 | 58 | 0 | `pipeline_output` |
| `legal-circular_4` | 1 | 10 | 0 | `pipeline_output` |
| `legal-circular_5` | 1 | 8 | 0 | `pipeline_output` |
| **Total** | **62** | **541** | **20** | |

Each block has one pre-cut crop PNG, so there are 541 crops (about 37 MB). Full page images are another 39 MB. The nbe-working catalog records 540 chunks after filtering and splitting.

### Visual citations as they work today in nbe-working

This is the behaviour the port must reproduce (`frontend/src/CitationPanel.tsx`, `ChatScreen.tsx`):

- Inline citation markers in the answer are clickable, and a row of source chips sits under each answer.
- A side panel lists the sources: index, document label, page number, a relevance label (high / medium / low from the reranker score) and a 90-character preview.
- The selected source has two tabs: **image** (the crop PNG, with a loading skeleton and an error state) and **text** (the block text, tables rendered as HTML tables).
- An "open original" link opens the crop in a new tab.
- The full page image URL is returned by the API but the panel never displays it.

## 3. Incompatibilities and how each is resolved

### 3.1 Data model

| # | Incompatibility | Consequence if ignored | Resolution |
|---|---|---|---|
| 1 | D2 payload is `{file, procedure, version, lang, effective, title, section}`; nbe-working's is `{doc_id, page_num, block_id, block_type, bbox, crop_path, ...}` | `/ask` reads `h["title"]`, `h["version"]`, `latest[h["procedure"]]` and `h["file"].split("_")[0]` on every hit, so a circular hit raises `KeyError` | Separate collection and a separate code path for scanned hits |
| 2 | D2 derives the procedure id with `file.split("_")[0]` | `legal_circular_3` becomes `legal`; version lookup fails | Scanned hits never enter the version logic |
| 3 | Circulars have no v1/v2 pair | A "what changed?" question that lands on a circular hits `version_delta` with no documents | The compare branch runs only when the top hit is a procedure; otherwise it falls through to a normal cited answer, `delta: null` |
| 4 | Unit of retrieval: D2 indexes whole sections; nbe-working indexes OCR blocks (median 95 characters, 40% under 50) | Stub blocks compete with full sections; weak grounding | Phase 2 keeps nbe-working's block-level chunks for citation parity. Passage merging is a measured follow-up (section 6, decision 1) |
| 5 | Document ids are inconsistent (`legal_circular_3` vs `legal-circular_4`); circulars 3 to 5 are typed `SOP`; language is `ar` in some files and `ara` in others; UI labels are hardcoded for three documents only | Wrong labels, filters that miss | A `manifest.json` written by the import script carries id, Arabic and English title, corrected type, page count; the UI reads labels from it |
| 6 | Tables are stored as HTML | The portal's Markdown renderer escapes raw HTML, so a table would show as tags | At ingest, convert table HTML to a GFM table for display and to pipe-separated text for the prompt (port of `html_to_text`) |
| 7 | Bounding boxes are not in one coordinate space (`rtgs` has x up to 3692 on a page recorded as 1940 wide) | A highlight drawn on the page image would be misplaced | Use the pre-cut crops only. No overlay is drawn from `bbox` |
| 8 | SQLite catalog, in-memory job state | Not available in the demo | Replaced by the manifest; nothing else needs them for a query-only corpus |

### 3.2 Retrieval

| # | Incompatibility | Consequence if ignored | Resolution |
|---|---|---|---|
| 9 | Vectors are 2048-dim nemotron embeddings in Milvus; the demo uses 1024-dim bge-m3 in Qdrant | Existing index cannot be read | Re-embed from the extraction JSON at `/admin/ingest`. About 540 chunks, seconds of work |
| 10 | One question, two collections | Either corpus could be invisible to a question | Search both collections in parallel with the existing `retrieval.search`, merge by rerank score (same reranker and query, so scores are comparable), keep the top five |
| 11 | Circular chunks can displace procedure chunks in the top five | The 51/52 golden score could drop | The version-preference sort applies only among procedure hits; the golden set is run before and after every backend change |
| 12 | D2's "not found" cut-off (`rerank_score < 0.02`) was tuned on procedures | Wrong refusals or wrong answers on circulars | Calibrate on a new circulars golden set; keep a separate constant per corpus if they differ |
| 13 | nbe-working's relevance labels use thresholds 6 and 2, which fit the NVIDIA reranker's logits; bge-reranker scores are 0 to 1 | Every source would read "low" | Recalibrate the three bands on the circulars golden set |
| 14 | Role filter is a hardcoded dict and a Milvus expression | Not portable | If roles are kept: store a `roles` list on each chunk and use the existing equality filter, which matches list members in Qdrant. No shared-code change |
| 15 | Topic gate is two keyword lists (which block "البنك الأهلي" and "سياسة") plus a cloud call; safety is a cloud call before and after | Broken behaviour and internet dependence | Both removed. Off-topic questions are handled by the "not found" cut-off. An optional local guardrail check can be added through a new config folder |

### 3.3 Generation

| # | Incompatibility | Consequence if ignored | Resolution |
|---|---|---|---|
| 16 | Citation markers are `[1]` in nbe-working and `[S1]` in D2 | The portal's chip renderer, the `cited` detection and the golden test all key on `[S n]` | D2's markers everywhere |
| 17 | nbe-working's prompt orders Arabic always | English questions answered in Arabic | D2's language detection and its two system prompts; add nbe-working's instruction on reading tables and lists |
| 18 | nbe-working streams tokens and stage events; D2 returns one JSON with a trace | Different feel while waiting | Not part of citation parity. Phase 2 keeps D2's single response; streaming is a later option (decision 5) |
| 19 | nbe-working has no conversation history | None | D2's follow-up handling applies to both corpora |
| 20 | LangChain, LangServe and `langchain_nvidia_ai_endpoints` | Not installed in the demo image | Logic rewritten as plain Python on `nbe_core`. No new dependencies |

### 3.4 Image storage and serving

| # | Incompatibility | Consequence if ignored | Resolution |
|---|---|---|---|
| 21 | Crops live in MinIO behind nginx proxies; URLs are built from the wrong hostname and bucket (as-built defect F6) | Images do not load | Crops are files under `/data`, which the D2 container already mounts read-only. D2 serves them at `GET /crop/{doc_id}/{block_id}`, reachable as `/api/d2/crop/...` through the existing gateway route |
| 22 | MinIO buckets are world-readable (defect F5) | Access control bypassed | The endpoint resolves ids through the manifest only (no raw paths) and applies the role filter if roles are kept |

### 3.5 Frontend

| # | Incompatibility | Consequence if ignored | Resolution |
|---|---|---|---|
| 23 | nbe-working is a standalone app with CSS modules and its own theme; the portal is Tailwind with the NBE theme and a fixed three-column D2 screen | The panel cannot be copied as-is | Port `CitationPanel` into `D2Chat.tsx` as a Tailwind component with the same elements and behaviour, in the portal theme (decision 2) |
| 24 | D2's right column holds the "answer card" (sources and version delta) and a Markdown modal viewer | Two competing citation views | The right column becomes the citation panel: source list, then the image/text detail for scanned sources. Procedure sources keep the Markdown modal. The delta block stays for procedure answers |
| 25 | nbe-working's strings are Arabic only | English mode shows Arabic labels | Add both languages to the screen's label table |
| 26 | Login screen and role picker | The portal has no login | Dropped. If roles are kept, a small role selector on the D2 screen |
| 27 | The UI walkthrough clicks the first `data-test=suggested` chip and waits for `data-test=answer` | Test breaks if these move | Both attributes kept; the first suggested question stays a procedure question; circular suggestions are appended |

### 3.6 Ingestion of new documents

| # | Incompatibility | Consequence if ignored | Resolution |
|---|---|---|---|
| 28 | nbe-working's upload path (Chandra OCR, orchestrator, MinIO ingestion bucket) is commented out of its own compose file; D2 has no upload at all | None for a query-only demo | Phase 2 ships pre-extracted pages as seed data, which is how nbe-working runs today |
| 29 | The demo's upload pattern elsewhere (render pages, transcribe with the vision model) returns text without bounding boxes | New uploads would get page-level citations only | Live upload with crop citations needs Chandra as a new model server on the big machine. Deferred (decision 6) |

### 3.7 Platform and operations

| # | Incompatibility | Consequence if ignored | Resolution |
|---|---|---|---|
| 30 | `scripts/up.sh` decides whether to ingest by checking `/api/d2/documents` for the word `procedure` and the `d2_procedures` collection | First-run ingest logic breaks | `/documents` keeps its current output; circulars are listed by a new `/corpus` endpoint |
| 31 | `/admin/ingest` recreates `d2_procedures` | Circulars not loaded by `make ingest` | The same endpoint also builds `d2_circulars` when the manifest exists |
| 32 | The README states "100% synthetic, no NBE data on the box" | The statement becomes false | Needs the repo owner's agreement and a README edit (decision 3) |

## 4. Work phases

Each phase ends with a check that must pass before the next starts.

### Phase 0: temporary development environment (API chat model)

- New `docker-compose.api.yml`: gives `nbe-llmgw` one extra network with a route out, mounts a new `config/litellm.api.yaml`, passes the API key from `.env`. Demo services stay on the internal network.
- `config/litellm.api.yaml`: `workhorse` and `vision` point at the API model; `embed` still points at local `nbe-embed`.
- `nbe-embed` and `nbe-rerank` run locally with bge-m3 and bge-reranker-v2-m3 (about 4.6 GB of weights, downloaded on their own instead of `make models`).
- Start only what D2 needs: Postgres, Qdrant, gateway, portal, model gateway, embed, rerank, `nbe-d2`. `make up` is not used on the workstation because its preflight stops other GPU containers.
- **Open risks:** the Docker daemon in WSL is not running; the NVIDIA container runtime in WSL is unverified; whether `nvcr.io/nvidia/vllm:26.05-py3` runs on x86 with the 5090 is unverified (fallback: the upstream vLLM image, same API).
- **Check:** `python tests/golden_d2.py` reproduces roughly the README's 51/52 on the untouched D2. This is the baseline for every later phase.

### Phase 1: data import (no behaviour change)

- New `scripts/import_nbe_working.py`: reads both extraction folders in nbe-working, normalises ids and types, converts table HTML, copies crops, writes `data/seed/d2/circulars/{manifest.json, extractions/, crops/}`.
- **Check:** 6 documents, 62 pages, 541 blocks, 541 crops present; D2 still passes the baseline.

### Phase 2: backend

- Ingest: port of `enricher.py` (rolling section header, drop footers and blocks under three words, tables kept whole) into `/admin/ingest`, writing `d2_circulars`.
- `/ask`: parallel search of both collections, merged ranking, a scanned-source branch for context building and citations. Citation objects keep every existing field and gain `kind`, `doc_id`, `page`, `block_type`, `crop_url`, `content`.
- New endpoints: `/crop/{doc_id}/{block_id}`, `/corpus`.
- **Check:** baseline golden score unchanged; UI walkthrough passes; a hand-run circular question returns an answer with working crop URLs.

### Phase 3: frontend

- Citation panel ported into the D2 screen as described in 3.5; circular suggestions added.
- **Check:** side-by-side comparison with nbe-working's panel on the same question (list, relevance, image tab, text tab, open original); UI walkthrough passes in both languages.

### Phase 4: quality

- New `data/seed/golden/d2_circulars.json` (about 25 questions, Arabic and English, including unanswerable ones) and `tests/golden_d2_circulars.py`.
- Calibrate the "not found" cut-off and the relevance bands. Evaluate passage merging against block-level chunks.
- Optional items if agreed: roles, local guardrail check.
- **Check:** agreed pass rate on the circulars set; procedures set still at baseline.

### Phase 5: big machine

- Pull the branch, copy the circulars data if it is not in git, run `make up` without the API override, `make ingest`, `make verify`, both golden sets, `make ui-test`, `make offline-check`.
- Re-check the two calibrated thresholds, since Gemma answers instead of the API model.
- **Check:** all of the above green with no internet.

## 5. What stays the same for the rest of the team

- No edits to shared code or config. Two new files at the repo root level (`docker-compose.api.yml`, `config/litellm.api.yaml`) are opt-in.
- D2's existing endpoints, response fields, golden set and UI test hooks are unchanged.
- Without the circulars data folder, D2 is byte-for-byte today's behaviour.

## 6. Decisions (taken 8 October 2026)

1. **Chunking: merged passages**, each keeping the list of blocks it was built from so the citation shows their crops. This replaces the block-level approach in row 4 of section 3.1 and in Phase 2.
2. **Citation panel: portal theme**, with nbe-working's elements and behaviour.
3. **Data handling: approved** to send the circulars and RTGS text to an external API during the temporary phase, and to commit the crops as seed data under `data/`.
4. **Roles: kept** (teller / legal counsel / manager), enforced by payload filtering in D2.
5. **Streaming: off.** D2 keeps its single response.
6. **Live upload: out of scope.** Chandra OCR is deferred.
7. **API model:** provider and model are set through `NBE_API_MODEL` and `NBE_API_KEY` in `.env`.

Implementation record: [d2-migration-log.md](d2-migration-log.md).

## 7. Where the build departed from this plan

| Plan said | What was built | Why |
|---|---|---|
| Block-level chunks first (section 3.1 row 4, Phase 2) | Merged passages from the start, each keeping its block list | Decision 1 |
| Import script at `scripts/import_nbe_working.py` (Phase 1) | `services/d2_chatdoc/tools/import_nbe_working.py` | Keeps it inside the D2 use case; confirmed by the owner |
| Embeddings and reranker on the workstation's GPU through vLLM (Phase 0) | Both on CPU through `docker/dev-cpu-models`, same weights and endpoints | The GPU is shared and was full |
| Two new opt-in files (section 5) | Also `.env.api.example`, `scripts/dev_api.sh`, `docker/dev-cpu-models/`, `services/d2_chatdoc/app/scans.py`, the import tool, the scanned golden set and its test | Needed by the items above and by Phase 4 |
| Scanned golden set in Phase 4, after the portal | Written and run in the same pass (`tests/golden_d2_circulars.py`, 25 questions) | Needed to answer the calibration question |
| The restricted reply was not specified | Chosen by rule from reranker scores, never written by the model | No forbidden text has to reach the model |
| Portal on port 8200 | Port 8210 on the workstation (`NBE_PORT` in `.env`) | 8200 is published by another user's copy of the demo on the same server |
| Safety and topic checks removed, with a local guardrail check as an option (section 3.2 row 15) | Added on 9 October: input check, identifier mask and output check on the local guardrails service, with a D2 policy | Parity with nbe-working, which screened every question and answer |
