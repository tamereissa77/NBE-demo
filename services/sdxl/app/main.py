"""Banner mock-ups for D3: SDXL base 1.0 (FP16) via diffusers. Profile `image`, on demand.

POST /generate {prompt, negative_prompt?, width?, height?, steps?, seed?} -> PNG as base64.
"""
import base64
import io
import os
import time

import torch
from diffusers import StableDiffusionXLPipeline
from fastapi import FastAPI
from pydantic import BaseModel

# cuDNN convolutions return wrong results on GB10 with the NGC 26.05 image (measured: VAE
# round-trip error 0.65 with cuDNN vs 0.004 without), which turns SDXL output into noise.
# Native CUDA convolution kernels are correct, so cuDNN stays off for this service.
torch.backends.cudnn.enabled = os.getenv("SDXL_CUDNN", "0") == "1"

MODEL_DIR = os.getenv("SDXL_DIR", "/models/sdxl-base-1.0")
app = FastAPI(title="NBE SDXL")
pipe = StableDiffusionXLPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.float16, variant="fp16",
                                                 use_safetensors=True).to("cuda")


class Req(BaseModel):
    prompt: str
    negative_prompt: str = "text, watermark, logo, letters, low quality, blurry, deformed"
    width: int = 1216
    height: int = 832
    steps: int = 25
    seed: int = 7


@app.get("/health")
def health():
    return {"status": "ok", "model": "sdxl-base-1.0"}


@app.post("/generate")
def generate(r: Req):
    t = time.time()
    g = torch.Generator("cuda").manual_seed(r.seed)
    img = pipe(r.prompt, negative_prompt=r.negative_prompt, width=r.width, height=r.height,
               num_inference_steps=r.steps, generator=g).images[0]
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return {"png_base64": base64.b64encode(buf.getvalue()).decode(), "latency_ms": int((time.time() - t) * 1000),
            "seed": r.seed, "label": "AI-generated mock-up"}
