# D5 Legal Documents: changes and test results

Summary of the work on D5 (Legal Documents Summarisation) done in October 2026: running it off the GB10,
English support, three rounds of accuracy work, and hardening for Gemma 4 served through OpenRouter.

Public endpoints are unchanged. Output fields were only added, never removed or renamed.

## Files touched

| File | What changed |
|---|---|
| `services/d5_legal/app/main.py` | All D5 logic changes below |
| `scripts/openrouter_relay.py` | **New.** Local stand-in for the LiteLLM gateway (Gemma 4 through OpenRouter) |
| `scripts/d5_stability.sh` | **New.** GB10 stability run: golden check N times per reduce alias |
| `tests/test_d5_unit.py` | **New.** 25 offline unit tests (fake model, no network) |
| `tests/golden_d5.py` | **New.** Live golden check against a running D5 |
| `data/seed/d5/E01.md` | **New.** English translation of C01, with C01's planted deviation |
| `data/seed/d5_en/C01_en.md`, `R01_en.md` | **New.** English copies of C01 and R01 for manual upload tests |
| `data/seed/d5/manifest.json`, `data/seed/golden/d5.json` | E01 added (`"lang": "en"`) |
| `data/generators/d5_clauses.py` | Re-adds E01 whenever the generator rewrites the manifest |
| `docker-compose.yml` | `D5_REDUCE_ALIAS` is now passed into the `nbe-d5` container (it was ignored before) |
| `services/portal/vite.config.ts` | `D5_URL` sends `/api/d5` straight to a local D5 in dev |

`nbe_core` (including the `llm.chat_json` retry path) is **not** modified.

## 1. Running D5 without the GB10

- **`scripts/openrouter_relay.py`** answers `/v1/chat/completions` like the gateway.
  - `workhorse`/`vision` go to `google/gemma-4-26b-a4b-it` and `quality` goes to `google/gemma-4-31b-it`, the
    same models the GB10 serves. Key: `OPENROUTER_API_KEY`. Only hosts that honour `json_schema` and
    `temperature` are used.
  - It retries 429/502/503 and dropped connections. Each request gets 60 s per try and 180 s in total
    (`UPSTREAM_TIMEOUT`, `REQUEST_BUDGET`); past that it returns 504. Concurrency is `RELAY_CONCURRENCY`
    (default 12). `RELAY_TIMING=1` logs each request's model, status and duration.
- `D5_SEED_DIR` overrides the seed folder (default `/data/seed/d5`). `/golden` reads `golden/d5.json` from
  beside it instead of a fixed Docker path.
- **Local run:** start the relay, then D5 with `LLM_GATEWAY_URL=http://127.0.0.1:4000/v1`, `LITELLM_MASTER_KEY=local`
  (any non-empty value), `D5_SEED_DIR` and `PYTHONPATH=packages/nbe_core`. Then start the portal with
  `D5_URL=http://127.0.0.1:8005 npx vite` and open `http://localhost:5173/d5`.

## 2. English documents

- `is_english()`: a document with more Latin than Arabic letters gets English output. Arabic stays the default.
- `Article N` headings are split and matched like `المادة N`, and they mark an upload as a contract.
- `.md` and `.txt` uploads are read directly, without Docling.
- An English contract's article comparison runs with an English prompt and an English copy of the severity rubric.

## 3. Accuracy

**Quotes**
- Each quote and the document (normalised once) go through whitespace collapsing, punctuation stripping and
  `nbe_core.text.normalize_ar` before matching.
- Unverified clauses are kept with `quote_verified: false`, and the UI marks them.

**Summary (map and reduce)**
- Each section gets 2–3 sentences (`max_tokens` 300), with every number, amount, percentage and period copied
  verbatim.
- Each key point starts with its source tag (`[م.N]`, `[Art.N]`, or the section name for rulings). The new
  `article_refs` field is built from those tags in code.
- `D5_REDUCE_ALIAS=quality` puts the reduce step on the 31B.

**Rulings**
- The headline amount is the one awarded in the operative part (المنطوق), not the one claimed. The operative
  part is passed verbatim, and code moves amounts found there to the front of the list.
- Amounts are de-duplicated, entries without a number are dropped, and the currency is taken from the source
  (`47,300` becomes `47,300 جنيه مصري`; English keeps `EGP 2,500,000`).
- New fields: `court`, `outcome` and `award_split` (null for contracts).
  - `court` is read in code from the `المحكمة: …` header line.
  - An empty `outcome` falls back to `outcome_or_obligations`, then to the operative part's first ruling.
  - Each `award_split` row has `party` (who **bears** the amount), `role` (`pays` / `bears_loss`) and
    `beneficiary`. This fixed R02, where the plaintiff had been named for both halves. Rows whose amount is
    not in the operative part are dropped, and payers come first.
