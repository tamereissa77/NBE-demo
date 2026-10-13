"""Text-to-speech for D4 on a workstation (docker-compose.local.yml): VoiceTut-TTS, an Egyptian-Arabic
model that also speaks English and mixed sentences, loaded from the local model store. Same contract
as the Piper service it stands in for, so D4 is unchanged.

POST /tts {text, lang: ar|en, speaker?, lexicon?, careful?, overrides?} -> audio/wav

Two things decide whether a word comes out right, and neither can be done in the text itself:
- lexicon: {bare word: the same word with diacritics}. VoiceTut deletes every diacritic from the text it is
  given and then adds back the ones it knows, so a spelling such as مِيت only reaches the model through
  its own lexicon. Without it ميت (a hundred pounds) is read as مَيِّت.
- careful: solve with TTS_CAREFUL_STEPS instead of TTS_NUM_STEP. At the fast setting the model has not
  converged on rarer words and, for one, turns a ق into a hamza (بدقة came out as بدءة).

One voice. The model copies the speaker from a reference recording, and it samples: left alone, the same
three words came out anywhere from 158 to 258 Hz, and a low take of a short phrase sounds like another
person, a man. Three things hold the voice still:
- every chunk is generated from the same random seed (TTS_SEED);
- a short sentence is spoken together with the next one, never alone, when there is a next one;
- the pitch of each chunk is measured against the speaker's reference recording, and a chunk that is off by
  more than TTS_PITCH_TOLERANCE is generated again from another seed (TTS_PITCH_TRIES in all); the closest
  take is kept.
"""
import glob
import io
import os
import re
import threading
import time

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from voicetut_tts import VoiceTutTTS
from voicetut_tts.engine import split_sentences

MODEL = os.getenv("VOICETUT_MODEL", "/models/models--mohammedaly22--VoiceTut-TTS")
DEVICE = os.getenv("TTS_DEVICE", "cuda")
SPEAKER = os.getenv("TTS_SPEAKER", "Hanan")
NUM_STEP = int(os.getenv("TTS_NUM_STEP", "6"))
CAREFUL_STEPS = int(os.getenv("TTS_CAREFUL_STEPS", "32"))       # the library's own default
GUIDANCE_SCALE = float(os.getenv("TTS_GUIDANCE_SCALE", "2.0"))
SPEED = float(os.getenv("TTS_SPEED", "0.8"))                    # below 1 is slower. Picked by ear: at the engine's own pace banking
                                                                # replies ran together, and كارت was only right at 0.8
# A flow-matching model rushes and drops word endings over long spans: longer text is spoken
# sentence by sentence and joined
CHUNK_CHARS = int(os.getenv("TTS_CHUNK_CHARS", "90"))
MIN_CHUNK_CHARS = int(os.getenv("TTS_MIN_CHUNK_CHARS", "30"))   # a shorter sentence joins its neighbour
GAP_MS = int(os.getenv("TTS_GAP_MS", "120"))                    # silence between chunks
SEED = int(os.getenv("TTS_SEED", "7"))
PITCH_TOLERANCE = float(os.getenv("TTS_PITCH_TOLERANCE", "0.15"))   # 0 switches the pitch check off
PITCH_TRIES = int(os.getenv("TTS_PITCH_TRIES", "4"))
LANGS = {"ar": "arz", "en": "en"}


def snapshot(path: str) -> str:
    """A Hugging Face cache folder holds the files under snapshots/<revision>."""
    snaps = sorted(glob.glob(os.path.join(path, "snapshots", "*")))
    return snaps[0] if snaps else path


def pitch(wav: np.ndarray, rate: int) -> float:
    """Median pitch in Hz over the voiced parts of `wav` (autocorrelation of 40 ms frames); 0 if none."""
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    frame, hop = int(0.04 * rate), int(0.02 * rate)
    low, high = int(rate / 400), int(rate / 70)                 # lags of 400 Hz and 70 Hz
    quiet = 0.05 * (float(np.abs(wav).max()) if len(wav) else 0.0)
    found = []
    for start in range(0, len(wav) - frame, hop):
        x = wav[start:start + frame]
        x = x - x.mean()
        if np.sqrt((x ** 2).mean()) < quiet:
            continue
        spectrum = np.fft.rfft(x, 2 * frame)
        corr = np.fft.irfft(spectrum * np.conj(spectrum))[:high + 1]
        if corr[0] <= 0:
            continue
        lag = low + int(np.argmax(corr[low:high]))
        if corr[lag] / corr[0] > 0.5:                           # a clear period: a voiced frame
            found.append(rate / lag)
    return float(np.median(found)) if found else 0.0


app = FastAPI(title="NBE TTS (VoiceTut)")
# float16 is unsupported or very slow on CPU
engine = VoiceTutTTS.from_pretrained(snapshot(MODEL), device=DEVICE, language="arz",
                                     dtype="float16" if DEVICE.startswith("cuda") else "float32")
