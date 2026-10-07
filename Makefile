# NBE AI demos on GB10 - single control surface. See PLAN.md §7.
.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose
# Management commands see every profile, so on-demand model servers are included in ps/stop/down/logs
COMPOSE_ALL := docker compose --profile core --profile quality --profile voice --profile image --profile hero --profile eval
-include .env
export NBE_PORT

.PHONY: help up down start stop restart build rebuild ps status logs clean \
        preflight gpu verify platform-check warm models d1 d2 d3 d4 d5 d6 d7 \
        arabic-gate models-lock hero hero-off quality-on quality-off voice-on voice-off image-on image-off

help:
	@echo "NBE AI demos on GB10"
	@echo ""
	@echo "  make up            preflight (free the GPU), then start everything in a memory-safe order"
	@echo "                     (MODE=show default: core + quality + voice;  MODE=core: core models only)"
	@echo "  make down          stop and remove containers (data volumes kept)"
	@echo "  make start|stop    start/stop existing containers"
	@echo "  make restart       restart all containers"
	@echo "  make build         build images"
	@echo "  make rebuild       build images without cache"
	@echo "  make ps|status     container status / status + health of every demo"
	@echo "  make logs          follow all logs;  make logs-<service> (e.g. logs-nbe-d2)"
	@echo "  make clean         down + remove volumes (DELETES Postgres and Qdrant data)"
	@echo ""
	@echo "  make preflight     stop non-NBE GPU consumers together, report free memory"
	@echo "  make gpu           GPU memory per container"
	@echo "  make verify        smoke test via the gateway + offline check + platform check"
	@echo "  make platform-check  exercise every shared service through nbe_core"
	@echo "  make warm          first request to every model, so nothing is cold on stage"
	@echo ""
	@echo "  make arabic-gate   run the week-1 Arabic gate on every candidate model (~40 min), then score at /eval"
	@echo "  make models-lock   freeze the gate result into config/models.lock (after human scoring)"
	@echo "  make hero          swap quality/voice/image out, gpt-oss-120b in (D6 hero moment)"
	@echo "  make hero-off      swap back to the show configuration"
	@echo "  make quality-on|off  voice-on|off  image-on|off   switch on-demand models"
	@echo "  make models        download model weights into \$$MODELS_DIR (the only online step)"
	@echo "  make d1 .. d7      health of one demo"
	@echo ""
	@echo "  Portal: http://localhost:$${NBE_PORT:-8200}"

.env:
	@cp .env.example .env
	@sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$$(head -c 18 /dev/urandom | base64 | tr -d '/+=')/" .env
	@sed -i "s/^LITELLM_MASTER_KEY=.*/LITELLM_MASTER_KEY=sk-$$(head -c 24 /dev/urandom | base64 | tr -d '/+=')/" .env
	@sed -i "s/^D6_API_KEY=.*/D6_API_KEY=nbe-$$(head -c 18 /dev/urandom | base64 | tr -d '/+=')/" .env
	@echo "Created .env from .env.example (random Postgres password and API keys)"

up: .env preflight
	@scripts/up.sh

down:
	$(COMPOSE_ALL) down

start:
	$(COMPOSE_ALL) start

stop:
	$(COMPOSE_ALL) stop

restart:
	$(COMPOSE_ALL) restart

build: .env
	$(COMPOSE_ALL) build

rebuild: .env
	$(COMPOSE_ALL) build --no-cache

ps:
	$(COMPOSE_ALL) ps

status: ps
	@echo ""
	@for i in 1 2 3 4 5 6 7; do \
	  printf 'd%s  ' $$i; curl -fsS --max-time 5 http://localhost:$${NBE_PORT:-8200}/api/d$$i/health || printf 'unreachable'; echo; \
	done

logs:
	$(COMPOSE_ALL) logs -f --tail=100

logs-%:
	$(COMPOSE_ALL) logs -f --tail=200 $*

clean:
	$(COMPOSE_ALL) down -v

preflight:
	@scripts/preflight.sh

gpu:
	@scripts/gpu.sh

verify:
	@scripts/verify.sh

platform-check warm:
	@docker run --rm --network nbe-core --env-file .env -e LLM_GATEWAY_URL=http://nbe-llmgw:4000/v1 \
	  -v $(CURDIR)/tests:/tests:ro nbe-d1:latest python /tests/platform_check.py

arabic-gate:
	@mkdir -p ops && set -o pipefail && scripts/arabic_gate.sh 2>&1 | tee ops/arabic_gate.log

models-lock:
	@docker exec nbe-eval python -m app.gate lock > config/models.lock && cat config/models.lock

hero hero-off quality-on quality-off voice-on voice-off image-on image-off:
	@scripts/mode.sh $@

models: .env
	@HF_TOKEN=$(HF_TOKEN) MODELS_DIR=$(MODELS_DIR) scripts/download_models.sh

d1 d2 d3 d4 d5 d6 d7:
	@curl -fsS http://localhost:$${NBE_PORT:-8200}/api/$@/health; echo
