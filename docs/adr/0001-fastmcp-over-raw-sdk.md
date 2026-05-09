# ADR 0001 — FastMCP over the raw MCP SDK

**Status:** Accepted
**Date:** 2026-05

## Context

The official MCP Python SDK (`mcp` on PyPI) ships with two ways to build a
server: the low-level `Server` class which requires explicit handling of
JSON-RPC messages, request schemas, and notification flow; and `FastMCP`,
a high-level decorator-based API.

We need to expose 15 tools, 4 resources, and 3 prompts to MCP clients
(Claude Desktop, Cursor, LangGraph). We also expect the MCP spec to evolve
through 2026 (initialise improvements, sampling, progress notifications).

## Decision

Use FastMCP for tool/resource/prompt registration.

## Consequences

**Positive**

- ~70% less boilerplate per tool (decorator vs. class subclassing).
- JSON Schema for inputs is auto-generated from Python type hints; no manual
  schema maintenance.
- Output schemas are auto-derived from Pydantic return types.
- FastMCP is the framework recommended by the MCP project itself; bug fixes
  and spec evolution land here first.
- We can still drop down to the raw SDK for things FastMCP doesn't expose —
  the FastMCP server has a `.run()` that uses the underlying SDK underneath.

**Negative**

- Coupling to FastMCP's API: if the project changed direction radically we'd
  rewrite the presentation layer. Mitigated because all business logic is in
  the application layer (see ADR-0007).
- Some advanced MCP features (custom samplings, complex progress flows) may
  require dropping to the raw SDK. We accept this — the 90% case is covered.

## Alternatives considered

- **Raw `mcp.server.Server`** — full control, but 3-5x more code per tool and
  every tool needs its own JSON Schema by hand. Rejected as not justified by
  the use case.
- **Building our own MCP server from scratch** — completely rejected; this
  is a solved problem and the spec is moving fast enough that "rolling our
  own" is a maintenance trap.
