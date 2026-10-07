# NBE AI Demos on GB10

Seven live AI demos for National Bank of Egypt (D1–D7), one per NBE use case. They run fully offline and fully containerised on one Dell Pro Max with GB10.

See [PLAN.md](PLAN.md) for the architecture, per-demo specs, model and memory budget, and execution phases.

## Status

All seven demos are live and pass the end-to-end UI walkthrough. Measured results are in PLAN.md §13. **Open item:** blind human scoring for the Arabic gate at `/eval`, then `make models-lock`.

| Demo | What it shows |
|---|---|
| D1 Doc verification | vision extraction, image forensics, cross-document checks, evidence-backed "flagged for review", human decision |
| D2 Chat with Document | cited answers from the current procedure version, "what changed" panel, "not found" instead of guessing |
| D3 Campaigns & Offers | spend-based interest profile, merchant match, AR/EN/dialect copy, compliance check with auto-fix, SDXL banner, A/B plan |
| D4 AI Virtual Agent | voice or chat, mock OTP, card block, ticket, human handoff, live guardrail STOP marker |
| D5 Legal summarisation | map-reduce summary, verified clause quotes, risk flags, comparison against the approved template |
| D6 NBE AI Assistant | task router with Model-Selection Panel, file chat, OpenAI-compatible `/v1` for Dataiku |
| D7 Complaints | classification, SLA routing, policy-checked drafts awaiting approval, trends, accuracy |

## Quick start

```bash
make up        # creates .env on first run, frees the GPU, starts models one by one, then the apps (~4 min cold)
make verify    # portal + demo APIs + offline proof + full platform check
make ui-test   # click through all seven demos in a real browser (Playwright)
make demo-reset   # between audiences
make gpu       # memory per container
make hero      # D6 hero moment: swap gpt-oss-120b in (~70 s);  make hero-off to swap back
```

Model weights live in `/opt/models` and are fetched once with `make models` (the only step that needs the internet).

Portal: <http://localhost:8200> (Arabic: <http://localhost:8200/?lang=ar>). Each demo is at `/d1` … `/d7`, and its API is at `/api/d1` … `/api/d7` (`/docs` for OpenAPI).

Run `make` with no target to list every command. Operators: [docs/runbook.md](docs/runbook.md). Presenters: [docs/talk-tracks.md](docs/talk-tracks.md). Arabic gate scoring: [docs/arabic_gate.md](docs/arabic_gate.md).

## Layout

```
brand/               NBE logo, mark and colour tokens (theme.css), served by the portal
config/              Caddy gateway, Postgres init, LiteLLM model aliases, guardrails rails
docker/              Dockerfiles (portal, shared demo-api image)
packages/nbe_core/   shared Python library: app factory, LLM/retrieval/platform clients, audit log
services/d1_…d7_…/   one FastAPI service per demo
services/portal/     React + Vite + Tailwind portal
services/mockbank/   mock OTP, cards, balance, tickets, handoff (synthetic customers)
services/{asr,tts,sdxl,guardrails,docling}/   platform services
services/d1_…d7_…/   one FastAPI service per demo; services/eval: Arabic gate
data/generators/     synthetic data (nbe-datagen container); data/seed: committed corpora and golden sets
tests/               platform_check.py (make verify), golden_d2.py, ui/walkthrough.py (make ui-test, make record)
scripts/             preflight, gpu, verify, download_models
```

## Notes

- Only the gateway publishes a port. Every other service sits on `nbe-core`, an `internal` Docker network with no route to the internet.
- The GB10 is shared. `make preflight` (run by `make up`) stops every non-NBE GPU consumer in one go, because vLLM sizes itself from the memory that is free when it starts.
- Synthetic data only. Everything shown is a single-user proof of concept, not production sizing.
