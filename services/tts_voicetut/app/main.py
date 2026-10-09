"""Text-to-speech for D4 on a workstation (docker-compose.local.yml): VoiceTut-TTS, an Egyptian-Arabic
model that also speaks English and mixed sentences, loaded from the local model store. Same contract
as the Piper service it stands in for, so D4 is unchanged.

POST /tts {text, lang: ar|en, speaker?, lexicon?, careful?} -> audio/wav

Two things decide whether a word comes out right, and neither can be done in the text itself:
- lexicon: {bare word: the same word with diacritics}. VoiceTut deletes every diacritic from the text it is
  given and then adds back the ones it knows, so a spelling such as مِيت only reaches the model through
  its own lexicon. Without it ميت (a hundred pounds) is read as مَيِّت.
- careful: solve with TTS_CAREFUL_STEPS instead of TTS_NUM_STEP. At the fast setting the model has not
  converged on rarer words and, for one, turns a ق into a hamza (بدقة came out as بدءة).
"""
import glob
import io
import os
import tempfile
import threading
import time

import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from voicetut_tts import VoiceTutTTS

MODEL = os.getenv("VOICETUT_MODEL", "/models/models--mohammedaly22--VoiceTut-TTS")
DEVICE = os.getenv("TTS_DEVICE", "cuda")
SPEAKER = os.getenv("TTS_SPEAKER", "Hanan")
NUM_STEP = int(os.getenv("TTS_NUM_STEP", "6"))
CAREFUL_STEPS = int(os.getenv("TTS_CAREFUL_STEPS", "32"))       # the library's own default
GUIDANCE_SCALE = float(os.getenv("TTS_GUIDANCE_SCALE", "2.0"))
# A flow-matching model rushes and drops word endings over long spans: longer text is spoken
# sentence by sentence and joined
CHUNK_CHARS = int(os.getenv("TTS_CHUNK_CHARS", "90"))
LANGS = {"ar": "arz", "en": "en"}


def snapshot(path: str) -> str:
    """A Hugging Face cache folder holds the files under snapshots/<revision>."""
    snaps = sorted(glob.glob(os.path.join(path, "snapshots", "*")))
    return snaps[0] if snaps else path


app = FastAPI(title="NBE TTS (VoiceTut)")
# float16 is unsupported or very slow on CPU
engine = VoiceTutTTS.from_pretrained(snapshot(MODEL), device=DEVICE, language="arz",
                                     dtype="float16" if DEVICE.startswith("cuda") else "float32")
speakers = sorted(s.speaker_name for s in engine.list_speakers())
lock = threading.Lock()       # one model instance: synthesis is serialised
lexicon: dict[str, str] = {}  # what the engine has been given so far


class Req(BaseModel):
    text: str
    lang: str = "ar"
    speaker: str | None = None
    lexicon: dict[str, str] = {}
    careful: bool = False


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE, "speaker": SPEAKER, "speakers": speakers,
            "steps": {"fast": NUM_STEP, "careful": CAREFUL_STEPS}, "lexicon_words": len(lexicon)}


@app.post("/tts")
def tts(r: Req):
    if r.lang not in LANGS:
        raise HTTPException(400, f"unsupported lang {r.lang}")
    speaker = r.speaker or SPEAKER
    if speaker not in speakers:
        raise HTTPException(400, f"unknown speaker {speaker}")
    steps = CAREFUL_STEPS if r.careful else NUM_STEP
    kwargs = dict(speaker=speaker, language=LANGS[r.lang], normalize=True, num_step=steps, guidance_scale=GUIDANCE_SCALE)
    t = time.time()
    with lock:
        new = {word: spoken for word, spoken in r.lexicon.items() if lexicon.get(word) != spoken}
        if new:
            engine.add_lexicon(new)
            lexicon.update(new)
        if len(r.text) > CHUNK_CHARS:
            with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
                wav = engine.synthesize_long(r.text, output=tmp.name, max_chars=CHUNK_CHARS, **kwargs)
        else:
            wav = engine.synthesize(r.text, **kwargs)
    buf = io.BytesIO()
    sf.write(buf, wav, int(getattr(engine, "sampling_rate", 24000)), format="WAV", subtype="PCM_16")
    return Response(buf.getvalue(), media_type="audio/wav",
                    headers={"X-Latency-Ms": str(int((time.time() - t) * 1000)), "X-Model": "VoiceTut-TTS", "X-Steps": str(steps)})
