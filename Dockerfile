# Minimal container for the offline reference UI + API. Builds the index at image time so
# the container is self-contained and needs no network at runtime.
FROM python:3.12-slim AS base

# uv for fast, reproducible installs from the committed lockfile.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Install dependencies first for layer caching.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --extra serve

# Then the project and its data.
COPY src ./src
COPY config ./config
COPY corpus ./corpus
COPY web ./web
RUN uv sync --locked --extra serve && uv run sprout ingest

EXPOSE 8000
# A non-root user; no mutable server state to protect, but least-privilege anyway.
RUN useradd --uid 10001 --no-create-home sprout && chown -R sprout /app
USER sprout

HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/livez')"
CMD ["uv", "run", "sprout", "serve", "--host", "0.0.0.0"]
