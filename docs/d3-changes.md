# D3 Campaigns & Offers: changes and test results

This summarises the work on D3 (Campaigns & Offers hyper-personalisation), done 10–11 October 2026. It covers:
- interest-profile accuracy;
- hardening the compliance check, the demo's live safety moment;
- the A/B plan and input guards;
- portal display fixes.

The public endpoints are unchanged. Response fields were only added, never removed or renamed. One new endpoint was added: `GET /eval/profile`.

## Files touched

| File | What changed |
|---|---|
| `services/d3_campaigns/app/main.py` | All D3 logic changes below |
| `packages/nbe_core/nbe_core/text.py` | **New** `normalize_map()` for rule matching. `normalize_ar()` is unchanged (D1 and D5 use it) |
| `services/portal/src/workspaces/D3Campaigns.tsx` | Labels, the "assumed" baseline, the "fixed in code" block, plain-language compliance output, mixed Arabic/English line fix |
| `services/portal/vite.config.ts` | `D3_URL` points `/api/d3` straight at a local D3 in dev (same as `D5_URL`) |
| `tests/test_d3_unit.py` | **New.** 63 offline unit tests (no model, no database) |

## 1. Interest profile: rank by how often people buy, not by spend

**Problem.** The profile ranked categories by share of **spend** × lift. Typical purchase sizes differ by up to 60× (café 120 EGP, travel 7,800 EGP), so occasional expensive categories beat the everyday ones. As a result, campaigns went to the wrong category for most personas:

| Persona | True top interest | Old profile picked |
|---|---|---|
| young_professional | café | travel |
| family | grocery | education |
| student | café | education |
| sme_owner | fuel | electronics |

**Change.**
- `interest_profile()` now ranks by share of **purchases**. Lift only breaks ties: multiplying by it favoured categories that only one segment buys, such as hotels over travel for affluent customers.
- It also returns `penetration`: the % of the segment's customers who bought in that category at least once.
- `metric="spend"` keeps the old behaviour for comparison.

**New `GET /eval/profile?metric=frequency|spend`.** This scores the profile against the true preferences: the persona category weights, read straight from `data/generators/d3_commerce.py`. It reports:
- top-1 accuracy and top-3 recall, per persona and per persona × city;
- segments under 30 customers, separately;
- every segment where the top category was wrong.

**Result** (full generated data: 5,000 customers, 50,000 purchases):

| | Old (spend) | New (purchases) |
|---|---|---|
| Whole personas: top category correct | 20% | **100%** |
| Whole personas: true top-3 found | 40% | **93%** |
| Persona × city, 30+ customers (37 segments): top category correct | 13.5% | **94.6%** |
| Persona × city, 30+ customers: true top-3 found | 38% | **95.5%** |
| Persona × city, under 30 customers (8 segments): top category correct | 50% | 50% |

The remaining misses are near-ties in small segments, such as students in Hurghada or Luxor, where telecom narrowly beats café. They come from small samples, not a ranking error. The `share_mae_pp` column in the evaluation output is the same under both metrics, because it always compares purchase counts, so ignore it when comparing them.

Because campaigns now target everyday categories like café and grocery, cashback caps are smaller. That's intended.

## 2. Compliance check (the live safety moment)

### 2.1 Banned claims can no longer be dodged by spelling

The old rules searched the raw text for exact patterns, so «١٠٠٪» (Arabic digits and percent sign), «مضـــمون» (kashida), «مَضْمُون» (diacritics) and zero-width characters all got through.

- **`nbe_core.text.normalize_map()`** folds the text before matching:
  - diacritics, kashida and zero-width characters are removed;
  - أ/إ/آ become ا, ة becomes ه, ى becomes ي;
  - Arabic and Persian digits become 0–9, and ٪ becomes %;
  - text is lower-cased.
  
  It also returns, for every folded character, its position in the original, so a match can be found and removed in the original text.
- **The rules now handle Arabic word forms:** attached و/ف/ب/ل/ك/ال prefixes and ة/ه/ين/ات/ان endings. They also cover verb forms (نضمن, Egyptian «بنضمنلك») and spelled-out forms («مية في المية», «بالمئة»).
- **Caught:** guaranteed, the guarantee verb, 100%, competitor comparison, "best bank", "totally free", "no conditions", "risk-free" (Arabic and English).
- **Not flagged:** «مضمار», «ضمان المنتج», «يتضمن/تتضمن», «100 جنيه», «أفضل العروض».
- **Deliberate choice:** «المضمون» **is** flagged. In bank copy it reads as "the guaranteed", and a false alarm only costs one extra fix pass.

### 2.2 Disclaimer check is tolerant of spacing and spelling

It now accepts «الشروط و الأحكام», «تُطبَّق», «تنطبق», line breaks, "T & C apply" and "Terms and conditions apply". Before, any spacing difference failed it.

### 2.3 Offer details must be in every message (new rule `offer_terms`)

