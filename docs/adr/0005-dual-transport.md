# ADR 0005 — Dual transport: MCP and REST

**Status:** Accepted
**Date:** 2026-05

## Context

MCP is the optimal transport for AI agents that natively support it (Claude
Desktop, Cursor, MCP-aware LangGraph, the MCP-enabled Anthropic API). But
many useful integrations don't speak MCP:

- n8n / Zapier workflows want plain HTTP
- Internal dashboards reading our data want REST
- Streamlit/Gradio prototypes use `requests`
- Plain LangChain agents (not LangGraph) wrap REST endpoints into tools

We have two choices: (a) serve only MCP and tell non-MCP users to write
adapters; (b) ship the same tools over both transports.

## Decision

Ship **both** MCP (FastMCP, stdio + Streamable HTTP) and REST (FastAPI on
port 8000), backed by the **same application-layer tool functions**.

The application layer (`tools.py`) is pure async functions that take a
`Container` and return Pydantic models. Both presentation layers
(`mcp_server.py`, `http_server.py`) are thin wrappers — they don't reimplement
business logic.

## Consequences

**Positive**

- Single source of truth for tool behaviour.
- Tests can target the application layer directly without spinning up either
  transport.
- New transports (gRPC, GraphQL) could be added later without refactoring.
- REST gives us free tooling: Swagger UI at `/docs`, Prometheus `/metrics`,
  health probes at `/healthz` and `/readyz`.

**Negative**

- Two presentation files to keep in sync when adding tools. Mitigated: the
  `ALL_TOOLS` registry in `application/tools.py` is the single list driving
  both — adding a tool means editing one place + decorating in two thin
  wrappers.
- Slightly larger Docker image (FastAPI is ~20MB more than MCP-only).

## Alternatives considered

- **MCP-only** — rejected; cuts off a meaningful slice of integration users.
- **REST-only with manual MCP adapters** — defeats the purpose of having
  built an MCP server; we'd be re-implementing what FastMCP already does.
- **One transport with an FFI bridge** — too clever, no measurable benefit.
