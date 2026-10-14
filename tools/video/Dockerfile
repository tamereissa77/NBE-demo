FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg fonts-noto-core fonts-noto-ui-core && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir playwright==1.55.0 pillow
