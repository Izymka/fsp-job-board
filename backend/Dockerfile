# Бэкенд + ML-ядро. Сборка из корня репозитория: docker build -f backend/Dockerfile .
FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/
WORKDIR /srv

# зависимости слоем отдельно от кода — кеш при изменении исходников
COPY pyproject.toml uv.lock ./
COPY ml/pyproject.toml ml/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
COPY fsp-registry-mock/pyproject.toml fsp-registry-mock/pyproject.toml
RUN mkdir -p ml/fspml backend/app fsp-registry-mock/registry && touch ml/fspml/__init__.py backend/app/__init__.py fsp-registry-mock/registry/__init__.py \
 && uv sync --frozen --no-dev --package backend --no-install-workspace

# Опционально: нейросетевые эмбеддинги rubert-tiny2 (CPU-сборка torch). По умолчанию —
# лёгкий TF-IDF fallback, качество подбора на валидации от этого не зависит.
ARG WITH_EMBEDDINGS=0
RUN if [ "$WITH_EMBEDDINGS" = "1" ]; then \
      uv pip install --python .venv/bin/python --index-url https://download.pytorch.org/whl/cpu torch && \
      uv pip install --python .venv/bin/python sentence-transformers && \
      .venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('cointegrated/rubert-tiny2')"; \
    fi

COPY ml ml
COPY backend backend
RUN uv sync --frozen --no-dev --package backend

ENV PATH="/srv/.venv/bin:$PATH" FSP_EMBEDDINGS=auto
WORKDIR /srv/backend
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=12 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips='*'"]
