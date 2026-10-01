FROM node:22-alpine AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY scripts/import_demo_links.py ./scripts/import_demo_links.py
COPY docs/demo_links.json ./docs/demo_links.json
COPY --from=web /build/web/dist/ ./web/dist/
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python scripts/import_demo_links.py && uvicorn information_agent.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
