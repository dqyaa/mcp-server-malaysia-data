# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.1] - 2026-05-09

### Fixed
- Declared `httpx[http2]` extra explicitly in `pyproject.toml`. Without the
  `h2` package, `ResilientHTTPClient` raised `ImportError` at runtime on
  fresh installs. Caught during fresh-machine integration testing.
- Added `src/malaysia_data_mcp/__main__.py` so `python -m malaysia_data_mcp`
  works as a launch contract for external runners (Claude Desktop, MCP
  Inspector). Previously the package had no module entry point.

### Known issues
- Claude Desktop occasionally logs `Unexpected non-whitespace character
  after JSON at position 4` during tool calls. Server output verified clean
  via `1>stdout.log` capture; suspected benign client-side parser noise.
  Tools function correctly. Tracking for v0.1.2.

## [0.1.0] - 2026-05-08

### Added
- Initial release: 15 MCP tools, 4 resources, 3 prompts
- Dual transport: FastMCP stdio + FastAPI REST
- Two-tier cache (memory L1 + optional Redis L2)
- Resilient HTTP with retries, rate limiting, circuit breaker
- Full observability: structlog + OpenTelemetry + Prometheus
- 19 unit/property/smoke tests + integration + contract tests
- 7 ADRs documenting architecture decisions
