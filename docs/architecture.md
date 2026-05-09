# Architecture

## High level

```mermaid
graph LR
  subgraph Clients
    CD[Claude Desktop]
    CR[Cursor]
    LG[LangGraph Agent]
    N8[n8n / Zapier]
    BR[Browser / curl]
  end

  subgraph Transport
    MCP[FastMCP<br/>stdio + Streamable HTTP]
    REST[FastAPI<br/>:8000]
  end

  subgraph App[Application Layer]
    T[15 tools<br/>3 prompts<br/>DI container]
  end

  subgraph Infra[Infrastructure]
    HTTP[Resilient HTTP<br/>retry • rate-limit • circuit-breaker]
    CACHE[Two-tier cache<br/>memory + Redis]
    OBS[Observability<br/>structlog • OTel • Prometheus]
  end

  subgraph Upstream
    BNM[(BNM OpenAPI)]
    DGM[(data.gov.my)]
  end

  CD & CR & LG --> MCP
  N8 & BR --> REST
  MCP --> T
  REST --> T
  T --> CACHE
  CACHE --> HTTP
  HTTP --> BNM & DGM
  T -.metrics, traces, logs.-> OBS
```

## Layered structure

```
src/malaysia_data_mcp/
├── domain/                          # zero deps; types only
│   ├── models.py                    # Pydantic v2 response models
│   └── errors.py                    # exception hierarchy
│
├── infrastructure/                  # outward adapters
│   ├── settings.py                  # 12-factor config
│   ├── observability.py             # structlog + OTel + Prometheus
│   ├── cache.py                     # 2-tier TTL cache + stampede protection
│   ├── http.py                      # httpx + tenacity + aiolimiter + circuit
│   └── clients/
│       ├── bnm.py                   # 8 BNM endpoints
│       └── datagovmy.py             # 5 data.gov.my datasets
│
├── application/                     # business logic
│   ├── container.py                 # DI container
│   ├── tools.py                     # 15 tools (pure async, MCP-agnostic)
│   └── prompts.py                   # 3 prompt templates
│
└── presentation/                    # inward adapters
    ├── mcp_server.py                # FastMCP wiring
    └── http_server.py               # FastAPI wiring
```

See [ADR-0007](./adr/0007-hexagonal-architecture.md) for the rationale.

## Request flow — example: Claude Desktop asks "what's the current OPR?"

```mermaid
sequenceDiagram
  participant U as User
  participant CD as Claude Desktop
  participant MCP as FastMCP server
  participant T as tools.get_overnight_policy_rate
  participant C as TwoTierCache
  participant H as ResilientHTTPClient
  participant B as BNM API

  U->>CD: "What's Malaysia's OPR?"
  CD->>MCP: tool_call get_overnight_policy_rate
  MCP->>T: invoke
  T->>C: get_or_set("opr", fetch=...)
  alt L1 hit
    C-->>T: cached OPRResponse
  else L1 miss, L2 hit
    C->>C: L2 lookup
    C-->>T: rehydrated OPRResponse
    C-->>C: populate L1
  else miss everywhere
    C->>H: GET /opr (rate-limit, retry, circuit)
    H->>B: HTTPS GET
    B-->>H: 200 JSON
    H-->>C: parsed dict
    C-->>C: populate L1+L2
    C-->>T: OPRResponse
  end
  T-->>MCP: serialised JSON
  MCP-->>CD: tool_result
  CD-->>U: "Malaysia's OPR is 2.75%, set on 2024-05-08"
```

## Failure modes

| Mode | What happens | Caller sees |
|---|---|---|
| BNM 5xx | retry up to N×, then circuit opens | `503 + Retry-After` (REST) / `ToolError(circuit_open)` (MCP) |
| BNM timeout | tenacity retries with exponential backoff | latency spike, eventually `502` if persists |
| Schema drift | Pydantic raises `ValidationError` → `UpstreamInvalidResponse` | `502 upstream_invalid_response` |
| Rate limit hit (local) | aiolimiter waits | latency spike, no error |
| Redis down | L2 silently falls back | warning log, increased upstream load |
| Bad input | FastAPI/Pydantic 422 / MCP schema rejection | `400` with field-level error |

## Configuration via environment variables

All settings prefixed `MALAYSIA_DATA_*`. See `infrastructure/settings.py` for
the full list. Common ones:

| Variable | Default | Purpose |
|---|---|---|
| `MALAYSIA_DATA_ENVIRONMENT` | `dev` | dev / staging / prod |
| `MALAYSIA_DATA_LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `MALAYSIA_DATA_LOG_JSON` | `true` | structured vs human-readable logs |
| `MALAYSIA_DATA_CACHE_REDIS_URL` | _(unset)_ | enables L2 cache |
| `MALAYSIA_DATA_OTEL_ENABLED` | `false` | turn on tracing |
| `MALAYSIA_DATA_OTEL_ENDPOINT` | _(unset)_ | OTLP HTTP endpoint |
| `MALAYSIA_DATA_HTTP_PORT` | `8000` | REST server bind port |
