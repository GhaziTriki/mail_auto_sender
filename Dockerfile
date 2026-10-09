# Stage 1: the React build. Only package.json and the lockfile are copied first so
# the npm layer is reused while sources change.
FROM node:24-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: the API and the worker share this image; compose picks the command.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /uvx /bin/
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/.venv \
    PATH="/srv/.venv/bin:$PATH"
# Dependencies first, from the lockfile, so they are cached independently of the code.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-install-project --extra dev
COPY backend/app ./app
COPY backend/tests ./tests
COPY --from=frontend /fe/dist ./app/static
RUN uv sync --locked --extra dev
COPY docs ./docs
ENV DOCS_DIR=/srv/docs
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
