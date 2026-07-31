# Sprout — optional serverless deploy

This is the **Tier-A** deployment target described in `docs/ROADMAP.md` (§ Observability
tier) and `STANDARDS/OBSERVABILITY-STANDARD.md`. It is entirely optional: the offline CLI
(Tier C) needs none of this and works with no AWS account. Deploy this only if you want a
hosted chat API behind Claude-on-Bedrock.

## What it deploys

An [AWS CDK](https://docs.aws.amazon.com/cdk/) app (`app.py` / `sprout_stack.py`) that
ships:

- A **Lambda function** built from `infra/Dockerfile` — the same `sprout serve` FastAPI
  app the root `Dockerfile` builds, with the
  [AWS Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) layered in
  so the existing container runs on Lambda unmodified. `arm64`, 512 MB, 29 s timeout (one
  second under API Gateway's HTTP API limit).
- An **API Gateway HTTP API** in front of it, default-integrated to the Lambda.
- A **monthly AWS Budget** (`CfnBudget`) with an SNS email alert at 80% and 100% of the
  configured limit — the "budget alarm" `CLAUDE.md`'s architecture plan calls for.
- The **Tier-A observability env vars** on the function (`OTEL_SERVICE_NAME`,
  `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_PROPAGATORS`,
  `OTEL_PYTHON_LOG_CORRELATION`) per `STANDARDS/OBSERVABILITY-STANDARD.md` §1 — the app
  code that reads these lives in `src/sprout/otel.py` and is gated behind
  `observability.tier: A` in `config/sprout.yaml`.
- Scale-to-zero by construction: Lambda + HTTP API bill per request; there is no
  always-on instance to idle.

This stack is genuinely deployable, but **has not been exercised against a live AWS
account as part of this change** — the same "wired, not yet run" posture `docs/ROADMAP.md`
already uses for release publishing (PyPI Trusted Publishing) and signed tags. Treat a
first real `cdk deploy` as the thing that flips this from "wired" to "exercised," and
record the result in `docs/ROADMAP.md`.

## Prerequisites

- An AWS account with `bedrock:InvokeModel` access to a Claude model in `us-west-2` (or
  your chosen region), and Amazon Bedrock model access granted for that model.
- An OTLP endpoint to export traces/metrics to (an OTel Collector you run, or a vendor
  that accepts OTLP directly — Grafana Cloud, Honeycomb, etc.). Local dev has one via
  `docker-compose.observability.yml` at the repo root; production needs your own.
- Node.js is **not** required — this is the CDK Python bindings; only `python`, `docker`
  (for the image asset build), and the AWS CLI credentials CDK needs to deploy.

## Deploy

```bash
cd infra
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# One-time per account/region:
cdk bootstrap aws://ACCOUNT_ID/REGION

cdk deploy \
  --context otlpEndpoint=https://otel-collector.example.com:4318 \
  --context budgetEmail=you@example.com \
  --context monthlyBudgetUsd=15
```

`cdk deploy` prints the API Gateway URL. Point `config/sprout.yaml`'s
`generation.provider` at `bedrock` (or `anthropic`) and set `observability.tier: A` before
building the image — the deployed Lambda serves exactly what `make dev` serves locally,
plus tracing/metrics.

## Teardown

```bash
cdk destroy
```

Deleting the stack removes the Lambda, the API Gateway API, and the budget. It does not
touch anything outside this stack (no shared VPC, no shared bucket).

## What is intentionally not here

- **Dashboards-as-code** and the **OTel Collector deployment itself** are out of scope for
  this stack — bring your own Collector/Grafana stack (or point `otlpEndpoint` at a
  managed one). `docker-compose.observability.yml` at the repo root is the local-dev
  equivalent (`STANDARDS/OBSERVABILITY-STANDARD.md` §7).
- **VPC / private networking** — Bedrock, API Gateway, and Lambda are reachable over
  public AWS service endpoints with IAM auth on the Lambda's Bedrock role; there is no
  database or private dependency that would require a VPC. If you add one (e.g. a shared
  Family Greenhouse data store), revisit this.
