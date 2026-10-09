"""Speech-to-text for D4 on a workstation (docker-compose.local.yml): QwenCleo-ASR, a Qwen3-ASR model
fine-tuned for Egyptian Arabic and Arabic-English code-switching, read from the local model store.
Same contract as the GB10's ASR service, so D4 is unchanged.

POST /transcribe multipart `file` (any format ffmpeg reads, e.g. browser webm/opus), optional
`language` (ar | en | auto) -> {text, language, audio_s, latency_ms, model}
"""
import os
import subprocess
import threading
import time

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from qwen_asr import Qwen3ASRModel

MODEL = os.getenv("ASR_MODEL", "/models/QwenCleo-ASR")
DEVICE = os.getenv("ASR_DEVICE", "cuda:0")
# What "auto" means: a Qwen3-ASR language name, or empty to let the model detect the language itself
AUTO_LANGUAGE = os.getenv("ASR_AUTO_LANGUAGE", "Arabic")
LANGUAGES = {"ar": "Arabic", "en": "English", "auto": AUTO_LANGUAGE or None}

app = FastAPI(title="NBE ASR (QwenCleo-ASR)")
model = Qwen3ASRModel.from_pretrained(MODEL, dtype=torch.bfloat16 if DEVICE.startswith("cuda") else torch.float32,
                                      device_map=DEVICE, max_new_tokens=256)
lock = threading.Lock()       # one model instance: transcription is serialised


def decode(raw: bytes) -> np.ndarray:
    """Any container/codec -> 16 kHz mono float32 via ffmpeg."""
    proc = subprocess.run(["ffmpeg", "-nostdin", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"],
                          input=raw, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise HTTPException(400, "could not decode audio")
    return np.frombuffer(proc.stdout, dtype=np.float32)


@app.get("/health")
def health():
    return {"status": "ok", "model": "QwenCleo-ASR", "device": DEVICE, "auto_language": AUTO_LANGUAGE or "detect"}


@app.post("/transcribe")
def transcribe(file: UploadFile = File(...), language: str = Form("ar")):
    if language not in LANGUAGES:
        raise HTTPException(400, f"unsupported language {language}")
    audio = decode(file.file.read())
    t = time.time()
    with lock:
        out = model.transcribe(audio=(audio, 16000), language=LANGUAGES[language])[0]
    return {"text": (out.text or "").strip(), "language": getattr(out, "language", None) or language,
            "audio_s": round(len(audio) / 16000, 2), "latency_ms": int((time.time() - t) * 1000), "model": "QwenCleo-ASR"}
