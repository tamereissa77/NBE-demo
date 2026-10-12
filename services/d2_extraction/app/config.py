"""Settings of the D2 extraction service, from environment variables.

Same values as nbe-working's extraction service, with two differences for a machine with no internet:
the model is read from a local folder (CHANDRA_MODEL_PATH) and no Hugging Face login is needed for it.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # A local folder holding datalab-to/chandra-ocr-2. If it does not exist, the model id is used and
    # HF_TOKEN must be set (the model is gated); that path needs internet and is for workstations only.
    chandra_model_path: str = os.environ.get("CHANDRA_MODEL_PATH", "/models/chandra-ocr-2")
    chandra_model_id: str = os.environ.get("CHANDRA_MODEL_ID", "datalab-to/chandra-ocr-2")
    hf_token: str = os.environ.get("HF_TOKEN", "")
    # Longest side of the page image given to the model. 2000 is what circulars 3 to 5 were extracted with.
    max_inference_dim: int = int(os.environ.get("MAX_INFERENCE_DIM", "2000"))
    # PDF pages are rendered at this scale (72 dpi x 2.7, about 200 dpi), as nbe-working's orchestrator did.
    render_scale: float = float(os.environ.get("RENDER_SCALE", "2.7"))
    crop_padding_px: int = int(os.environ.get("CROP_PADDING_PX", "8"))
    # 4-bit loading through bitsandbytes, as nbe-working did. Set LOAD_IN_4BIT=0 where bitsandbytes does not run.
    load_in_4bit: bool = os.environ.get("LOAD_IN_4BIT", "1") == "1"
    # The service's own working folder: received PDFs in <data_dir>/incoming, page images in
    # <data_dir>/docs_images, page JSON and crops in <data_dir>/pipeline_output (nbe-working's layout).
    data_dir: str = os.environ.get("DATA_DIR", "/work")

    @property
    def output_dir(self) -> str:
        return f"{self.data_dir}/pipeline_output"


settings = Settings()
