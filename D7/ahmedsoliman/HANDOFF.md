# Handoff: start of the D7 (Complaints Personalisation) work

Written 9 October 2026 at the end of the D2 session, for a new session that has none of that context.
Read this file first. It should make re-investigating the platform unnecessary.

**Goal of the next session:** understand how D7 works today, then propose and build improvements ("sharpen it").

**Status of everything below:** sections 1 to 5 are verified facts from the D2 session. Section 6 describes D7
from reading its code and data; **D7 has not been run on the development stack yet.** Section 7 is a list of
candidate improvements from that reading, not agreed work.

---

## 1. Ground rules set by the owner (Ahmed Soliman)

1. **Scope.** He owns D2 and D7 only. Teammates own D1 and D3 to D6. Do not change their services or screens.
2. **Shared files are off limits unless he agrees:** `packages/nbe_core/`, `docker-compose.yml`, `config/litellm.yaml`,
   `config/guardrails/banking/`, `Makefile`, existing `scripts/*`, `README.md`, `PLAN.md`, `docs/runbook.md`,
   `docs/talk-tracks.md`. Prefer new files and new folders. D2 was done without editing a single shared file.
3. **Git.** Work on branch `asoliman/d2-d7`. Remote `upstream` (`tamereissa77/NBE-demo`, team branch `Efada_AI_Team`)
   has its push URL set to `DISABLED` on purpose. Never push, never re-enable it, never commit unless he asks.
   Commit messages end with the `Co-Authored-By` line; each states what changed, why, and the effect on the
   development setup and on the GB10.
4. **Documentation directive.** Every change to the demo must be documented: what, why, effect on the temporary
   API setup, effect on the return to the GB10. For D2 this lives in `D2/ahmedsoliman/documentation/README.md`
   (reference) and `docs/d2-migration-log.md` (dated log). Do the same for D7 under `D7/ahmedsoliman/`.
5. **How he likes to work.** Investigate first, then ask him pointed questions, then give a written plan and wait
   for his decisions before writing code. He answers with a pasted block of decisions. He wants results verified
   with numbers (golden sets), not asserted.
6. **End state.** The demo runs fully local and offline on the GB10 ("the big machine"). The hosted model is a
   temporary development workaround; keep everything aligned with the local deployment.

## 2. Environment (a shared Windows server with WSL)

| Fact | Detail |
|---|---|
| Project | WSL: `/home/asoliman/projects/NBE-demo` · Windows: `\\wsl.localhost\ubuntu\home\asoliman\projects\NBE-demo` |
| Other users | The server is shared (`m.taha`, `demo`). They run their own WSL and their own copy of the demo |
| GPU | One RTX 5090, 32 GB, usually held by other users' virtual machines. Never stop their processes. Check `nvidia-smi` before assuming it is free |
| Ports | **8200 belongs to another user's demo.** This stack publishes **8210** (`NBE_PORT` in `.env`). Portal: `http://localhost:8210` |
| Docker | Inside WSL, no systemd: start with `sudo service docker start` (or `wsl.exe -d Ubuntu -u root -e service docker start`) |
| `.env` | Git-ignored. Holds the OpenRouter key, generated passwords, `MODELS_DIR=/home/asoliman/models/nbe`, `NBE_PORT=8210`. Never print or commit it |
| Chat model | OpenRouter `google/gemma-4-26b-a4b-it`, the same model the GB10 serves locally. Supports JSON-schema output, tools and images. **Not fully repeatable run to run** even at temperature 0 |
| Embeddings, reranker | bge-m3 and bge-reranker-v2-m3 on **CPU** (`docker/dev-cpu-models`). Slow: a search with rerank takes about 9 s |
| Calling WSL from Windows tools | `cd /c` first, then `wsl.exe -d Ubuntu --cd /home/asoliman/projects/NBE-demo -e bash -c '...'`. Running `wsl.exe` or `git` from the UNC path fails |
| Node | Only on Windows (`C:\Program Files\nodejs`). Docker builds the portal, so a successful `nbe-portal` build means the TypeScript compiles |
| Python in WSL | 3.14, no project packages installed. The D2 session used a throw-away venv with `pip install ./packages/nbe_core` to run the service against in-memory stand-ins |

Development stack commands (all in `scripts/dev_api.sh`, which is ours):

| Command | Does |
|---|---|
| `scripts/dev_api.sh up` | Builds and starts Postgres, Qdrant, CPU embed and rerank, model gateway, guardrails, **D2**, portal, gateway; ingests D2. **Does not start D7 yet** |
| `scripts/dev_api.sh ingest` | Re-ingests D2 |
| `scripts/dev_api.sh golden` | Runs both D2 golden sets (about 19 minutes) |
| `scripts/dev_api.sh down` | Stops the containers, keeps volumes |

