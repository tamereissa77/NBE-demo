# NBE AI demos on GB10 - single control surface. See PLAN.md §7.
.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose
-include .env
export NBE_PORT

.PHONY: help up down start stop restart build rebuild ps status logs clean \
        preflight gpu verify models d1 d2 d3 d4 d5 d6 d7

help:
	@echo "NBE AI demos on GB10"
	@echo ""
	@echo "  make up            preflight (free the GPU), then start everything"
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
	@echo "  make verify        smoke test via the gateway + offline check"
	@echo "  make models        download model weights into \$$MODELS_DIR (the only online step)"
	@echo "  make d1 .. d7      health of one demo"
	@echo ""
	@echo "  Portal: http://localhost:$${NBE_PORT:-8200}"

.env:
	@cp .env.example .env
	@sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$$(head -c 18 /dev/urandom | base64 | tr -d '/+=')/" .env
	@echo "Created .env from .env.example (random Postgres password)"

up: .env preflight
	$(COMPOSE) up -d
	@echo "Portal: http://localhost:$${NBE_PORT:-8200}"

down:
	$(COMPOSE) down

start:
	$(COMPOSE) start

stop:
	$(COMPOSE) stop

restart:
	$(COMPOSE) restart

build: .env
	$(COMPOSE) build

rebuild: .env
	$(COMPOSE) build --no-cache

ps:
	$(COMPOSE) ps

status: ps
	@echo ""
	@for i in 1 2 3 4 5 6 7; do \
	  printf 'd%s  ' $$i; curl -fsS --max-time 5 http://localhost:$${NBE_PORT:-8200}/api/d$$i/health || printf 'unreachable'; echo; \
	done

logs:
	$(COMPOSE) logs -f --tail=100

logs-%:
	$(COMPOSE) logs -f --tail=200 $*

clean:
	$(COMPOSE) down -v

preflight:
	@scripts/preflight.sh

gpu:
	@scripts/gpu.sh

verify:
	@scripts/verify.sh

models: .env
	@HF_TOKEN=$(HF_TOKEN) MODELS_DIR=$(MODELS_DIR) scripts/download_models.sh

d1 d2 d3 d4 d5 d6 d7:
	@curl -fsS http://localhost:$${NBE_PORT:-8200}/api/$@/health; echo
