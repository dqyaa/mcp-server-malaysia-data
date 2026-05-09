# ADR 0007 — Hexagonal architecture (ports & adapters)

**Status:** Accepted
**Date:** 2026-05

## Context

The codebase has multiple concerns that change at different rates:

- Business logic of "what is the OPR, what is zakat nisab, what's an
  economic snapshot" — slow-changing.
- HTTP transport details, MCP protocol specifics — change with framework
  releases.
- Upstream API quirks — change when BNM/data.gov.my version their endpoints.
- Cross-cutting infrastructure (cache, retry, observability) — semi-stable.

If these are tangled in one big `server.py`, every framework upgrade or
upstream change risks breaking unrelated logic. Tests become hard because
you can't exercise the business logic without spinning up MCP and HTTP
clients with real network calls.

## Decision

Adopt **hexagonal architecture** (also called ports and adapters):

```
src/malaysia_data_mcp/
  domain/          ← business types (Pydantic models, error hierarchy)
  infrastructure/  ← outward adapters (HTTP, cache, observability, settings)
  application/     ← use cases (the 15 tools, prompts, DI container)
  presentation/    ← inward adapters (MCP server, REST server)
```

Dependency direction: `presentation → application → domain ← infrastructure`.
Domain has no dependencies on anything else. Application depends on domain
plus interfaces it imports from infrastructure (HTTP client class, cache).
Presentation depends on application but not on infrastructure directly.

## Consequences

**Positive**

- The 15 tool functions are pure async functions taking a Container and
  returning Pydantic models. They're independently testable, transport-
  agnostic, and re-used by both MCP and REST presentations (see ADR-0005).
- A new transport (gRPC, AMQP, etc.) is a new file in `presentation/`.
- A new upstream is a new client in `infrastructure/clients/` with no
  changes to tools.
- Tests can mock at the right boundary: unit tests mock HTTP and exercise
  full tools; integration tests use real HTTP clients.

**Negative**

- More directories than a flat layout. Onboarding cost ~5 minutes.
- Risk of "architecture astronaut" patterns if someone adds layers without
  reason. Mitigated by code review + this ADR's directive: four layers,
  no more.

## Alternatives considered

- **Flat module layout** — one `server.py` with everything. Fast to start,
  expensive to change at every framework upgrade. Rejected.
- **Service layout (per-feature folders)** — appropriate for very large
  apps with bounded contexts; overkill here. Rejected.
- **Full Domain-Driven Design with aggregates and repositories** — the
  domain (read-only public APIs) doesn't have entities or aggregates worth
  modelling. Rejected as ceremony.
