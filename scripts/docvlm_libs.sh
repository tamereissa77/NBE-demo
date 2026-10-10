#!/usr/bin/env bash
# Python packages for nbe-docvlm, D1's document reader (docker-compose.local.yml).
# The reader runs in the shared GPU image, which already holds PyTorch and CUDA. The few packages it lacks go
# into a folder on the host that the container mounts, so no image is built or changed:
#   - transformers and tokenizers at the exact versions the adapter was measured with
#   - peft (loads the LoRA adapter), OpenCV, and the torchvision that matches the image's PyTorch
# Run once, and again after the GPU image changes its PyTorch version. Needs internet; about 250 MB.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=${NBE_DOCVLM_LIBS:-ops/docvlm-libs}
IMAGE=${NBE_DOCVLM_IMAGE:-nbe-retrieval:latest}
mkdir -p "$DIR"
DIR=$(cd "$DIR" && pwd)

pip_into() { docker run --rm --user 0 -v "$DIR":/libs --entrypoint /opt/asr/bin/pip "$IMAGE" install --no-deps --upgrade --target /libs "$@"; }

pip_into transformers==4.57.1 tokenizers==0.22.1 peft==0.14.0 opencv-python-headless

# torchvision is released in step with PyTorch (2.7 with 0.22, 2.8 with 0.23, ...) and per CUDA build
read -r TV CUDA < <(docker run --rm --entrypoint python "$IMAGE" -c \
  "import torch; v, _, c = torch.__version__.partition('+'); m = v.split('.'); print(f'0.{int(m[1]) + 15}.{m[2]}', c or 'cpu')")
pip_into --index-url "https://download.pytorch.org/whl/$CUDA" "torchvision==$TV"

echo "Packages for nbe-docvlm are in $DIR (torchvision $TV for $CUDA)"
