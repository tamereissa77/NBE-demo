# Piper TTS runs on CPU (onnxruntime publishes aarch64 wheels).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY services/tts/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt
COPY services/tts/app /srv/app
RUN useradd --system --uid 10001 nbe
USER nbe
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