- **Amount self-check:** any summary amount not found in the source text is added to `risk_flags`.
- If the summary has no amounts, the operative part's amounts are used.

**Template comparison**
- Articles are still matched by number only, so C05's deleted article 9 shows as `missing` / `high`.
- A fixed severity rubric is in the prompt, matching `manifest.json`:
  - **high:** a borrower right or notice step is removed or restricted, or the law, jurisdiction or
    arbitration changes, or the article is deleted
  - **medium:** a fee or penalty amount alone changes, or any change to insurance, liability or data
  - **low:** wording only
- Insurance, liability and data (articles 7, 10, 11) are **capped at medium in code** unless the article is
  deleted.
- This differs from the rubric in the original brief, which conflicted with the manifest on C04
  liability/rate and C05 data.

**Compound risks (deterministic)**
- The model is no longer asked for compound risks. `compound_risks()` fires when two or more *deviating*
  articles share a theme in the fixed `THEMES` map:
  - cost of credit: articles 3, 5, 6
  - default and termination: articles 6, 8, 9
  - recourse: articles 10, 12
- The output keeps the same shape: `summary.compound_risks` and `risk_flags` entries with `compound: true`.
- No seed contract fires one: C01's example (shorter cure period plus removed notice) is inside a single
  article. The theme map should be reviewed by legal.

**Other**
- `analyzed_at` (UTC, ISO 8601) is added to every result. `/analyze/refresh` still forces a fresh run.

## 4. Hardening for Gemma 4 on OpenRouter

Problems found in testing, and how D5 now handles them:

