# D2 extraction service

nbe-working's Chandra OCR-2 extraction service, used by D2 to add a new scanned document (back office,
manager only). Full description: `D2/ahmedsoliman/documentation/README.md`, section 12.

It receives a PDF over HTTP and returns the page JSON and crop images as a zip, so it can run on the machine
that has the GPU and the model while D2 runs elsewhere. This folder is self-contained.

## Running it on the GB10 for a D2 on the workstation

On the GB10:

```bash
# 1. the model, once (gated: the Hugging Face account must have accepted its terms)
hf download datalab-to/chandra-ocr-2 --local-dir /opt/models/chandra-ocr-2      # or wherever MODELS_DIR is

# 2. this folder, copied from the workstation, for example:
#    scp -r services/d2_extraction <user>@100.69.85.46:~/d2_extraction

# 3. start, check, and stop when done (it holds GPU memory while it runs)
cd ~/d2_extraction
MODELS_DIR=/opt/models docker compose up -d --build
curl -s localhost:8010/health        # wait for "model_loaded": true
docker compose down
```

On the workstation, D2 is started with the two override files and then documents are added with the script:

```bash
C="docker compose -f docker-compose.yml -f docker-compose.api.yml -f docker-compose.d2-extract.yml -f docker-compose.d2-extract-remote.yml"
$C --profile core up -d --wait nbe-d2
scripts/d2_upload.sh circular_12.pdf "تعميم قانوني رقم 12" "Legal circular no. 12"
```

## If it does not start on the GB10

This image has only been built for an x86 workstation in nbe-working, and has not been built or run from
this repository at all. The first start on the GB10 is the test. `docker compose logs` and `/health` show
what failed. The settings below exist for the likely cases:

| Symptom | Setting |
|---|---|
| `gpu_available: false`, or torch installed without CUDA | `D2_EXTRACT_TORCH_INDEX` (a wheel index with GPU builds for that platform), or `D2_EXTRACT_BASE_IMAGE` (an image that already ships a working GPU torch) |
| bitsandbytes fails to import or to load the model | `D2_LOAD_IN_4BIT=0`: loads in bfloat16 without bitsandbytes. Needs more memory; the output may differ slightly from the 4-bit extractions |
| The port is taken | `D2_EXTRACT_PORT`, and the same port in `D2_EXTRACTION_URL` on the workstation |
| Others on the network should not be able to submit files | `D2_EXTRACTION_TOKEN` here and the same value in the workstation's `.env` |

## API

| Endpoint | |
|---|---|
| `GET /health` | `model_loaded`, GPU name and free memory |
| `POST /v1/extract` | Multipart: `file` (PDF), `doc_id`, `doc_name`, `doc_type`, `language`. Returns a job, HTTP 202 |
| `GET /v1/jobs/{id}` | `accepted`, `running`, `complete` or `failed`; page counts; pages that could not be read |
| `GET /v1/jobs/{id}/result` | Zip: `extractions/<doc_id>/page_NNN.json`, `crops/<doc_id>/page_NNN/<block>.png` |

## Where the code comes from

`app/extractor.py`, `cropper.py`, `coords.py` and `schemas.py` are nbe-working's files (`extraction_service`
and `nbe_schemas`) with imports renamed. Changed: the model loads from a local folder with no login; 4-bit
loading can be switched off; the PDF is rendered here (`render.py`, the orchestrator's step); files travel
over HTTP instead of a shared volume; nothing is forwarded to an indexing service.
