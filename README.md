# NBE AI Demos on GB10

Seven live AI demos for National Bank of Egypt (D1–D7), one per NBE use case. They run fully offline and fully containerised on one Dell Pro Max with GB10.

See [PLAN.md](PLAN.md) for the architecture, per-demo specs, model and memory budget, and execution phases.

## Status

| Phase | State |
|---|---|
| 0. Scaffold | **Done.** Gateway, NBE-themed portal (EN/AR, RTL), Postgres, Qdrant, seven demo API services with health checks, `make verify` |
| 1. Platform | **Done.** Gemma 4 26B (workhorse + vision), Gemma 4 31B (quality), gpt-oss-120b (hero, on demand), bge-m3 + reranker, LiteLLM gateway, NeMo guardrails, mock bank, Docling, Whisper, Piper, SDXL. Measured budget in PLAN.md §5 |
| 2. Arabic gate | **Run on 5 models; awaiting blind human scores** at `/eval` (guide: `docs/arabic_gate.md`). Provisional result in PLAN.md §12 |
| 3–7 | See PLAN.md §8 |

## Quick start

```bash
make up        # creates .env on first run, frees the GPU, starts models one by one, then the apps (~4 min cold)
make verify    # portal + demo APIs + offline proof + full platform check
make gpu       # memory per container
make hero      # D6 hero moment: swap gpt-oss-120b in (~70 s);  make hero-off to swap back
```

Model weights live in `/opt/models` and are fetched once with `make models` (the only step that needs the internet).

Portal: <http://localhost:8200> (Arabic: <http://localhost:8200/?lang=ar>). Each demo is at `/d1` … `/d7`, and its API is at `/api/d1` … `/api/d7` (`/docs` for OpenAPI).

Run `make` with no target to list every command.

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
tests/               platform_check.py (run by make verify)
scripts/             preflight, gpu, verify, download_models
```

## Notes

- Only the gateway publishes a port. Every other service sits on `nbe-core`, an `internal` Docker network with no route to the internet.
- The GB10 is shared. `make preflight` (run by `make up`) stops every non-NBE GPU consumer in one go, because vLLM sizes itself from the memory that is free when it starts.
- Synthetic data only. Everything shown is a single-user proof of concept, not production sizing.
