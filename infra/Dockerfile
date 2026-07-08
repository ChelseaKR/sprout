# Lambda-packaged build of the same `sprout serve` app the root Dockerfile runs in a
# container elsewhere. It mirrors that Dockerfile's steps exactly (same layer-caching
# shape) and adds the AWS Lambda Web Adapter extension, which lets an ordinary
# HTTP-listening container run on Lambda unmodified — no handler rewrite, no Mangum
# shim, so this image and the root one never drift in what code path they run.
# Built from the repo root: `docker build -f infra/Dockerfile .`
FROM public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 AS adapter

FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra serve --extra bedrock --extra observability

COPY src ./src
COPY config ./config
COPY corpus ./corpus
COPY web ./web
RUN uv sync --frozen --extra serve --extra bedrock --extra observability && uv run sprout ingest

# The adapter proxies Lambda invocations to this port over HTTP, so the app code (and
# its /livez, /readyz, /api/* routes) is unchanged from the non-Lambda deployment. Lambda
# auto-discovers everything under /opt/extensions/ as an extension — no exec-wrapper env
# var needed for the container-image path (that's only for zip-layer deploys).
COPY --from=adapter /lambda-adapter /opt/extensions/lambda-adapter
ENV PORT=8000 \
    AWS_LWA_READINESS_CHECK_PATH=/readyz

EXPOSE 8000
RUN useradd --uid 10001 --no-create-home sprout && chown -R sprout /app
USER sprout

CMD ["uv", "run", "sprout", "serve", "--host", "0.0.0.0"]
