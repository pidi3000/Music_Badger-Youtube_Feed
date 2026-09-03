# Single-container build: the React SPA is built first, then baked into
# the FastAPI image as static files it serves itself (PROJECT_OUTLINE.md
# §2 "Deployment topology").

FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS backend
WORKDIR /app

# Install dependencies in their own layer, cached unless pyproject.toml
# changes. Editable install so the later COPY of the real source is what
# actually runs (a non-editable install would freeze this placeholder).
COPY backend/pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --no-cache-dir -e .

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

COPY --from=frontend-build /frontend/dist ./static

RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENV STATIC_DIR=/app/static \
    DATABASE_URL=sqlite+aiosqlite:////app/data/app.db \
    PYTHONUNBUFFERED=1

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
