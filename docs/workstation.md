# Running on a workstation (one GPU, hosted LLM)

The GB10 build serves every model itself. On a single-GPU PC the stack runs with `docker-compose.local.yml`
on top of `docker-compose.yml`: the LLM is hosted, and the small models run locally.

| Role | GB10 | Workstation |
|---|---|---|
| LLM (`workhorse`, `vision`) | Gemma 4 26B-A4B on vLLM | The same model on OpenRouter (`config/litellm.local.yaml`) |
| Embeddings, reranker | vLLM pooling servers | `nbe-retrieval`: bge-m3 and bge-reranker-v2-m3 |
| Speech out (D4) | Piper | `nbe-voicetut`: VoiceTut-TTS (Egyptian Arabic and English) |
| Speech in (D4) | whisper-large-v3 | `nbe-qwencleo`: QwenCleo-ASR (Egyptian Arabic with English mixed in) |
| Document reading (D1 uploads) | not present | `nbe-docvlm`: Qwen3-VL-8B with the fine-tuned adapter v18 |

The demo services are unchanged: the workstation services answer under the GB10 service names.
Only the model gateway gets a route to the internet; prompts leave the box through it, audio does not.
Use synthetic data in everything that calls the hosted LLM. The one exception is D1's uploaded documents:
they are read by `nbe-docvlm` on this machine, and their checks and summary use no LLM (see below).

## Before the first start

1. Models in `MODELS_DIR` (set it in `.env`): `bge-m3-source/`, `bge-reranker-v2-m3/`,
   `models--mohammedaly22--VoiceTut-TTS/` (a Hugging Face cache folder) and `QwenCleo-ASR/`.
