# Runbook: running the NBE demos on the GB10

For whoever operates the box on demo day. The talk track for each demo is in [talk-tracks.md](talk-tracks.md).

## The Efada build (fine-tuned reader, Egyptian voice)

`docker-compose.gb10.yml` adds D1's fine-tuned reader (`nbe-docvlm`) and D4's Egyptian voice (`nbe-voicetut`,
`nbe-qwencleo`) to the GB10's own models. Nothing is hosted: the workhorse is the local Gemma, and the three
services sit on the internal network like every other, so `make offline-check` covers them.

Once, online:

1. In `.env`, set the block at the end of `.env.example`: a project name and image tag of its own (a second
   checkout on a shared box keeps its own images and data), `COMPOSE_FILE` so every `make` target sees the
   overlay, and `EFADA_MODELS_DIR`.
2. Into `EFADA_MODELS_DIR`: `QwenCleo-ASR/` (a plain folder), and in Hugging Face cache layout
   `models--mohammedaly22--VoiceTut-TTS` (with `eustlb/higgs-audio-v2-tokenizer` as `audio_tokenizer/` inside
   its snapshot) and `models--Qwen--Qwen3-VL-8B-Instruct-FP8`. Each cache folder needs `refs/main` holding
   the snapshot's revision, or the offline load does not find it.
3. Into `NBE_DOCVLM_REPO`: the fine-tune project's `nbe_finetune/` (its `*.py`, `demo/` and
   `output/candidates/v18`).
4. `scripts/docvlm_libs.sh`, after the first build.

Start with `scripts/up_gb10.sh`, not `make up`: it starts the models one at a time (about 95 GB in all, the
reader 18 GB of it) and never stops another team's containers. `make down`, `status`, `gpu`, `verify`,
`offline-check` and `ui-test` work as below.

## The day before

1. `make up`: about 4 minutes from cold. It stops other GPU users on the shared box first, starts the models one at a time, then the apps, and on a fresh box generates and loads the demo data.
2. `make verify`: portal, seven demo APIs, offline proof, and a platform check of every model and service. Every line must say PASS.
3. `make ui-test`: clicks through all seven demos in a real browser with real models (about 2.5 minutes). It must print `7/7 passed`. Screenshots land in `ops/ui/`.
4. `make record`: refreshes the backup videos in `recordings/video/` (Arabic and English, one per demo). Copy them to a laptop **and** a USB stick.
5. `make offline-check`: proves no container can reach the internet. If the room's network is shaky, unplug the uplink and run `make verify` again; everything must still pass.

## Demo morning

```bash
make status        # all containers healthy, every demo answers
make gpu           # memory per container: workhorse ~35 GB, SDXL ~7-16 GB, Whisper ~4 GB
make demo-reset    # clean slate: decisions, triage, agent sessions, mock bank
make ui-test       # optional final check: warms every path too
```

Open **http://localhost:8200** on the GB10, or `http://<gb10-ip>:8200` from the presenter laptop. Add `?lang=ar` to start in Arabic. The language button switches at any time.

## Between audiences

`make demo-reset`. It keeps the data loaded and clears what the last audience did: D1 decisions, D7 triage, D4 sessions, cards blocked in the mock bank.

## The hero moment (D6, optional)

`make hero` swaps gpt-oss-120b in, in about 70 s. Voice and image go off while it runs, so do D3 and D4 first. `make hero-off` swaps back in about 2 minutes. If the hero model is down, D6 still answers code questions with the workhorse and says so on screen.

## Known limits (say them before anyone asks)

| Topic | What to know |
|---|---|
| Speed | Single-user proof of concept on one GB10. Never quote the numbers as production throughput. |
| Microphone (D4) | Browsers allow the microphone only on `https://` or `localhost`. Run D4 voice in a browser **on the GB10**, or use the script buttons and typing from the laptop. |
| Data | All synthetic. D1 documents carry a SPECIMEN watermark and are not real people, IDs, companies or banks. |
| D1 | "Flagged for review", never "fraud". A04 is clean on purpose and carries one planned false positive for the officer to clear. |
| D5 | Clauses and rulings are synthetic; NBE's legal team should validate outputs before demo day. |
| D7 | The policy rules are placeholders until NBE supplies its real ones (the screen says so). |
| Models | The Arabic gate is provisional until the human scores are in (`/eval`). Gemma 4 31B is optional (`MODE=full make up` or `make quality-on`). |

## If something breaks

| Symptom | Do this |
|---|---|
| A demo shows "Offline" or errors | `make logs-nbe-dN` (for example `logs-nbe-d4`), then `docker compose restart nbe-dN`. Apps restart in seconds. |
| Every demo fails on model calls | `make gpu`. If `nbe-llm` is missing, `make up` restarts what is down. If another project grabbed GPU memory, `make preflight` then `make up`. |
| D3 banner says "cache" | SDXL is off; cached banners are fine. `make image-on` for live generation. |
| D4 replies but no voice | Voice profile off: `make voice-on`. |
| Nothing recovers in two minutes | Play the backup video for that demo and keep talking; fix it afterwards. |

## Useful addresses

| What | Where |
|---|---|
| Portal | `http://<gb10>:8200` |
| Arabic gate (blind scoring) | `http://<gb10>:8200/eval?scorer=Name` |
| D6 OpenAI-compatible endpoint (Dataiku LLM Mesh) | `http://<gb10>:8200/v1`, model `nbe-auto`, key `D6_API_KEY` in `.env` |
| API docs for any demo | `http://<gb10>:8200/api/dN/docs` |
