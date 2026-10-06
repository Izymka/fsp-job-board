.PHONY: bench-build bench-estimate bench-judge bench-label bench-eval help up kc-demo down logs ps test lint fmt validate validate-quick seed reset dev-backend dev-registry dev-frontend

help:
	@echo "make up            — весь стек в Docker (http://localhost)"
	@echo "make test          — тесты ML-ядра и API"
	@echo "make validate      — процедура валидации (отчёт в docs/)"
	@echo "make dev-backend   — API локально (AUTH_MODE=dev, SQLite)"
	@echo "make dev-frontend  — фронтенд локально (Vite)"

up:
	docker compose up -d --build
	$(MAKE) kc-demo

# Демо-стенд без TLS: разрешить HTTP для админки Keycloak (realm master). В продакшене — TLS на прокси.
kc-demo:
	@until docker compose exec -T keycloak /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user $${KEYCLOAK_ADMIN:-admin} --password $${KEYCLOAK_ADMIN_PASSWORD:-admin} >/dev/null 2>&1; do sleep 3; done
	docker compose exec -T keycloak /opt/keycloak/bin/kcadm.sh update realms/master -s sslRequired=NONE

down:
	docker compose down

logs:
	docker compose logs -f --tail=100 backend frontend keycloak

ps:
	docker compose ps

test:
	uv run pytest ml/tests -q
	cd backend && uv run pytest tests -q
	cd frontend && npm run build

lint:
	uv run ruff check backend ml fsp-registry-mock
	uv run ruff format --check backend ml fsp-registry-mock

fmt:
	uv run ruff format backend ml fsp-registry-mock
	uv run ruff check --fix backend ml fsp-registry-mock

validate:
	uv run python -m fspml.validation --out docs

validate-quick:
	uv run python -m fspml.validation --out docs --quick

# Бенчмарк подбора (docs/bench.md): пул пар → LLM-асессор и эксперты → метрики
bench-build:
	uv run --all-packages --extra bench python -m fspml.bench build

bench-estimate:
	uv run python -m fspml.bench estimate

bench-judge:
	uv run python -m fspml.bench judge

bench-label:
	uv run python -m fspml.bench label

bench-eval:
	uv run python -m fspml.bench eval

seed:
	docker compose exec backend python -m app.seed

reset:
	docker compose exec backend python -m app.seed --reset

# Локальная разработка без Docker: SQLite, вход без Keycloak
dev-backend:
	cd backend && AUTH_MODE=dev DATABASE_URL=sqlite:///./dev.db FSP_EMBEDDINGS=hashing EMAIL_ENABLED=false \
	  sh -c "uv run alembic upgrade head && uv run python -m app.seed && uv run uvicorn app.main:app --reload --port 8000"

dev-registry:
	cd fsp-registry-mock && uv run uvicorn registry.main:app --port 8090

dev-frontend:
	cd frontend && npm install && npm run dev
