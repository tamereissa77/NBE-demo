# Shared image recipe for the seven demo APIs. SERVICE selects services/<SERVICE>.
FROM python:3.12-slim

ARG SERVICE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY packages/nbe_core /tmp/nbe_core
RUN pip install /tmp/nbe_core && rm -rf /tmp/nbe_core

COPY services/${SERVICE}/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt

COPY services/${SERVICE}/app /srv/app

RUN useradd --system --uid 10001 nbe
USER nbe
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
