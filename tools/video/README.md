# Demo video kit

Records a narrated walkthrough of all seven demos for the active customer: the real portal in a real browser, real
models, captions in Arabic with an English line, and a voice-over in Arabic or English. Made for Crédit du Maroc
(`recordings/CDM_AI_Demos_AR.mp4` and `_EN.mp4`, 9 min 22 s, 1080p); for another customer, edit `lines.py` and the
title cards in `film.py`.

Everything runs on the GB10 with the stack up (`make up`, voice models on). Work files stay in this folder
(`out/`, `tts/`, `tts_en/`, git-ignored).

```bash
cd ~/Bank-Demo/tools/video
docker build -t bank-demo-video:1 .                    # Playwright + ffmpeg + Xvfb, once
V="docker run --rm -v $PWD:/w -w /w"
$V --network nbe-core bank-demo-video:1 python make_tts.py       # Arabic narration (VoiceTut), cached by text
$V --network nbe-core bank-demo-video:1 python check_tts.py      # transcribe every clip back (Whisper), flag mismatches
$V --network nbe-core bank-demo-video:1 python make_tts_en.py    # English narration (Piper en_US-lessac)

make -C ../.. demo-reset
$V --network host --shm-size=2g -v ~/Bank-Demo:/repo:ro bank-demo-video:1 /w/run.sh --rehearse   # screenshots per caption in out/
make -C ../.. demo-reset
$V --network host --shm-size=2g -v ~/Bank-Demo:/repo:ro bank-demo-video:1 /w/run.sh              # the take: out/raw.mkv + events.json (~11 min)

$V bank-demo-video:1 python edit.py --offset 0.95 --out CDM_AI_Demos_AR.mp4
$V bank-demo-video:1 python edit.py --offset 0.95 --voice en --reuse 1 --out CDM_AI_Demos_EN.mp4
$V --network nbe-core bank-demo-video:1 python sync.py           # voice vs caption at several points
```

| File | |
|---|---|
| `lines.py` | The narration: per step the Arabic caption, the English line, and the text spoken if different (numbers as words) |
| `film.py` | The script of the video: title cards, clicks with a drawn cursor, captions, waits; `--rehearse`, `--only=d1,d2` |
| `edit.py` | Speeds up model waits (an on-screen counter keeps the real time), lays each clip on its caption, fades, loudness |
| `make_tts.py`, `make_tts_en.py` | Narration clips and their lengths (`tts*/index.json`); `film.py` holds each caption as long as its Arabic clip |
| `check_tts.py`, `en_check.py`, `sync.py`, `sync_en.py` | Quality checks with the on-box Whisper |

Notes from making it:
- Chromium's toolbar cannot be hidden under Playwright (kiosk and app modes are ignored), so the window is 86 px
  taller than the page and ffmpeg grabs from 108 px down (`--window-size=1536,950` at scale 1.25 = 1920×1080 page).
- `--offset` is where event time 0 sits in `raw.mkv` (the first frame of the opening card, about 1 s in).
- One ffmpeg filter graph with many trims of the same input runs out of memory on the GB10 next to the models;
  `edit.py` cuts each piece separately and joins them.
- Whisper hears «مصرف» as «مصر في» whatever the spelling: that is the recogniser, not the voice.
- The Arabic voice (VoiceTut) has an Egyptian accent; for English, Piper reads numbers correctly and VoiceTut does not.
