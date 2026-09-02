# Reliable LLM Proxy

A small, production-minded Python service that sits between an application and an
OpenAI-compatible third-party LLM API. It centralizes authentication, model policy,
timeouts, bounded retries, safe error mapping, and basic observability without exposing
the provider credential to callers.

## Why this project

LLM integration is easy to demo but harder to operate safely. A gateway creates a narrow
control point where a team can govern which models applications use, keep provider secrets
server-side, and make failures visible. The sample deliberately focuses on the less flashy
work that turns an API integration into a dependable service.

## Architecture

```text
caller -- bearer token --> FastAPI gateway -- provider secret --> LLM API
                              |   |   |
                              |   |   +-- deadlines + retry/backoff
                              |   +------ request validation + model allowlist
                              +---------- request IDs + JSON logs + metrics
```

The upstream base URL comes only from trusted deployment configuration; callers cannot
choose arbitrary destinations. Request bodies are validated and capped. Logs contain
request metadata, never prompts, tokens, authorization headers, or upstream response bodies.
Provider errors are converted into stable, non-sensitive gateway errors.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
# Set UPSTREAM_API_KEY and choose a private INBOUND_API_KEYS value.
uvicorn gateway.main:app --reload --port 8080
```

Send a request:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H 'Authorization: Bearer demo-client-key' \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Say hello"}]}'
```

OpenAPI documentation is at `http://localhost:8080/docs`. Health is public at `/healthz`;
metrics at `/metrics` require the same bearer token as gateway traffic.

## Test and lint

```bash
pytest -q
ruff check .
```

Tests use an in-memory HTTP transport: they do not need network access or real secrets.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `UPSTREAM_API_KEY` | Provider credential; required and treated as a secret | none |
| `INBOUND_API_KEYS` | Comma-separated caller credentials; required | none |
| `ALLOWED_MODELS` | Comma-separated model allowlist | `gpt-4o-mini` |
| `UPSTREAM_BASE_URL` | Trusted OpenAI-compatible API root | OpenAI v1 API |
| `REQUEST_TIMEOUT_SECONDS` | End-to-end upstream request deadline | `20` |
| `MAX_RETRIES` | Retries for network errors, 429s, and transient 5xx responses | `2` |
| `MAX_MESSAGES` | Maximum messages per request | `50` |

For deployment, inject secrets through the platform's secret manager rather than a `.env`
file. The container runs as a non-root user.

## Deliberate tradeoffs and next steps

- The sample uses static inbound tokens to stay runnable. In a private-network deployment,
  identity from the network or control plane would support per-identity policy and audit
  attribution without distributing additional application credentials.
- Metrics are dependency-free, in-process Prometheus text counters. A real service should
  use OpenTelemetry, histograms, distributed traces, and a durable metrics backend.
- Retry behavior is intentionally bounded and limited to transient failures. Production work
  should honor `Retry-After`, use a shared retry budget, and add circuit breaking and load tests.
- The proxy implements non-streaming chat completions only. Streaming requires careful
  cancellation, backpressure, partial-failure accounting, and connection-limit testing.
- Multiple replicas need centralized rate limits and policy storage. Key rotation and audit-log
  retention would also be deployment concerns.

## Security notes

Never commit `.env` or real API keys. Rotate any secret that is accidentally exposed. Before
internet-facing deployment, add TLS at the ingress, request/body byte limits at the proxy,
per-identity rate limits, dependency scanning, and an explicit egress policy.
