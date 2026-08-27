# Minimal container for the offline reference UI + API. Builds the index at image time so
# the container is self-contained and needs no network at runtime.
FROM python:3.12-slim AS base

# Apply pending Debian security updates on top of the base image. The upstream
# python:3.12-slim tag lags the trixie-security suite: on 2026-08-26 it still shipped
# openssl 3.5.6-1~deb13u2 while 3.5.7-1~deb13u2 was already published, leaving
# CVE-2026-14456 (HIGH, unbounded memory growth in the QUIC server) open in libssl3t64,
# openssl, and openssl-provider-legacy. Patching here fixes the packages for real rather
# than waiting on a base-image rebuild or muting the finding in an ignore file.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# uv for fast, reproducible installs from the committed lockfile.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

# uv is the only installer this image uses, so the interpreter's bundled pip is dead
# weight, and it is *scanned* weight: pip ships vendored copies of its own dependencies,
# and pip 25.0.1 vendors setuptools 70.3.0 (CVE-2025-47273, path traversal). Nothing
# imports it at runtime, so the surface is removed rather than ignored.
RUN rm -rf /usr/local/lib/python3.12/site-packages/pip \
           /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Install dependencies first for layer caching.
#
# `--no-dev` matters twice over. This is a runtime image, so the dev toolchain (pytest,
# mypy, ruff, coverage, hypothesis, cyclonedx, pip-audit) has no business shipping in it;
# and pip-audit drags in pip itself, whose vendor set is exactly what the image scan was
# flagging (msgpack 1.1.2 -> GHSA-6v7p-g79w-8964, setuptools 70.3.0 -> CVE-2025-47273).
# Everything the dev group provides that runtime code can reach (httpx, sigstore,
# opentelemetry) is imported lazily inside the function that needs it, behind the
# optional cloud-provider, corpus-signing, and observability seams, so the offline
# default path is unaffected.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev --extra serve

# Then the project and its data.
COPY src ./src
COPY config ./config
COPY corpus ./corpus
COPY web ./web
RUN uv sync --locked --no-dev --extra serve && uv run --no-dev sprout ingest

EXPOSE 8000
# A non-root user; no mutable server state to protect, but least-privilege anyway.
RUN useradd --uid 10001 --no-create-home sprout && chown -R sprout /app
USER sprout

HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/livez')"
# Run the console script out of the already-built venv rather than through `uv run`.
# The image runs as `sprout`, created with `--no-create-home`, so `$HOME` (/home/sprout)
# does not exist; `uv run` tries to initialize its cache under it and dies before the
# server ever starts ("Failed to initialize cache at /home/sprout/.cache/uv: Permission
# denied"). That made every build of this image non-startable. `uv run` would also try to
# re-sync the environment at container start, which is a network call this image is
# explicitly built not to need. Nothing is left to resolve at runtime, so invoke the
# entry point directly.
CMD ["/app/.venv/bin/sprout", "serve", "--host", "0.0.0.0"]