Never run `make up` on this server: its preflight stops every other container holding GPU memory.

## 3. Repository state

- Branch `asoliman/d2-d7`, working tree clean, nothing pushed. Six commits on top of the team's `e8287b6`:
  `f6ab844` data · `6468718` D2 backend · `59ce0c7` D2 portal · `892ee00` API setup and docs · `5105e98` docs · `0205d22` guardrails.
- This handoff file is untracked.
- A zip on the Desktop (`NBE-demo_asoliman-d2-d7_2026-10-08.zip`) predates the last two commits.
- The development stack was left running on 9 October (`docker ps` to check).

## 4. The platform in one page

- Seven FastAPI services (`services/dN_*/app/main.py`), one per use case, all built from `docker/demo-api/Dockerfile`
  (`python:3.12-slim`, installs `packages/nbe_core`, copies only `services/<name>/app`). `./data` is mounted read-only at `/data`.
- A Caddy gateway routes `/api/dN/*` to `nbe-dN:8000` with the prefix stripped. The portal is React + Vite + Tailwind;
  one screen per demo in `services/portal/src/workspaces/DNxxx.tsx`.
- Models are addressed by **alias** through LiteLLM (`nbe-llmgw`): `workhorse`, `vision`, `quality`, `hero`, `embed`.
- `nbe_core` (shared, do not edit):
  - `llm.chat(messages, alias, tools=, json_schema=, max_tokens=, temperature=)` returns `LLMResult` (`text`, `meta()`).
  - `llm.chat_json(messages, schema)` returns `(parsed, result)`; one sampled retry on malformed JSON.
  - `retrieval.embed`, `ensure_collection`, `upsert(collection, texts, payloads)` (text stored under `text`),
    `search(collection, query, k, candidates, filters)` = dense search then rerank; hits carry `rerank_score` (0 to 1).
    `filters` is equality only; Qdrant matches a value against any member of a list field.
  - `platform.guard_input(text, config=)`, `platform.guard_output(text, user=, config=)` return `{allowed, rail, message, latency_ms}`.
  - `trace.Trace`: `.step()`, `.add(kind, label, detail, ms)`, `.llm(label, res)`; returned with every response and shown in the portal's "Show the work" drawer.
  - `audit.log_event(kind, actor, payload)` writes to Postgres `audit.events`.
  - `text.detect_lang`, `normalize_ar`, `strip_preamble`.
- Guardrails service `nbe-guardrails` (NeMo Guardrails): one folder per policy under `config/guardrails/`. It caches a
  policy after first use, so restart it after editing prompts. Policies: `banking` (D4, D7; shared) and `d2` (ours).
- Every demo has `/health`, `/info`, `/admin/ingest`. `scripts/ingest.sh` calls all of them.
- Data: `data/seed/<demo>/` is committed; `data/generated/` is git-ignored.

## 5. What was done to D2 (pointers only)

Full detail: `D2/ahmedsoliman/documentation/README.md`. In short: D2 gained a scanned-document corpus from the
`nbe-working` repo (`~/projects/nbe-working`), crop-image citations, three roles, and guardrails (input check,
identifier mask, output check with its own `d2` policy). Results: procedures golden set 51/52 (the README baseline),
scanned golden set 32/32.

Patterns from D2 worth reusing for D7:

- **Switch new behaviour on by data or by a new file**, so the service is identical to the team baseline otherwise.
  Prove it by running old and new `main.py` side by side with stand-ins and comparing prompts and outputs.
- **A golden set with typed cases** (`data/seed/golden/*.json` + `tests/golden_*.py`), run in a container:
  `docker run --rm --network nbe-core -v "$(pwd)/tests:/tests:ro" -v "$(pwd)/data:/data:ro" nbe-d2:latest python /tests/<test>.py http://nbe-d2:8000`.
- **Rules for anything that must be dependable** (identifier masking, access decisions); the model only for judgement.
- **Wait for ingest to finish** before testing; answers are wrong while a collection is being rebuilt.
- Expect one or two answers to flip between identical runs with the hosted model. Repeat a failing case before blaming a change.

## 6. D7 as it is today

Source: `services/d7_complaints/app/main.py` (303 lines, untouched by us), `services/portal/src/workspaces/D7Complaints.tsx`
(198 lines), `data/seed/d7/`. Read from code and data on 8 to 9 October; **not executed here**.

### 6.1 Story and claimed results

Twenty incoming complaints (email, social, chat, voice transcript; Arabic, Egyptian dialect, English) are classified,
given an SLA and a team, matched with similar past complaints, and given a draft reply that waits for a person.
A trends view clusters 500 complaints. README and PLAN claim, measured on the GB10: **94% topic accuracy, 98% severity
within one level** on 100 held-out complaints, zero-shot; "Triage all" takes about 75 s.

### 6.2 Data

