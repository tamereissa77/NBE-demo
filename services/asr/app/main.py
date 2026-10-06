"""Speech-to-text for D4: whisper-large-v3 (FP16) on the GB10 GPU.

POST /transcribe  multipart `file` (any format ffmpeg reads, e.g. browser webm/opus), optional
`language` (ar | en | auto). Returns text plus timing so the UI can show real latency.
"""
import os
import subprocess
import time

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from transformers import pipeline

MODEL = os.getenv("ASR_MODEL", "openai/whisper-large-v3")
app = FastAPI(title="NBE ASR (whisper-large-v3)")
asr = pipeline("automatic-speech-recognition", model=MODEL, torch_dtype=torch.float16, device="cuda:0")


def decode(raw: bytes) -> np.ndarray:
    """Any container/codec -> 16 kHz mono float32 via ffmpeg."""
    proc = subprocess.run(["ffmpeg", "-nostdin", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"],
                          input=raw, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise HTTPException(400, "could not decode audio")
    return np.frombuffer(proc.stdout, dtype=np.float32)


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL}


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form("ar")):
    audio = decode(await file.read())
    t = time.time()
    kwargs = {"task": "transcribe"}
    if language != "auto":
        kwargs["language"] = language
    out = asr({"raw": audio, "sampling_rate": 16000}, generate_kwargs=kwargs, return_timestamps=len(audio) > 30 * 16000)
    return {"text": out["text"].strip(), "language": language,
            "audio_s": round(len(audio) / 16000, 2), "latency_ms": int((time.time() - t) * 1000)}
