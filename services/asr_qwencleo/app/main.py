"""Speech-to-text for D4 on a workstation (docker-compose.local.yml): QwenCleo-ASR, a Qwen3-ASR model
fine-tuned for Egyptian Arabic and Arabic-English code-switching, read from the local model store.
Same contract as the GB10's ASR service, so D4 is unchanged.

POST /transcribe multipart `file` (any format ffmpeg reads, e.g. browser webm/opus), optional
`language` (ar | en | auto) -> {text, heard, confidence, level_db, language, audio_s, latency_ms, model}

`heard` is false when the recording is not to be trusted. With the language given, the model has no way to
say "no speech": on silence, noise or a mumble it writes a fluent sentence nobody said («انا بحب اعمل ازاي»
for room noise, «انا بحبك انت بحبني انت» over and over for silence or a hum). Three measures tell such a
recording apart, and the caller should ask again when `heard` is false:
- level_db: how loud the recording gets. Silence is not given to the model at all;
- confidence: how sure the model was of the words it wrote (the typical probability of a token). Measured:
  0.79 to 0.99 for speech it got right, also in a noisy room; 0.35 to 0.58 for noise, several people at
  once, and speech under louder noise, which it got wrong;
- looping: the model repeating one phrase, which it does with full confidence. It is stopped at the third
  repeat instead of running to its token limit (8 s).
"""
import os
import subprocess
import threading
import time

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from qwen_asr import Qwen3ASRModel
from transformers import StoppingCriteria, StoppingCriteriaList

MODEL = os.getenv("ASR_MODEL", "/models/QwenCleo-ASR")
DEVICE = os.getenv("ASR_DEVICE", "cuda:0")
# What "auto" means: a Qwen3-ASR language name, or empty to let the model detect the language itself
AUTO_LANGUAGE = os.getenv("ASR_AUTO_LANGUAGE", "Arabic")
LANGUAGES = {"ar": "Arabic", "en": "English", "auto": AUTO_LANGUAGE or None}
# A recording below any of these is reported as not heard
MIN_SECONDS = float(os.getenv("ASR_MIN_SECONDS", "0.4"))
MIN_LEVEL_DB = float(os.getenv("ASR_MIN_LEVEL_DB", "-50"))
MIN_CONFIDENCE = float(os.getenv("ASR_MIN_CONFIDENCE", "0.6"))

app = FastAPI(title="NBE ASR (QwenCleo-ASR)")
model = Qwen3ASRModel.from_pretrained(MODEL, dtype=torch.bfloat16 if DEVICE.startswith("cuda") else torch.float32,
                                      device_map=DEVICE, max_new_tokens=256)
lock = threading.Lock()       # one model instance: transcription is serialised
token_logprobs: list[float] = []      # of the transcription in progress (held under `lock`)
looped: list[bool] = []


class Looping(StoppingCriteria):
    """Stops a transcription once its last 3 to 16 tokens have come three times in a row."""
    def __init__(self, prompt_tokens: int):
        self.prompt_tokens = prompt_tokens

    def __call__(self, input_ids, scores, **kwargs) -> bool:
        ids = input_ids[0, self.prompt_tokens:].tolist()
        if any(len(ids) >= 3 * n and ids[-n:] == ids[-2 * n:-n] == ids[-3 * n:-2 * n] for n in range(3, 17)):
            looped.append(True)
            return True
        return False


# The library returns only the text. Its generate() is wrapped to keep how probable each written token was,
# and to stop a transcription that loops.
_generate = model.model.generate


def _generate_scored(*args, **kwargs):
    stop = StoppingCriteriaList([Looping(kwargs["input_ids"].shape[1])])
    out = _generate(*args, output_scores=True, stopping_criteria=stop, **kwargs)
    scores = model.model.thinker.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)
    written = out.sequences[:, -scores.shape[1]:]
    for row, ids in zip(scores.float().cpu().tolist(), written.cpu().tolist()):
        token_logprobs.extend(lp for lp, tok in zip(row, ids) if tok not in (151645, 151643) and lp > -1e9)   # not end-of-text or padding
    return out


model.model.generate = _generate_scored


def level_db(audio: np.ndarray) -> float:
    """The loudest stretch of the recording in dBFS: the 95th percentile of 30 ms frames."""
    frames = audio[: len(audio) // 480 * 480].reshape(-1, 480)
    if not len(frames):
        return -120.0
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    return round(float(20 * np.log10(max(np.percentile(rms, 95), 1e-6))), 1)


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
    seconds, level = round(len(audio) / 16000, 2), level_db(audio)
    t = time.time()
    if seconds < MIN_SECONDS or level < MIN_LEVEL_DB:          # nothing to transcribe: the model would invent a sentence
        return {"text": "", "heard": False, "confidence": 0.0, "level_db": level, "looping": False, "language": language,
                "audio_s": seconds, "latency_ms": 0, "model": "QwenCleo-ASR"}
    with lock:
        token_logprobs.clear()
        looped.clear()
        out = model.transcribe(audio=(audio, 16000), language=LANGUAGES[language])[0]
        confidence = round(float(np.exp(np.mean(token_logprobs))), 3) if token_logprobs else 0.0
        text = (out.text or "").strip()
        # Also a loop the stop missed: far more was written than the library kept after removing repeats
        looping = bool(looped) or len(token_logprobs) > len(text) + 10
    heard = bool(text) and not looping and confidence >= MIN_CONFIDENCE
    return {"text": text, "heard": heard, "confidence": confidence, "level_db": level, "looping": looping,
            "language": getattr(out, "language", None) or language,
            "audio_s": seconds, "latency_ms": int((time.time() - t) * 1000), "model": "QwenCleo-ASR"}
