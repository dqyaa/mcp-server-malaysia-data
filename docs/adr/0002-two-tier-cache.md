# ADR 0002 — Two-tier cache (in-process + optional Redis)

**Status:** Accepted
**Date:** 2026-05

## Context

The server proxies upstream BNM and data.gov.my APIs. These are free public
APIs without published rate limits, but we should be a good citizen and avoid
hammering them.

Tools differ in their data freshness profile:

- Exchange rates: change intraday → seconds-to-minutes TTL useful
- OPR: changes ~6× per year → hours-to-days TTL fine
- Population, GDP: annual/quarterly → days-to-weeks TTL fine

The server will likely be deployed in two configurations:
1. **Single instance** (developer's laptop, MCP stdio mode for Claude Desktop)
2. **Multi-instance HTTP/REST** behind a load balancer

In configuration 1, an in-memory cache is sufficient. In configuration 2,
each replica has its own cache → cache stampedes at deploy and worse hit rate.

## Decision

Implement a **two-tier cache**:

- **L1**: `cachetools.TTLCache` (in-process, microsecond access)
- **L2**: optional Redis (shared across replicas, ~1ms network hop)

Read order: L1 → on miss → L2 → on miss → upstream.
Write order: populate both layers.

L2 is enabled iff `MALAYSIA_DATA_CACHE_REDIS_URL` is set. When unset, the L2
methods become cheap no-ops and the server runs identically to L1-only.

Stampede protection: concurrent identical requests share an in-flight
`asyncio.Future` per cache key.

## Consequences

**Positive**

- Single deployment can scale from 1 to N replicas without code changes.
- Stampede protection prevents the "first request after deploy hammers BNM 50×"
  pattern.
- Per-tool TTLs let us tune for data freshness vs. upstream load.

**Negative**

- More code than a single layer (~150 lines vs ~30).
- L2 failures must never block requests — we silently fall through to upstream.
  This means a degraded Redis silently increases upstream load. Mitigated by
  monitoring `cache_l2_*` metrics in Grafana.

## Alternatives considered

- **L1 only** — would force operators to deploy single-instance only, or accept
  poor cache hit rate at scale. Rejected.
- **L2 only (Redis required)** — adds a hard infra dependency for the simple
  developer-laptop use case. Rejected.
- **HTTP-level cache (cachecontrol)** — works for some endpoints, but BNM
  doesn't set Cache-Control headers we can rely on.