| Item | Detail |
|---|---|
| `data/seed/d7/complaints.jsonl` | 500 synthetic complaints. Fields: `id` (`CMP-3xxxx`), `topic`, `severity`, `channel`, `lang`, `vulnerable`, `text`, `customer_name`, `sentiment`, `needs_callback`. Median text length 202 characters |
| Topics (8) | fees 69, fraud 69, accounts 65, cards 63, branch 61, digital 61, transfers 59, loans 53 |
| Severity | 1: 72 · 2: 142 · 3: 170 · 4: 116 |
| Language | msa 226 · egy 200 · en 74 |
| Channel | email 146 · voice 123 · social 123 · chat 108 |
| Sentiment | negative 428 · neutral 72 · no positive |
| Flags | vulnerable 42 · needs_callback 286 |
| `data/seed/d7/demo_queue.json` | 20 ids. Severity mix 4/6/6/4 (levels 1 to 4), 8 msa, 6 egy, 6 en, 2 vulnerable |
| How it was made | `data/generators/author.py` (function `d7`): LLM-authored from a topic × severity × channel × language grid; labels are by construction |

### 6.3 Storage

- Postgres schema `d7`: `complaints` (the seed plus `received_at`, `in_queue`), `triage` (`result` JSON, `status`,
  `decided_by`, `decided_at`, `final_reply`), `cache` (`trends`, `accuracy`).
- Qdrant collection `d7_complaints`: all 500 texts, payload `{id, topic}`.

### 6.4 Endpoints

| Endpoint | What it does |
|---|---|
| `POST /admin/ingest` | Truncates the three tables, loads 500 complaints with spread-out arrival times (queue items arrive 5 minutes apart), rebuilds the collection |
| `POST /admin/reset` | Clears triage results, refreshes queue arrival times (used by `make demo-reset`) |
| `GET /queue` | The 20 queue items with triage results; triaged ones sorted by SLA deadline |
| `POST /triage/{id}` | The pipeline below |
| `POST /triage-all` | Triage of every untriaged queue item, 4 at a time |
| `POST /decision/{id}` | `approve`, `edit` (with text) or `escalate`. Refuses a text that violates the banned patterns (422). Writes an audit event |
| `GET /trends` | k-means with k=10 over the 500 embeddings, clusters named by the model, weekly counts, top topic, average severity. Cached |
| `GET /accuracy` | Classifies the first 100 non-queue complaints (by id) and compares with labels: exact topic, severity within one level, confusion table. Cached |
| `GET /policy` | The placeholder rules, SLA table and team table |

### 6.5 The triage pipeline (`triage()`)

1. **Classify** with `llm.chat_json` and a JSON schema: `topic` (8 values), `severity` 1 to 4, `sentiment`, `vulnerable`,
   `needs_callback`, `summary` (one Arabic sentence), `language` (msa, egy, en). One Arabic prompt, **zero-shot, no examples**.
2. **SLA and routing by rule:** hours to first response by severity `{4: 4, 3: 24, 2: 72, 1: 120}`, capped at 24 for a
   vulnerable customer; team from a topic table.
