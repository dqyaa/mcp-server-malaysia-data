# ADR 0003 — Circuit breaker for upstream APIs

**Status:** Accepted
**Date:** 2026-05

## Context

When BNM's API is degraded (which happens — public-sector APIs sometimes
experience maintenance windows or transient outages), retrying every request
amplifies the problem and stalls our server's event loop.

Concretely: with `http_max_retries=3` and 10s timeouts, every upstream call
during an outage holds an asyncio task for ~30 seconds before giving up.
At sufficient request volume this exhausts the connection pool and blocks
unrelated tools from succeeding.

## Decision

Wrap each upstream client with a **circuit breaker** (purgatory library).

State machine:
- **Closed** (normal): requests pass through.
- **Open** (after N consecutive failures): all requests fail fast with
  `CircuitOpenError` for `recovery_seconds`. No upstream calls attempted.
- **Half-open** (after recovery window): next request is allowed; on success,
  return to Closed; on failure, back to Open.

Defaults: `failure_threshold=5`, `recovery_seconds=30`.

## Consequences

**Positive**

- Prevents thundering-herd during upstream outages.
- Frees event-loop tasks during outages → unrelated tools (and `/healthz`)
  remain responsive.
- Provides a clean Retry-After header to REST clients via 503.

**Negative**

- Adds non-trivial complexity to the HTTP layer (per-upstream breaker state).
- During half-open testing, one user's request is "sacrificed" to probe
  recovery. Acceptable trade-off.

## Alternatives considered

- **Just retry forever** — pathological under outage; rejected.
- **No retries, hard-fail on first error** — overreacts to transient blips
  that retry would have masked.
- **External circuit breaker (Envoy, Istio sidecar)** — appropriate at the
  service mesh layer in a Kubernetes cluster, but overkill for our deployment
  envelope (Docker, single VM, MCP stdio). Library-level breaker is the right
  scope.
