# ADR 0006 — Pydantic v2 throughout

**Status:** Accepted
**Date:** 2026-05

## Context

Every API boundary in this server — upstream JSON parsing, MCP tool input/output,
REST request/response, cache serialization — needs schema validation.

Options:
- Pydantic v1 (legacy)
- Pydantic v2 (current)
- attrs + manual validation
- dataclasses + manual validation
- TypedDict (no runtime validation)

## Decision

Pydantic v2 across all layers. Settings via pydantic-settings.

## Consequences

**Positive**

- Pydantic v2 is ~5-50× faster than v1 (Rust core via pydantic-core).
- FastAPI's request/response auto-validation uses Pydantic — same models
  serve both REST docs and validation.
- FastMCP auto-derives JSON Schema from Pydantic models, providing precise
  type info to LLM clients.
- `model_dump_json()` / `model_validate_json()` round-trip for cache.
- Works with `mypy --strict` thanks to the Pydantic mypy plugin.
- `field_validator` / `model_validator` give us a pluggable place for
  cross-field invariants.

**Negative**

- Pydantic v2 has different APIs than v1 (`.dict()` → `.model_dump()`,
  `Config` class → `model_config = ConfigDict(...)`). New developers need
  to know which version they're on.
- Validation overhead is non-zero — for very hot paths (which we don't have)
  we'd consider raw dataclasses.

## Alternatives considered

- **attrs + cattrs** — viable, faster than v1 but slower than v2. No
  ecosystem advantage over Pydantic in our domain (we use FastAPI and FastMCP,
  both Pydantic-native). Rejected.
- **TypedDict** — no runtime validation = upstream contract drift goes
  undetected. Rejected.
- **Pydantic v1** — past end-of-life path; speed is much worse; FastAPI new
  features assume v2. Rejected.