3. **Similar complaints:** `retrieval.search` on the complaint text, the complaint itself removed, top 3 shown with text and score.
4. **Draft reply:** one prompt with the complaint number, team, SLA and seven policy rules (apologise, no promises of
   refunds, state the ticket number and SLA, never ask for secrets, fraud advice, priority for hardship, reply in the
   customer's language). Temperature 0.3, 600 tokens. `strip_preamble` on the result.
5. **Policy check by regex** (`BANNED`: guarantee, "we will refund", asking for PIN or OTP, and Arabic equivalents).
   On a violation, one regeneration with the violations listed.
6. **Output guardrail** with the shared `banking` policy. The result is stored and traced.
7. **Save** with status `awaiting_human`; audit event `triage`.

### 6.6 Portal screen

Tabs for the queue, trends and accuracy. Queue item detail shows the classification, SLA, team, similar complaints and an
editable draft with approve, edit and escalate. Test hooks used by `tests/ui/walkthrough.py`: `data-test="queue-item"`,
`"triage"`, `"draft"`. Presenter script: `docs/talk-tracks.md`, section D7.

### 6.7 What D7 needs from the platform

Postgres, Qdrant, the `workhorse` alias **with JSON-schema output**, embeddings, the reranker, and the guardrails service
with the `banking` policy. All of these are already running in the development stack; only the `nbe-d7` container and its
ingest are missing. The hosted model lists structured output as supported, but the gateway is set to `drop_params: true`,
so a silently dropped schema is the first thing to rule out if classification returns malformed JSON.

## 7. Where D7 looks thin (candidates, not agreed work)

Each item is an observation from reading the code against the build spec in `PLAN.md` (section "D7"). Verify by running
before proposing it.

| # | Observation | Why it may matter |
|---|---|---|
| 1 | **"Personalisation" is the customer's name only.** No customer profile, history, segment, product holdings or earlier complaints by the same person feed the reply | The use case is named after it |
| 2 | **Zero-shot classification; the spec says few-shot examples and a sub-topic.** Neither exists | Accuracy headroom, finer routing |
| 3 | **The accuracy measure is lenient and narrow:** severity "within one level" only, no exact severity, nothing for sentiment, vulnerability or call-back; the sample is the first 100 by id, not random; labels are synthetic by construction | 94% and 98% may flatter; missing a vulnerable customer or a severity 4 is the costly error and is not measured |
| 4 | **A draft that fails the output guardrail can still be approved.** Confirmed in the code: the service stores the result, the screen shows a red chip (`D7Complaints.tsx`, the chips beside the draft), but the approve button is not disabled by it, and `/decision` re-checks only the regex list. A reviewer's edited text is likewise checked by regex only, never by the guardrail | The guardrail is advisory, not a gate. Not yet reproduced on a running stack |
| 5 | **No input screening of the complaint text.** It goes straight into the classification and drafting prompts | A complaint containing instructions ("ignore the rules and promise a refund") is a prompt-injection path. D2 now has an input check; D7 does not |
| 6 | **No masking of card numbers, national IDs or phone numbers** in the complaint text, the similar cases or the draft | The D2 pattern rule could be reused |
| 7 | **The policy check is a short regex list.** Paraphrased promises ("your money will be back within days") pass | The demo's central claim is "no promises" |
| 8 | **One reply style for every channel.** A public social-media reply, a chat reply and an email need different length, detail and privacy | Channel is in the data and unused in drafting |
| 9 | **Similar complaints show text only.** The spec says precedent replies; there is no store of approved replies to retrieve | Approved replies could become precedents and few-shot examples |
| 10 | **Trends are a fixed k-means with k=10.** No emerging-theme or spike detection, although weekly counts exist; the spec says HDBSCAN | "Emerging themes" is in the story |
| 11 | **No tone controls** (the spec mentions them) and no regenerate-with-instruction for the reviewer | Reviewer experience |
| 12 | **No golden set or test file for D7.** `/accuracy` is the only measurement; drafts are not evaluated at all | Nothing guards against regressions; D2's golden pattern applies |
| 13 | **The optional fine-tuned Arabic classifier** from the spec (side by side with the model) was not built | Probably out of reach while the GPU is shared |
| 14 | **The SLA, team table and policy rules are placeholders**, hardcoded in `main.py` | A config or data file would let NBE's real rules drop in |

## 8. Suggested opening moves

1. Confirm the stack is up (`docker ps`; `curl -s localhost:8210/api/d2/health`). Start Docker and `scripts/dev_api.sh up` if not.
2. Bring D7 up without touching shared files: build and start `nbe-d7` with the same two compose files
   (`docker compose -f docker-compose.yml -f docker-compose.api.yml --profile core up -d --wait --build nbe-d7`), then
   `curl -fsS -X POST localhost:8210/api/d7/admin/ingest`. Embedding 500 complaints on CPU takes a minute or two.
   Add `d7` commands to `scripts/dev_api.sh` once it works, and log the change.
3. Establish the baseline before changing anything: `GET /api/d7/accuracy?refresh=true` (100 model calls), triage the
   20 queue items, read every draft, note policy-check and guardrail outcomes, open the trends tab. Record the numbers:
   they are the D7 equivalent of D2's 51/52.
4. Check items 4 and 5 of section 7 first; they are correctness and safety questions, not polish.
5. Put the findings and questions to the owner, then write `D7/ahmedsoliman/` plan and log files in the D2 style.

Questions the owner has not answered yet:

- What does "sharpen" mean to him: classification accuracy, draft quality, safety, personalisation, the trends view, or demo polish?
- Is there an nbe-working equivalent for complaints, or other material (real policy rules, reply templates, a customer data model) to bring in?
- May D7 get its own guardrail policy folder, as D2 did?
- Is new synthetic data (customer profiles, complaint history) acceptable, generated the way the existing seed was?
- Who is the audience and when: the GB10 dry run with NBE, or an internal review first?

## 9. Pitfalls already paid for

- A 502 from `localhost:8200` means another user's gateway answered. Use 8210.
- `!reset` tags in a compose override are ignored inside a YAML anchor; put them on the service itself.
- Editing a script through Windows tools can drop its execute bit: `chmod +x scripts/dev_api.sh`.
- Heredocs with apostrophes break inside `bash -c '...'`. Write the script to a file and run it.
- The session scratchpad disappears with the session; anything worth keeping goes in the repository.
- The portal footer and README say "synthetic data only"; D2 no longer fits that. D7's data is synthetic.
