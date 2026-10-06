# NBE AI Demos on GB10

Seven live AI demos for National Bank of Egypt (D1–D7), one per NBE use case. They run fully offline and fully containerised on one Dell Pro Max with GB10.

See [PLAN.md](PLAN.md) for the architecture, per-demo specs, model and memory budget, and execution phases.

## Status

| Phase | State |
|---|---|
| 0. Scaffold | **Done.** Gateway, NBE-themed portal (EN/AR, RTL), Postgres, Qdrant, seven demo API services with health checks, `make verify` |
| 1. Platform (models, embeddings, guardrails, mock bank) | Next. Model weights are downloading (`make models`) |
| 2–7 | See PLAN.md §8 |

## Quick start

```bash
make up        # creates .env on first run, frees the GPU (preflight), starts the stack
make verify    # smoke test through the gateway + proof that services cannot reach the internet
make status    # containers + health of every demo
```

Portal: <http://localhost:8200> (Arabic: <http://localhost:8200/?lang=ar>). Each demo is at `/d1` … `/d7`, and its API is at `/api/d1` … `/api/d7` (`/docs` for OpenAPI).

Run `make` with no target to list every command.

## Layout

```
brand/               NBE logo, mark and colour tokens (theme.css), served by the portal
config/              Caddy gateway, Postgres init
docker/              Dockerfiles (portal, shared demo-api image)
packages/nbe_core/   shared Python library (settings, app factory, audit log)
services/d1_…d7_…/   one FastAPI service per demo
services/portal/     React + Vite + Tailwind portal
scripts/             preflight, gpu, verify, download_models
```

## Notes

- Only the gateway publishes a port. Every other service sits on `nbe-core`, an `internal` Docker network with no route to the internet.
- The GB10 is shared. `make preflight` (run by `make up`) stops every non-NBE GPU consumer in one go, because vLLM sizes itself from the memory that is free when it starts.
- Synthetic data only. Everything shown is a single-user proof of concept, not production sizing.
