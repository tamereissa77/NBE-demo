# NBE AI demos on GB10 - single control surface. See PLAN.md §7.
.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose
# Management commands see every profile, so on-demand model servers are included in ps/stop/down/logs
COMPOSE_ALL := docker compose --profile core --profile quality --profile voice --profile image --profile hero --profile eval --profile extract
-include .env
export NBE_PORT IMAGE_TAG COMPOSE_PROJECT_NAME BRAND MODE COUNTRY BANK_NAME_EN

.PHONY: setup customer customers author start-NBE start-RYD brand help up down start stop restart build rebuild ps status logs clean \
        preflight gpu verify platform-check warm models d1 d2 d3 d4 d5 d6 d7 \
        data ingest demo-reset ui-test record offline-check arabic-gate models-lock hero hero-off quality-on quality-off voice-on voice-off image-on image-off

help:
	@echo "Bank AI demos on GB10 (customer: $${BANK_NAME_EN:-none yet}, country $${COUNTRY:-EG}, project $${COMPOSE_PROJECT_NAME:-nbe})"
	@echo ""
	@echo "  make setup         web page to add or edit a customer (logo, names, country, colours) and apply it: :$${SETUP_PORT:-8210}"
	@echo "  make customers     list the customer profiles (customers/<name>: logo, names, country, colours)"
	@echo "  make customer NAME=<name>"
	@echo "                     present the demos for that customer: its logo, colours and names, and its country's"
	@echo "                     data, currency, dialect and rules (EG, SA, AE, MA). Reloads the running stack."
	@echo "  make author        write the active country's corpus with the LLM, once per new country (~25 min, stack up)"
	@echo "  make start-NBE|start-RYD   shortcuts for make customer NAME=nbe|riyad"
	@echo "  make brand         the active customer and which stack is running"
	@echo ""
	@echo "  make up            preflight (free the GPU), then start everything in a memory-safe order"
	@echo "                     (MODE=show default: core + voice + image;  MODE=full adds Gemma 4 31B;  MODE=core: core only)"
	@echo "                     (MODE=api in .env: LLMs on external APIs, only D3 and D6 started; see .env.example)"
	@echo "  make down          stop the running demo stack, NBE or RYD, from either folder (data volumes kept)"
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
	@echo "  make data          regenerate synthetic data (D1 documents, D3 commerce, D6 docs) in containers"
	@echo "  make ingest        load every demo's data into Postgres/Qdrant (done automatically on first make up)"
	@echo "  make demo-reset    between audiences: clear decisions, triage, agent sessions, mock-bank state"
	@echo "  make ui-test       scripted walkthrough of all seven demos in the real UI (Playwright)"
	@echo "  make record        same, recording backup videos to recordings/ (English and Arabic)"
	@echo "  make offline-check prove nothing can reach the internet"
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

customer:
	@scripts/switch_customer.sh $(NAME)

customers:
	@python3 scripts/apply_customer.py --list

# The customer setup page (scripts/setup): upload a logo, set the names and country, preview, save and apply
setup:
	@python3 scripts/setup/server.py

# Once per new country: the LLM writes its procedures, knowledge base, rulings and complaints from the fact sheets
# (data/generators/countries/<cc>.py) into data/seed/<CC>; commit that folder afterwards.
author: .env
	@docker ps --format '{{.Names}}' | grep -qx nbe-llmgw || { echo "Start the stack first: make up" >&2; exit 1; }
	$(DATAGEN) python -m data.generators.author
	$(DATAGEN) python -m data.generators.d5_clauses
	@python3 scripts/apply_customer.py --seed-only >/dev/null
	@python3 scripts/apply_customer.py --seed-only
	@scripts/ingest.sh && cp data/customer.json data/generated/.loaded-customer.json

start-NBE start-RYD:
	@scripts/switch_customer.sh $(if $(findstring NBE,$@),nbe,riyad)

brand/brand.json:
	@python3 scripts/apply_customer.py $${CUSTOMER:-nbe}

brand:
	@python3 -c 'import json; c=json.load(open("data/customer.json")); print("customer:", c["name"]["en"], "-", c["country"])' 2>/dev/null || echo "customer: none yet (make customer NAME=...)"
	@docker ps --filter name=nbe-gateway --format 'running: project {{.Label "com.docker.compose.project"}} from {{.Label "com.docker.compose.project.working_dir"}}' | grep . || echo "no demo stack running"

up: .env preflight
	@scripts/up.sh

down:   ## stop whichever bank's stack is running (NBE or RYD), from either folder
	@scripts/stop_demo.sh

start:   ## only services that have a container: on-demand profiles (quality, hero, ...) usually have none
	@svcs="$$($(COMPOSE_ALL) ps -a --services)"; \
	if [ -z "$$svcs" ]; then echo "No containers for project $${COMPOSE_PROJECT_NAME:-nbe} yet: run 'make up'"; exit 1; fi; \
	$(COMPOSE_ALL) start $$svcs

stop:
	$(COMPOSE_ALL) stop

restart:
	$(COMPOSE_ALL) restart

build: .env brand/brand.json
	$(COMPOSE_ALL) --profile tools build   # tools: the data generators (datagen) and test runners

rebuild: .env brand/brand.json
	$(COMPOSE_ALL) --profile tools build --no-cache

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
	  -v $(CURDIR)/tests:/tests:ro nbe-d1:$(or $(IMAGE_TAG),latest) python /tests/platform_check.py

DATAGEN := docker compose --profile tools run --rm -u $$(id -u):$$(id -g) nbe-datagen
PW_IMAGE := mcr.microsoft.com/playwright/python:v1.55.0-noble
PW_RUN := docker run --rm --network host -u pwuser -v $(CURDIR)/tests/ui:/tests:ro

data:
	@mkdir -p data/generated/d3/banners && (chmod 777 data/generated/d3/banners 2>/dev/null || true)
	$(DATAGEN) python -m data.generators.d1_loan_docs
	$(DATAGEN) python -m data.generators.d3_commerce
	$(DATAGEN) python -m data.generators.d6_docs
	$(DATAGEN) python -m data.generators.d5_clauses
	@python3 scripts/apply_customer.py --seed-only >/dev/null || true   # the D5 clauses into data/seed-active

ingest:
	@scripts/ingest.sh

demo-reset:
	@scripts/demo_reset.sh

ui-test:
	@mkdir -p ops/ui && chmod 777 ops/ui
	$(PW_RUN) -v $(CURDIR)/ops/ui:/out $(PW_IMAGE) sh -c "pip install -q playwright==1.55.0 2>/dev/null; python /tests/walkthrough.py --base http://localhost:$${NBE_PORT:-8200} --lang en"

record: demo-reset
	@mkdir -p recordings && chmod 777 recordings
	$(PW_RUN) -v $(CURDIR)/recordings:/out $(PW_IMAGE) sh -c "pip install -q playwright==1.55.0 2>/dev/null; python /tests/walkthrough.py --base http://localhost:$${NBE_PORT:-8200} --lang ar --record && python /tests/walkthrough.py --base http://localhost:$${NBE_PORT:-8200} --lang en --record"

offline-check:
	@scripts/offline_check.sh

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
