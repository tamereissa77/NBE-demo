"""Text-to-speech for D4: Piper voices on CPU (Arabic ar_JO-kareem, English en_US-lessac).

POST /tts {text, lang: ar|en} -> audio/wav
"""
import io
import os
import time
import wave

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from piper import PiperVoice
from pydantic import BaseModel

VOICES_DIR = os.getenv("PIPER_VOICES_DIR", "/models/piper-voices")
VOICE_FILES = {
    "ar": "ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx",
    "en": "en/en_US/lessac/medium/en_US-lessac-medium.onnx",
}
app = FastAPI(title="NBE TTS (Piper)")
voices = {lang: PiperVoice.load(os.path.join(VOICES_DIR, f)) for lang, f in VOICE_FILES.items()}


class Req(BaseModel):
    text: str
    lang: str = "ar"


@app.get("/health")
def health():
    return {"status": "ok", "voices": list(voices)}


@app.post("/tts")
def tts(r: Req):
    voice = voices.get(r.lang)
    if voice is None:
        raise HTTPException(400, f"unsupported lang {r.lang}")
    t = time.time()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        voice.synthesize_wav(r.text, wav)
    return Response(buf.getvalue(), media_type="audio/wav",
                    headers={"X-Latency-Ms": str(int((time.time() - t) * 1000))})