The first live run showed SMS made up only of «تطبق الشروط والأحكام» **passing**. Every SMS, email body and social post must now state:
- the correct cashback % and cap (any digits; "2,500" counts as 2500);
- the merchant name, in Arabic copy.

A wrong rate, for example 20% instead of 15%, is caught.

### 2.4 SMS length counted in real SMS parts

The old rule was `len(text) > 160`. That's only right for GSM-7 text: Arabic SMS are UCS-2, so 70 characters per part, or 67 per part when split. `sms_parts()` now counts the way a gateway does.

**Decision:** Arabic SMS may use **2 parts (up to 134 characters)**, because 70 characters can't hold the rate, cap, merchant, end date and disclaimer. English stays at 1 part (160). The prompt asks for at most 130 characters for Arabic SMS. The limit is the `SMS_MAX_PARTS` constant.

### 2.5 Fix loop, then a code-enforced fallback

- The model gets up to **2 fix passes** (`MAX_FIX_PASSES`, previously 1).
- If issues remain, **`enforce()`** fixes them in code instead of shipping them:
  - **banned claim:** removes the whole clause that contains it (only the claim itself if that clause holds the disclaimer);
  - **missing disclaimer:** adds it;
  - **SMS too long:** shortens it at a word boundary, keeping the disclaimer;
  - **offer details missing or wrong:** replaces the message with a plain one built from the offer itself.
- Everything done this way is returned in `compliance.enforced_in_code` and shown in the portal.

### 2.6 Stress test no longer depends on the model

The model was asked to plant «عائد مضمون 100%», but the test model ignored it, so nothing was there to catch. If the model's copy has no banned claim, the phrase is now inserted in code, so the stress test always fires.

## 3. A/B plan

- **The baseline is now an explicit assumption.** The synthetic data has no redemption history, so 8% is a guess. The request takes `baseline_rate` (default 0.08), and the response adds `baseline_source: "assumption"`, `baseline_note`, and `min_detectable_lift_if_baseline` (the result at half and double the baseline). The portal labels the baseline "assumed".
- **Identical variants warning.** If SMS A and B end up the same, for example both replaced in code, the A/B note says there's nothing to test.

## 4. Guards

- A segment with no spending in any category that has an offer rule now returns a clear **409** instead of crashing (`IndexError` or `KeyError`).
- The merchant match and the brief-based search only consider categories that have an offer rule.
- The banner falls back to a generic scene for unknown categories.

## 5. Portal

- The interest profile is labelled "share of purchases", not "share of spend", in English and Arabic.
- The baseline shows an "assumed" label and the assumption note.
- A new **"Fixed in code"** block (orange) lists what the code changed. "Caught before output" stays red.
- Compliance lines are in plain language in both UI languages. For example, `sms_a_ar: replaced_with_offer_terms missing 5%…` now reads **SMS A (Arabic): Replaced with the standard offer text (5%, cap 200, …)**.
- The segment line keeps the Arabic persona name separate from the English text, so it reads in the right order.

## Test results

### Unit tests: `pytest tests/test_d3_unit.py` → 63 passed

These cover the normaliser, 33 banned-claim variants, 9 clean texts that must not be flagged, disclaimer variants, SMS part counting, the offer-terms rule, every enforcement path, and that the code-built offer text passes all rules. D3 and D5 tests can be run together: 87 passed in either order. D3 is loaded under its own module name because every service package is called `app`.

### Live campaigns (real `/campaign` code)

These ran on a laptop against a temporary Postgres and a **local `llama3.2:1b`** in Ollama, because the GB10 wasn't available. It's a very weak model for Arabic, so this is a worst-case test of the safety net, not of copy quality.

| Campaign | Problems found at first | Fixed by the model (2 passes) | Fixed in code | Final |
|---|---|---|---|---|
| young_professional, stress test | 11, including «مضمون» and «100%» | 0 | 6 | passed, 0 issues |
| family, stress test | 15, including «المضمون 100%» in the banner headline | 0 | 7 | passed, 0 issues |
| student, normal | 6, all missing offer details | 0 | 6 | passed, 0 issues |

- The planted claim was caught every time and never reached the output.
- Every final message states the correct rate, cap and end date.
- Arabic SMS were 105–115 characters (2 parts); English SMS were 99–100 characters (1 part).
- With this model every message ended up as the plain code-built text, so SMS A and B were identical (the new warning covers this).
- Runs took 2.5–6 minutes on CPU.

## Handover

### Where things stand (11 October 2026)

| Area | State |
|---|---|
| Code | Done. All changes above are in the working tree. The project is not a git repository, so nothing is committed |
| Unit tests | 63/63 D3, 87/87 together with D5 |
| Profile accuracy | Measured on the full data: 100% personas, 94.6% city segments |
| Compliance safety net | Live-tested: no banned claim reached the output in any run |
| Real model (GB10) | **Not tested.** All live runs used `llama3.2:1b` on a laptop |
| Marketing brief, banner | **Not tested.** They need Qdrant + embed and SDXL, which weren't available locally |
| GB10 deployment | **Not done.** The changed files are not on the demo machine yet |

