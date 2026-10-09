# Running on a workstation (one GPU, hosted LLM)

The GB10 build serves every model itself. On a single-GPU PC the stack runs with `docker-compose.local.yml`
on top of `docker-compose.yml`: the LLM is hosted, and the small models run locally.

| Role | GB10 | Workstation |
|---|---|---|
| LLM (`workhorse`, `vision`) | Gemma 4 26B-A4B on vLLM | The same model on OpenRouter (`config/litellm.local.yaml`) |
| Embeddings, reranker | vLLM pooling servers | `nbe-retrieval`: bge-m3 and bge-reranker-v2-m3 |
| Speech out (D4) | Piper | `nbe-voicetut`: VoiceTut-TTS (Egyptian Arabic and English) |
| Speech in (D4) | whisper-large-v3 | `nbe-qwencleo`: QwenCleo-ASR (Egyptian Arabic with English mixed in) |

The demo services are unchanged: the workstation services answer under the GB10 service names.
Only the model gateway gets a route to the internet; prompts leave the box through it, audio does not.
Use synthetic data.

## Before the first start

1. Models in `MODELS_DIR` (set it in `.env`): `bge-m3-source/`, `bge-reranker-v2-m3/`,
   `models--mohammedaly22--VoiceTut-TTS/` (a Hugging Face cache folder) and `QwenCleo-ASR/`.
2. `.env`: copy `.env.example`, set `OPENROUTER_API_KEY`, and `NBE_PORT` if 8200 is taken.
3. An NVIDIA GPU with about 10 GB free for the three local services, and Docker with the NVIDIA runtime.

## Start

```bash
DEMOS="d4" scripts/up_local.sh        # only D4; leave DEMOS out for all seven
VOICE=0 scripts/up_local.sh           # without VoiceTut and QwenCleo-ASR
BUILD=1 scripts/up_local.sh           # rebuild images first
```

First run only: `curl -X POST http://localhost:$NBE_PORT/api/d4/admin/ingest` loads the knowledge base.

## Images and disk

The three GPU services share one recipe, `docker/local-gpu/Dockerfile`, so PyTorch and CUDA are built and
stored once (about 15 GB). `NBE_GPU_BASE` can name an earlier build to add only what changed.

A build costs several times the image size on the drive that holds Docker's data. `scripts/up_local.sh`
refuses to build with less than `NBE_MIN_FREE_GB` (default 20) free. On WSL, also cap the VM's memory in
`.wslconfig` (`memory=24GB`): a build otherwise grows the Windows pagefile on the same drive.

## Developing without rebuilds

```bash
DEV=1 DEMOS="d4" scripts/up_local.sh
```

adds `docker-compose.dev.yml`, which mounts the service code from the checkout. After an edit, restart the
container (`docker restart nbe-d4`); no image is built. The portal is served from `services/portal/dist`:
build it first, and again after a portal change, with `npm ci && npm run build` in `services/portal`
(a browser refresh picks it up). Images built without `DEV=1` stay self-contained.

## Tests for D4

```bash
docker run --rm -v ./tests:/tests:ro nbe-d4 python /tests/d4_rules.py                      # no models needed
docker run --rm --network nbe-core -v ./tests:/tests:ro nbe-d4 python /tests/d4_script.py  # real models, mock bank
```

## From another computer

Browsers allow the microphone only on `localhost` or https. `scripts/remote_tunnel.ps1` (Windows) and
`scripts/remote_tunnel.sh` (macOS, Linux) run on the laptop and forward the portal over SSH, so it opens
as `http://localhost:<port>` there.

## How the D4 voice says banking terms

`data/seed/d4/pronunciation.ini` maps written terms to how they should be spoken, per language
(`OTP = أو تي بي`, `EGP = Egyptian pounds`). It is applied to spoken replies and to the listen button on
each chat message, and is re-read when it changes: edit, save, listen again. Card endings, one-time codes,
ticket numbers and phone numbers are read digit by digit; amounts are read as numbers.