2. `.env`: copy `.env.example`, set `OPENROUTER_API_KEY`, and `NBE_PORT` if 8200 is taken.
3. An NVIDIA GPU with about 10 GB free for the three local services, and Docker with the NVIDIA runtime.
4. For D1 uploads: `NBE_DOCVLM_REPO` in `.env` (the fine-tune project that holds `nbe_finetune/`), the base model
   `models--Qwen--Qwen3-VL-8B-Instruct-FP8/` in `MODELS_DIR`, `scripts/docvlm_libs.sh` run once (it puts the
   reader's extra Python packages in `ops/docvlm-libs`, about 300 MB, without building an image), and about
   18 GB more GPU memory.

## Start

```bash
DEMOS="d4" scripts/up_local.sh        # only D4; leave DEMOS out for all seven
VOICE=0 scripts/up_local.sh           # without VoiceTut and QwenCleo-ASR
BUILD=1 scripts/up_local.sh           # rebuild images first
DOCVLM=0 DEMOS="d1" scripts/up_local.sh  # D1 without the document reader: demo packs only
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
container (`docker restart nbe-d4`, `docker restart nbe-d1`); no image is built. The portal is served from `services/portal/dist`:
build it first, and again after a portal change, with `npm ci && npm run build` in `services/portal`
(a browser refresh picks it up). Images built without `DEV=1` stay self-contained.

## Tests for D4

```bash
docker run --rm -v ./tests:/tests:ro -v ./data:/data:ro nbe-d4 python /tests/d4_rules.py   # no models needed
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
ticket numbers and phone numbers are read digit by digit; amounts are read as numbers. A half, a quarter and
three quarters are said as such (`2.5 مليون` is "2 ونص مليون", `22.5%` is "22 ونص في المية").

- **Vowels:** the voice deletes diacritics from the text, so a word that is spelled like another (مقدم: the
  down payment مُقَدَّم, or the one who presents مُقَدِّم) is fixed in the file's `[diacritics]` section. One
  line per word covers it behind ال and the joined particles (والمقدم، بمقدم، للمقدم). The banking words there
  were vowelled from the dictionary, not checked one by one by ear: correct a line if one sounds wrong.
- **One voice:** the model samples, and the same three words came out anywhere from 158 to 258 Hz, a low
  take sounding like another speaker. `nbe-voicetut` now generates every chunk from one seed (`TTS_SEED`),
  speaks a short sentence together with its neighbour, and regenerates a chunk whose pitch is more than
  `TTS_PITCH_TOLERANCE` (15%) off the speaker's reference recording. Twelve test sentences: 177 to 216 Hz.
- **A recording that was not heard:** with the language fixed, QwenCleo-ASR cannot answer "no speech" and
  writes a sentence nobody said (room noise: «انا بحب اعمل ازاي»; silence or a hum: one phrase repeated to
  its token limit, 8 s). `nbe-qwencleo` returns `heard: false` for a silent recording (not transcribed), a
  looping one (stopped at the third repeat) and one the model was unsure of (`ASR_MIN_CONFIDENCE`, 0.6). D4
  then shows no transcript, calls no model, and asks the customer to repeat or type. On 24 test recordings
  made from the voice's own clips: the 10 it transcribed correctly, including speech in room noise, scored
  0.79 to 0.99 and were heard; noise, three voices at once and speech under louder noise scored 0.35 to 0.58
  and were not. Real callers' voices were not measured: lower the threshold if clear speech is turned away.

## D1: reading real documents

D1 has two tabs. **Uploaded documents** is for an applicant's own papers: the officer opens a loan file,
types what the applicant declared, uploads each document and names its type. **Demo packs** are the
synthetic packs with planted forgeries (`make data`). With `nbe-docvlm` installed they are read by it too,
and their summary is written from the flags, so this tab calls no hosted model either; without it they are
read by the `vision` alias as on the GB10.

Uploads never reach the model gateway. `nbe-docvlm` reads them with the serving code of the project that
trained the adapter (its prompts, image sizing and ID-number handling), mounted read-only; the checks are
rules (`services/d1_docverify/app/rules.py`); the summary is written from the flags without a model; the
audit log and the trace carry no field value. Images are stored under `data/uploads/d1` (git-ignored) and
are removed with their loan file.

- **Document types:** national ID front and back, HR letter, bank statement, invoice, utility bill, electricity
  bill, commercial register. A JPEG, PNG or WebP image, or a PDF (its first page is read).
- **Fields the adapter was not trained on** are read by the reader's plain base model through its generic
  prompt, in a second call, and shown as "general reading": the letter's date, the salary rows and paying
  company of a bank statement, and everything on an invoice. On 13 statements with known rows the salary
  rows were right 37 times in 39 and the paying company 10 times in 13, so the company is always confirmed
  by the officer before a mismatch on it counts. No real statement with salary rows or real invoice was
  available to measure on.
- **Unsure readings:** the reader returns how sure it was of every field. A mismatch that rests on an unsure
  field asks the officer to confirm the reading first; the officer can correct any field and the checks run
  again without re-reading.
- **Checks:** the ID number against itself (length, birth date, gender), front against back, expiry; the same
  name, ID number and address across the documents and the application; salary and employer against the
  application; the letter's salary against the salary rows of the bank statement, and its employer against
  the company that paid them; the letter's date and the statement's period; whether an invoice adds up; bill
  date; stamp and signature on the HR letter; missing documents.
- **Document type:** the officer picks the type of every document before adding it, and can change it on the
  document afterwards (the page is then read again). Nothing guesses the type. A detector was tried (the
  base model asked what the page calls itself: right on 113 of 133 pages, no answer on 20, wrong on none)
  and taken out at the user's request.
- **Second reading:** when a text field is unsure, the page is read again as two enlarged halves. A field
  changes only when one half is confident (0.9 or more) of another value and no half repeats the first
  reading, and it stays marked unsure either way. On 130 labelled pages (690 fields): 17 unsure fields
  changed, 14 of them to the right value; fields right went from 89.0% to 90.3% (registers and electricity
  bills: 83.1% to 85.1%). It adds two readings to a page that has unsure fields. `D1_SECOND_READ=0` turns it off.
- **Image checks on uploads** (`D1_UPLOAD_FORENSICS`, default `metadata,stamps,copy_move,patch,recompressed`),
  measured on 80 untouched real photos and the same photos with planted edits, saved again as JPEG:

  | Check | False alarms | Planted edits caught, of 79 or 80 photos |
  |---|---|---|
  | `copy_move`: a region that is an exact copy of another, grain included | 0 of 80 | a copied block on 23 |
  | `patch`: writing on a patch without the camera noise around it | 4 of 80 | a typed-over value on 14; none when the forger adds matching noise |
  | `recompressed`: content that missed the picture's first JPEG save | 1 of 80 | a typed-over value on 24, a careful one on 23, a copied block on 24, a pasted block on 26 |
  | the three together | | typed-over 35, careful typed-over 23, copied block 37, pasted block 28 |
  | `resampled`: a region resized to fit (off) | 3 of 80 | 0 to 1 of each kind |
  | `noise`: the check tuned on the generated scans (off) | 64 of 80 | |

  `patch` and `copy_move` compare a region with the camera noise around it, so they cannot check a page that
  has none: 33 of the 80 real photos (heavily compressed) and every file made on a computer; the screen says
  so on such a page. `recompressed` needs a JPEG that was saved twice at a rising quality. So about half
  to two thirds of the planted edits on real photos go unnoticed by the image checks, and a file made on a
  computer is checked only through its PDF record. These are indicators for a reviewer, not proof of an untouched document.
- **PDF record:** the program that wrote the file (an image or PDF editor is reported), a modification date
  later than the creation date, and more than one save in the file. Checked on constructed files only: no
  collection of real PDFs was available to count false alarms on.

Measured on this workstation with adapter v18 (fields correct; generated pages are from the adapter's
validation split, never trained on):

| Document | Generated pages | Real photos |
|---|---|---|
| HR letter | 99.9% of 1,278 fields (209 pages) | about 15 of 24 fields on three letters in other companies' layouts |
| Utility bill | 100% of 485 (91 pages) | none available |
| Electricity bill | 90.5% of 348 (54 pages); name and address 80% | 2 of 7 fields on the one photo not in training |
| National ID front | | 92.9% of 196 fields (49 photos) |
| National ID back | | 92.3% of 271 fields (55 photos); number 87% |
| Commercial register | 87.9% of 439 (67 pages) | 9 of 14 fields on the two photos not in training |

The three real HR letters are the warning in this table: on a layout the adapter was not trained on it
took the signer's title for the employee's, a bonus figure for the salary and the letter's date for the
hire date, and only some of those were marked unsure. Treat a letter in an unfamiliar layout as needing
the officer's eyes on every field.

About 5 s for one reading. An HR letter and a bank statement take two (adapter, then base model) and a page
with unsure fields two more, so a three-document file took 33 s on average in the benchmark below. Replayed
through `nbe-docvlm`, 82 of those pages scored 90.7% against 91.3% in the original run, and one page came
back as cut-off JSON, which D1 shows as "could not be read".

Under WSL every GPU memory block is a file handle, and the model is loaded tensor by tensor: `nbe-docvlm`
needs the raised `nofile` limit in `docker-compose.local.yml`, or the adapter fails to load with
"CUDA driver error: unknown error".

### Planted forgeries, end to end

`scripts/d1_bench_docs.py <fine-tune repo>` draws 27 documents for 9 invented applicants in the layouts the
reader knows (it uses the fine-tune project's generators and Windows fonts), makes each look photographed,
and plants 10 forgeries on the pictures and one false positive. `tests/d1_bench.py` uploads them, has them
read and checked, and scores the result:

| | Upload flow, 27 documents | Demo packs, 40 synthetic documents |
|---|---|---|
| Planted forgeries flagged | 10 of 10 | 10 of 10 |
| Genuine documents flagged | 3 of 17: two are the other side of a mismatch, one is the planted false positive | 6 of 30: five are the other side of a mismatch, one is the planted false positive |
| Time | 33 s a file of three documents (longest 54 s) | 32 s a pack of four to six documents (longest 38 s) |

Read with the numbers: the doubled salary row on a statement was caught by the image check, not by the
reading (the base model did not report the changed amount); the letter from a company that never paid the
applicant comes up as "confirm the reading first", because the paying company is one of the less reliable
readings; and the benchmark pages are drawn, not photographed.

```bash
docker run --rm -v ./tests:/tests:ro nbe-d1 python /tests/d1_rules.py     # the checks, no models needed
docker run --rm --network nbe-core -v ./tests:/tests:ro -v ./data/generated/d1_bench:/bench:ro nbe-d1 python /tests/d1_bench.py
```