**Verdict:** the code is ready, but the demo isn't proven. It's ready to demo once the checklist below passes on the GB10.

### 1. Deploy to the GB10

Copy these files to the same paths in the GB10 checkout:

```
services/d3_campaigns/app/main.py
packages/nbe_core/nbe_core/text.py
services/portal/src/workspaces/D3Campaigns.tsx
services/portal/vite.config.ts
tests/test_d3_unit.py
docs/d3-changes.md
```

Then rebuild and restart D3 and the portal. Each demo image copies in its own `nbe_core`, so no separate base image needs rebuilding. The other demos only gain an unused function and can be rebuilt later.

```sh
docker compose build nbe-d3 nbe-portal
docker compose up -d nbe-d3 nbe-portal
make data        # only if data/generated/d3 is missing (the seed is fixed, so it regenerates identically)
make ingest      # or: curl -X POST http://localhost:8200/api/d3/admin/ingest
make d3          # health check
```

### 2. Go/no-go checklist (about 20 minutes)

| # | Check | Pass when |
|---|---|---|
| 1 | `pytest tests/test_d3_unit.py` | 63 passed |
| 2 | `curl http://localhost:8200/api/d3/eval/profile` | `personas.top1_accuracy` = 1.0 and `persona_city.top1_accuracy` ≈ 0.946 |
| 3 | Normal campaign (Families, all cities) | Arabic copy reads naturally; the rate, cap, merchant and date are right; "Fixed in code" is empty or has 1–2 lines; SMS A and B differ |
| 4 | Stress-test campaign | The planted claim appears under "Caught before output" and **not** in any final text; compliance chip is green |
| 5 | Campaign with a marketing brief (e.g. «عروض المطاعم») | No error; the brief's merchant is first in the match list |
| 6 | Banner | An image appears (cached or live SDXL) |
| 7 | Timing | Note the seconds on the result chip, to plan the talk track while it runs |

**If check 3 fails** (the real model also produces mostly "Fixed in code"):
- It's still safe to show. The output is correct, just plain.
- To improve it: look at the first issues in the trace drawer. If they're mostly `offer_terms`, the model is paraphrasing the rate or cap, and the copy prompt should give it the exact phrases to use.
- Don't loosen the rules for the demo.

**If check 4 fails:** don't demo the stress test. Send the trace output for review: unit test `test_stress_test_phrase_always_ends_clean` covers this path, so a failure means the deployed code is out of date.

### 3. Decisions for the owner

1. **Arabic SMS limit.** Currently 2 SMS parts (134 characters). If the SMS gateway contract requires a single part, set `SMS_MAX_PARTS["ar"] = 1` in `main.py`. The copy will then be very tight.
2. **«المضمون» is always flagged.** Chosen to be safe. Remove that case from the `guaranteed` rule only if marketing needs the word in the sense of "content".
3. **A/B baseline.** 8% is an assumption and is labelled so in the UI. Replace it with the bank's historical redemption rate when available. It's the request field `baseline_rate`; the UI doesn't set it yet.

### 4. Known issues (not blockers)

- **Small segments** (under 30 customers, e.g. affluent in Ismailia): the profile is unreliable (50% top-1), and the A/B plan says the audience is too small. Prefer whole personas or large cities in the demo.
- **`share_mae_pp`** in `/eval/profile` is the same under both metrics, because it always uses purchase counts. Use top-1 and top-3 instead.
- **Windows only:** `/health` shows Postgres as "error" because of an async psycopg limitation. This doesn't happen in the containers.
- **Every service package is called `app`.** Load service code under its own module name in new test files (as `test_d3_unit.py` does), or tests that are run together will clash.

### 5. Suggested talk track for the safety moment

1. Turn on **Stress test**. Say: "we'll ask the model to slip in a forbidden promise: a guaranteed 100% return."
2. Build the campaign, then point at **"Caught before output"**: the banned claim was caught, including Arabic digits and spelling variants.
3. Point at the final SMS: the claim is gone, and the offer and disclaimer are intact.
4. If **"Fixed in code"** has lines, say: "if the model can't fix it, the code does. A banned claim can never ship."

## Running D3 locally (no GB10)

The portal dev server can talk to a D3 run directly with uvicorn:

```sh
D3_URL=http://127.0.0.1:8003 npx vite --port 5183   # in services/portal
```

Notes:
- The `/health` endpoint reports Postgres as "error" on Windows. That's an async psycopg limitation on Windows and doesn't happen in the Linux containers.
- The marketing brief needs Qdrant and the embedding service, so leave it empty when running locally.
- There's no banner image unless SDXL is running.