RATE = int(getattr(engine, "sampling_rate", 24000))
speakers = sorted(s.speaker_name for s in engine.list_speakers())
lock = threading.Lock()       # one model instance: synthesis is serialised
lexicon: dict[str, str] = {}  # what the engine has been given so far
reference_pitch: dict[str, float] = {}


def target_pitch(speaker: str) -> float:
    """The pitch of the speaker's reference recording: what every chunk is held to."""
    if speaker not in reference_pitch:
        audio, rate = sf.read(engine.registry.get(speaker).audio_path, dtype="float32", always_2d=True)
        reference_pitch[speaker] = pitch(audio.mean(axis=1), rate)
    return reference_pitch[speaker]


def chunks(text: str) -> list[str]:
    """`text` in pieces of at most CHUNK_CHARS, a short sentence joined to the one before or after it."""
    out: list[str] = []
    for piece in split_sentences(text, max_chars=CHUNK_CHARS):
        if out and min(len(out[-1]), len(piece)) < MIN_CHUNK_CHARS and len(out[-1]) + len(piece) < CHUNK_CHARS + MIN_CHUNK_CHARS:
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out


def speak(text: str, target: float, tolerance: float, kwargs: dict) -> tuple[np.ndarray, float, int]:
    """(audio, its pitch, takes) for one chunk: the first take within `tolerance` of `target`, else the closest."""
    best = None
    for attempt in range(max(1, PITCH_TRIES if tolerance and target else 1)):
        torch.manual_seed(SEED + attempt)
        wav = np.asarray(engine.synthesize(text, **kwargs), dtype=np.float32).reshape(-1)
        heard = pitch(wav, RATE)
        off = abs(heard / target - 1) if heard and target else 0.0
        if best is None or off < best[0]:
            best = (off, wav, heard)
        if off <= tolerance:
            break
    return best[1], best[2], attempt + 1


class Req(BaseModel):
    text: str
    lang: str = "ar"
    speaker: str | None = None
    lexicon: dict[str, str] = {}
    careful: bool = False                 # the whole text on the exact setting
    careful_words: list[str] = []         # or only the sentences that hold one of these words (numbers, listed words)
    overrides: dict[str, float] = {}      # for tuning by ear: num_step, guidance_scale, speed, pitch_tolerance, ...


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE, "speaker": SPEAKER, "speakers": speakers,
            "steps": {"fast": NUM_STEP, "careful": CAREFUL_STEPS}, "speed": SPEED, "lexicon_words": len(lexicon),
            "voice": {"seed": SEED, "pitch_hz": round(target_pitch(SPEAKER), 1), "tolerance": PITCH_TOLERANCE, "tries": PITCH_TRIES}}


@app.post("/tts")
def tts(r: Req):
    if r.lang not in LANGS:
        raise HTTPException(400, f"unsupported lang {r.lang}")
    speaker = r.speaker or SPEAKER
    if speaker not in speakers:
        raise HTTPException(400, f"unknown speaker {speaker}")
    overrides = dict(r.overrides)
    tolerance = overrides.pop("pitch_tolerance", PITCH_TOLERANCE)
    steps = CAREFUL_STEPS if r.careful else NUM_STEP
    # The engine's text preparation is Arabic only: in an English sentence it turns digits, currency codes, %
    # and first names into Arabic words. English is spoken as it arrives; the caller writes its numbers out.
    kwargs = dict(speaker=speaker, language=LANGS[r.lang], normalize=r.lang == "ar", num_step=steps, guidance_scale=GUIDANCE_SCALE, speed=SPEED)
    kwargs.update({k: int(v) if k == "num_step" else v for k, v in overrides.items()})
    slow = set(r.careful_words)

    def setting(piece: str) -> dict:
        """The exact setting for a piece that holds a word the fast one gets wrong; the request's setting otherwise."""
        if "num_step" in overrides or r.careful or not slow.intersection(re.findall(r"[ء-ي]+", piece)):
            return kwargs
        return {**kwargs, "num_step": CAREFUL_STEPS}

    t = time.time()
    with lock:
        new = {word: spoken for word, spoken in r.lexicon.items() if lexicon.get(word) != spoken}
        if new:
            engine.add_lexicon(new)
            lexicon.update(new)
        target = target_pitch(speaker)
        pieces = chunks(r.text)
        used = [setting(piece) for piece in pieces]
        spoken = [speak(piece, target, tolerance, k) for piece, k in zip(pieces, used)]
    gap = np.zeros(int(RATE * GAP_MS / 1000), dtype=np.float32)
    wav = np.concatenate([part for audio, _, _ in spoken for part in (audio, gap)][:-1])
    buf = io.BytesIO()
    sf.write(buf, wav, RATE, format="WAV", subtype="PCM_16")
    return Response(buf.getvalue(), media_type="audio/wav",
                    headers={"X-Latency-Ms": str(int((time.time() - t) * 1000)), "X-Model": "VoiceTut-TTS", "X-Steps": ",".join(str(k["num_step"]) for k in used), "X-Speed": str(kwargs["speed"]),
                             "X-Pitch-Hz": ",".join(str(round(p)) for _, p, _ in spoken), "X-Takes": ",".join(str(n) for _, _, n in spoken)})