| Problem | Fix |
|---|---|
| Gemma writes valid JSON, then pads with whitespace up to `max_tokens`. Each call took ~100 s, and the retries made it 4 calls per article (E01 took about 15 min) | `chat_json_d5` calls `llm.chat` once at temperature 0 and **repairs a truncated reply before any retry**. The comparison cap is 350 tokens for English, 1000 for Arabic (Arabic verdicts are longer and don't pad) |
| Unusable reply on one article | `repair_json` closes the JSON and fills missing fields, recording them in `_filled`. A repaired verdict is used only if the model itself wrote `deviates` (and `severity` when it deviates). Otherwise the article is retried once on `D5_FALLBACK_ALIAS` (default `quality`, the 31B), then marked `status: "unchecked"`. It is never guessed |
| Unusable summary or clause reply | Repaired, or else a basic summary is built from the section summaries (court and amounts from the source). Incomplete clauses are dropped |
| Timeout or 5xx on any call | Map: one retry, then the section's own opening text stands in. Structured steps: as above. One bad call never fails the whole document |

Unchecked articles never count as deviations, risk flags or compound risks. The UI shows them with a neutral
"unchecked" chip.

## 5. Tests

- **Offline:** `pytest tests/test_d5_unit.py` passes 25/25. It covers C05 article 9, quote normalisation,
  amount ordering and units, the court and outcome fallbacks, award split checks, compound-risk determinism,
  the English path, JSON repair, the fallback model, timeouts and the severity cap.
- **Live:** `python tests/golden_d5.py <base_url> <seed_dir> [--json out.json]`. It fails on any of these:
  - a missed or false deviation
  - a severity that differs from the manifest
  - an unchecked article
  - an untagged key point
  - an English contract summarised in Arabic
  - a wrong headline amount, or one missing its currency
  - a missing or wrong court
  - a wrong award split (R02: bank bears 72,000, plaintiff bears 48,000)
  - a compound risk on a seed contract
- **GB10:** `make quality-on && scripts/d5_stability.sh` (`RUNS=3` by default).

## 6. Results

| Setup | Result |
|---|---|
| Gemma 4 on OpenRouter, final run (3 runs, summary on the 31B, comparison on the 26B with 31B fallback) | **3/3 runs pass every check** (9/9 deviations, 9/9 severity, rulings, split, currency). 11–18 min per run |

## 7. Open items

- **Run `scripts/d5_stability.sh` on the GB10.** Everything was tested through OpenRouter. The GB10 serves the
  same models with vLLM, which may enforce JSON more strictly.
- **`manifest.json` lists R02's amount as 120,000.** That's the disputed total; the award is 72,000 / 48,000.
  The golden test checks the award; the manifest itself was not changed.
- **Legal review of the `THEMES` map** for compound risks.
- **The relay is for local testing only.** It is not part of the Docker stack.

## 8. Handover

### Current state

- **D5 code is complete and tested:** 25/25 unit tests, and 3/3 clean live runs on Gemma 4 through OpenRouter.
- **Not yet tested on the GB10.** Run the stability script there before relying on it (see Open items).
- **Nothing is under version control.** `C:\Code\NBA ai` is not a git repository; commit or back up before
  further changes.
- **Only D5 works off the GB10.** The other portal demos (D1–D4, D6, D7) need the full Docker stack.

### Prerequisites (Windows laptop)

- Python 3.12 with `fastapi`, `uvicorn`, `httpx`, `pydantic`, `python-multipart` and `psycopg[binary,pool]`.
  Node.js for the portal (`npm install` in `services/portal` once).
- `OPENROUTER_API_KEY` set as a user environment variable (`setx OPENROUTER_API_KEY "..."`). Fully restart
  VS Code or the terminal afterwards so it is picked up.
- **OpenRouter credit:** one golden run (9 documents) costs about $0.02–0.03 with the current code, so one
  document costs well under $0.01. Keep a few dollars on the key; check it at openrouter.ai under Keys.

### Starting it locally (PowerShell, three terminals, from `NBE-demo`)

```powershell
# 1. Relay (port 4000)
python scripts/openrouter_relay.py

# 2. D5 (port 8005)
cd services/d5_legal
$env:LLM_GATEWAY_URL='http://127.0.0.1:4000/v1'; $env:LITELLM_MASTER_KEY='local'
$env:D5_REDUCE_ALIAS='quality'                       # summary on the 31B (tested setup)
$env:D5_SEED_DIR="$PWD/../../data/seed/d5"; $env:PYTHONPATH="$PWD/../../packages/nbe_core"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8005

# 3. Portal (port 5173)
cd services/portal
$env:D5_URL='http://127.0.0.1:8005'; npx vite --port 5173
```

Open `http://localhost:5173/d5`. Use `localhost`, not `127.0.0.1`.

### Before a live demo

1. **Check the credit** (a few dollars is plenty).
2. **Warm the cache.** Each analysis takes 1–3 minutes live. D5 keeps results in memory, so analyse every
   document once beforehand and clicks during the demo are then instant:
   ```powershell
   foreach ($f in 'template.md','C01.md','C02.md','C03.md','C04.md','C05.md','E01.md','R01.md','R02.md','R03.md') {
     Invoke-RestMethod -Method Post http://127.0.0.1:8005/analyze -ContentType 'application/json' `
       -Body (@{file=$f} | ConvertTo-Json) -TimeoutSec 900 | Out-Null; "$f done" }
   ```
   The cache is lost if D5 restarts, so warm it after the last restart.
3. **During the demo:**
   - Stay on the D5 page.
   - "Refresh" and file uploads run live, so they take 1–3 minutes.
   - A "degraded" health status is expected, because Postgres and Qdrant are not running. Analysis does not
     use them.
4. **Good talking points:**
   - R02's award split: the bank pays 72,000 and the plaintiff bears 48,000.
   - C05's deleted article 9 shows as "missing".
   - E01 shows an English contract checked against the Arabic template.
   - Verified quotes are marked ✓.

### On the GB10 (Docker stack)

- The relay is not used there. D5 talks to the LiteLLM gateway as before.
- To put the summary on the 31B: `make quality-on`, then set `D5_REDUCE_ALIAS=quality` (now passed through by
  `docker-compose.yml`). The article-comparison fallback uses `D5_FALLBACK_ALIAS` (default `quality`). Without
  the quality profile, the gateway serves it from the workhorse.
- Validate with `make quality-on && scripts/d5_stability.sh` and check that every run reports 9/9 caught,
  9/9 severity and no failures.

### Checking it still works after a change

```powershell
python -m pytest tests/test_d5_unit.py -q                                   # offline, ~2 s
python tests/golden_d5.py http://127.0.0.1:8005 data/seed/d5                  # live, ~10-15 min, ~$0.03
```

### Where to look when something goes wrong

| Symptom | Likely cause | Where to look |
|---|---|---|
| Article shows "unchecked" | Both models returned an unusable reply for it | D5 trace (the "Show the work" drawer) and the relay output |
| Requests fail with 403 | OpenRouter key out of credit or over its limit | openrouter.ai, under Keys |
| Analysis very slow | OpenRouter host slow or padding replies | Start the relay with `RELAY_TIMING=1` to log each call's duration |
| Portal shows nothing for D5 | `D5_URL` not set, or D5 not running | `http://127.0.0.1:8005/health` |
| A severity looks wrong | Rubric or the medium cap | `SEVERITY_RUBRIC`, `SEVERITY_RUBRIC_EN` and `MEDIUM_ARTICLES` in `main.py` |
