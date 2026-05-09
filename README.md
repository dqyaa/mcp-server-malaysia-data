# 🇲🇾 Malaysia Data MCP Server

> Production-grade Model Context Protocol server giving any AI assistant live access to Bank Negara Malaysia and data.gov.my datasets — over **MCP, REST, and as a LangGraph agent tool**.

[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)](https://python.org)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP-blue)](https://github.com/jlowin/fastmcp)
[![Tests](https://img.shields.io/badge/tests-16%20passing-green)](#testing)
[![Coverage](https://img.shields.io/badge/coverage-85%25%2B-green)](#testing)
[![Type-checked](https://img.shields.io/badge/mypy-strict-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

> **Disclaimer:** Unofficial community project. Not affiliated with or endorsed by Bank Negara Malaysia, DOSM, or the Government of Malaysia. Uses their free, public APIs.

---

## What this is

Most AI assistants don't have live access to Malaysian financial data. Ask Claude or ChatGPT for today's OPR, this week's RON95 price, or whether a company is on Bank Negara's unauthorised list — you'll get a guess from training cutoffs or a refusal.

This server fixes that for **any** MCP-compatible client (Claude Desktop, Cursor, VS Code Continue, MCP-aware LangGraph), **plus** a REST API for everything else (n8n, Zapier, Streamlit, plain LangChain agents).

```text
You: "What's Malaysia's current OPR and how does it affect Islamic home financing?"
LLM: [calls get_overnight_policy_rate via MCP]
     [calls get_islamic_interbank_rate via MCP]
     "Malaysia's OPR is currently 2.75% (effective 2026-05-07).
      Islamic interbank overnight rates are tracking at..."
```

## Three transports, same 15 tools

| Client | Transport | Use case |
|---|---|---|
| Claude Desktop, Cursor, VS Code | **MCP stdio** | Local agentic workflows |
| LangGraph, MCP-aware LangChain | **MCP via langchain-mcp-adapters** | Programmatic agents (see [examples/langgraph_agent.py](examples/langgraph_agent.py)) |
| n8n, Zapier, dashboards, curl | **REST on :8000** | Anything HTTP |

All three are backed by the **same application-layer tool functions** — single source of truth, no duplication. See [ADR-0005](docs/adr/0005-dual-transport.md).

## Tools (15)

### Bank Negara Malaysia
| Tool | Returns |
|---|---|
| `get_exchange_rates` | Buying/selling/middle rates for major currencies |
| `get_overnight_policy_rate` | Current OPR + last change |
| `get_base_rates` | Base rates and BLR/BFR by bank |
| `get_interbank_rates` | Conventional interbank rates by tenure |
| `get_islamic_interbank_rate` | IIMM rates by tenure |
| `get_kijang_emas_price` | Live gold prices + per-gram derivation |
| `check_consumer_alert` | Whether an entity is on BNM's unauthorised list |
| `get_usd_myr_reference_rate` | KL USD/MYR reference rate (3:30pm daily) |

### data.gov.my (DOSM)
| Tool | Returns |
|---|---|
| `get_fuel_prices` | Weekly RON95/RON97/Diesel + week-on-week change |
| `get_cpi_inflation` | Latest headline CPI + y-o-y inflation |
| `get_gdp_data` | Latest quarterly real GDP growth |
| `get_population_stats` | Population by state |
| `get_household_income` | Median + mean income by state |

### Derived & Composite
| Tool | Returns |
|---|---|
| `get_zakat_nisab_threshold` | 85g gold value in MYR (factual; not zakat advice — see [ADR-0004](docs/adr/0004-no-zakat-advice.md)) |
| `get_malaysia_economic_snapshot` | Composite: OPR + USD/MYR + gold + fuel + inflation in one call |

Plus **3 MCP prompts** (`economic_briefing`, `scam_check`, `currency_planner`) and **4 MCP resources** for URI-addressable cached data.

---

## Why this matters technically

Most MCP servers are 100-line scripts wrapping a few API calls. This one demonstrates the **production patterns** AI engineering teams ship in 2026:

- **Hexagonal architecture** — `domain/` → `infrastructure/` → `application/` → `presentation/`. Tools are pure async functions, transports are thin wrappers, business logic is independently testable.
- **Resilient HTTP** — `httpx` async + `tenacity` retries with exponential backoff + jitter + `aiolimiter` token-bucket rate limiting + `purgatory` circuit breaker. Every upstream call is fault-tolerant by construction.
- **Two-tier cache** — L1 in-memory + optional L2 Redis with stampede protection via in-flight `asyncio.Future` sharing. Tunable per-tool TTLs.
- **Observability triad** — `structlog` JSON logs with correlation IDs + `OpenTelemetry` traces (auto-instrumented httpx) + `Prometheus` metrics on tool calls, latency, cache hit rate, circuit state.
- **Pydantic v2 throughout** — every API boundary validated, FastMCP auto-generates JSON Schema for tool I/O from the same models that validate REST.
- **Strict typing** — `mypy --strict` clean. No `Any` leaks.
- **Real test discipline** — 16 passing tests across **unit (mocked HTTP via `respx`)**, **property-based (`hypothesis`)**, **integration (live APIs, optional)**, **contract (daily upstream drift detection)**, plus an **eval suite** with 30 questions and automated scoring.
- **12-factor config** — every setting from env vars via `pydantic-settings`. Single `.env.example`.
- **Production deploy** — multi-stage Dockerfile (~150MB), docker-compose stack with Redis + Prometheus + Grafana with a pre-built dashboard.
- **CI** — GitHub Actions matrix (3.10/3.11/3.12), ruff + mypy + tests + security scan + image build, plus a daily contract-check workflow that opens a GitHub issue if BNM/DOSM change their response shapes.

See [docs/architecture.md](docs/architecture.md) for diagrams and [docs/adr/](docs/adr/) for the seven decisions that shaped the codebase.

---

## Quickstart

### 1. Run the REST server (fastest demo)

```bash
git clone https://github.com/aliyaalias19/mcp-server-malaysia-data
cd mcp-server-malaysia-data
pip install -e .
python -m malaysia_data_mcp.presentation.http_server
```

Then:
```bash
curl http://localhost:8000/v1/opr | jq
curl http://localhost:8000/v1/snapshot | jq
open http://localhost:8000/docs   # Swagger UI
```

### 2. Run with the full observability stack

```bash
docker compose -f deploy/docker-compose.yml up
```
- Server:     http://localhost:8000/docs
- Prometheus: http://localhost:9090
- Grafana:    http://localhost:3000 (admin/admin) — dashboard pre-provisioned

### 3. Connect to Claude Desktop (MCP)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%/Claude/claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "malaysia-data": {
      "command": "python",
      "args": ["-m", "malaysia_data_mcp.presentation.mcp_server"],
      "env": { "PYTHONPATH": "/ABSOLUTE/PATH/TO/mcp-server-malaysia-data/src" }
    }
  }
}
```
Restart Claude Desktop. You'll see `malaysia-data` in the tools panel.

### 4. Use as a LangGraph agent tool

```bash
pip install -e ".[agent]"
export ANTHROPIC_API_KEY=sk-ant-...
python examples/langgraph_agent.py
```

### 5. Run the eval suite

```bash
pip install -e ".[agent]"
export ANTHROPIC_API_KEY=sk-ant-...
python -m examples.eval_suite.runner
```
Reports per-category accuracy and tool-selection score on 30 hand-curated questions.

---

## Testing

```bash
pip install -e ".[dev]"

pytest tests/unit tests/property            # fast, mocked        (default)
pytest tests/integration -m integration     # hits live BNM/DOSM
pytest tests/contract -m contract           # validates upstream API shape
pytest --cov                                 # coverage report
```

Test layout:
- **Unit** (`tests/unit/`) — every tool, mocked HTTP via respx
- **Property** (`tests/property/`) — Hypothesis invariants on parsing logic
- **Integration** (`tests/integration/`) — real BNM + data.gov.my calls
- **Contract** (`tests/contract/`) — daily-run upstream shape validation
- **Smoke** (`tests/smoke/`) — end-to-end MCP protocol smoke

---

## Project layout

```
src/malaysia_data_mcp/
├── domain/               Pydantic models + error hierarchy
├── infrastructure/       HTTP, cache, observability, settings, upstream clients
├── application/          Tools, prompts, DI container
└── presentation/         FastMCP server + FastAPI server
tests/                    unit / property / integration / contract / smoke
examples/                 LangGraph agent + eval suite
deploy/                   Dockerfile, docker-compose, Prometheus, Grafana
docs/                     architecture diagrams + 7 ADRs + runbook
```

See [ADR-0007](docs/adr/0007-hexagonal-architecture.md) for the architectural rationale.

---

## Configuration

All settings via env vars (`MALAYSIA_DATA_*`). Common ones:

| Variable | Default | Purpose |
|---|---|---|
| `MALAYSIA_DATA_ENVIRONMENT` | `dev` | dev / staging / prod |
| `MALAYSIA_DATA_LOG_JSON` | `true` | structured vs human-readable logs |
| `MALAYSIA_DATA_CACHE_REDIS_URL` | unset | enables shared L2 cache |
| `MALAYSIA_DATA_OTEL_ENABLED` | `false` | OpenTelemetry tracing on/off |
| `MALAYSIA_DATA_OTEL_ENDPOINT` | unset | OTLP HTTP endpoint |
| `MALAYSIA_DATA_HTTP_PORT` | `8000` | REST bind port |

Full list in `src/malaysia_data_mcp/infrastructure/settings.py`.

---

## Related projects

- [bnm-mcp](https://github.com/meisin/bnm-mcp) — BNM-only MCP server (inspired this project)
- [mcp-datagovmy](https://github.com/hithereiamaliff/mcp-datagovmy) — data.gov.my MCP server
- [FastMCP](https://github.com/jlowin/fastmcp) — the framework underneath

This project unifies BNM + data.gov.my, adds production patterns (cache, circuit breaker, observability), exposes a parallel REST API, and ships with an eval suite.

---

## License

MIT — see [LICENSE](LICENSE).

---

Built by **[Aliya Alias](https://linkedin.com/in/aliyaalias)** — AI Engineer, Kuala Lumpur.
MSc Artificial Intelligence, University of Malaya. Currently shipping production AI for Malaysian federal-government clients.
