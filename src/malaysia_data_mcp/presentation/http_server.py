"""FastAPI REST server — dual transport for the same 15 tools.

Why a REST wrapper alongside MCP (interview talking point):

MCP is the optimal transport for AI agents that natively support it (Claude
Desktop, Cursor, MCP-aware LangGraph). But many integrations don't speak MCP:
n8n workflows, plain LangChain agents, custom apps, monitoring dashboards.
Rather than maintain two codebases, we expose the SAME application-layer tool
functions through a thin FastAPI layer. Single source of truth, two transports.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from malaysia_data_mcp.application import tools as t
from malaysia_data_mcp.application.container import (
    Container,
    clear_container,
    get_container,
    set_container,
)
from malaysia_data_mcp.domain.errors import (
    CircuitOpenError,
    MalaysiaDataError,
    NotFoundError,
    RateLimitedError,
    UpstreamUnavailable,
)
from malaysia_data_mcp.infrastructure.observability import (
    correlation_id,
    get_logger,
    get_metrics_registry,
)
from malaysia_data_mcp.infrastructure.settings import get_settings

logger = get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    container = await Container.create()
    set_container(container)
    logger.info("rest_server_started", host=get_settings().http_host, port=get_settings().http_port)
    try:
        yield
    finally:
        await container.aclose()
        clear_container()


app = FastAPI(
    title="Malaysia Data API",
    description="Same 15 tools as the MCP server, exposed over REST for non-MCP clients.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(MalaysiaDataError)
async def _malaysia_error_handler(request: Any, exc: MalaysiaDataError) -> JSONResponse:
    """Map typed domain errors to RFC 9457 problem-detail responses."""
    if isinstance(exc, NotFoundError):
        status = 404
    elif isinstance(exc, RateLimitedError):
        status = 429
    elif isinstance(exc, CircuitOpenError):
        status = 503
    elif isinstance(exc, UpstreamUnavailable):
        status = 502
    else:
        status = 500

    body: dict[str, Any] = {
        "type": f"about:blank#{type(exc).__name__}",
        "title": type(exc).__name__,
        "status": status,
        "detail": str(exc),
    }
    if hasattr(exc, "upstream"):
        body["upstream"] = exc.upstream  # type: ignore[attr-defined]
    if hasattr(exc, "retry_after_seconds"):
        body["retry_after_seconds"] = exc.retry_after_seconds  # type: ignore[attr-defined]

    headers = {}
    if isinstance(exc, RateLimitedError | CircuitOpenError):
        headers["Retry-After"] = str(int(exc.retry_after_seconds))

    return JSONResponse(content=body, status_code=status, headers=headers)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@app.get("/", response_model=HealthResponse, tags=["meta"])
async def root() -> HealthResponse:
    return HealthResponse(status="ok", service="malaysia-data-mcp", version="0.1.0")


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    """Liveness probe — does the process respond?"""
    return {"status": "ok"}


@app.get("/readyz", tags=["meta"])
async def readyz() -> dict[str, Any]:
    """Readiness probe — can we serve traffic? Tries one cheap upstream call."""
    container = await get_container()
    try:
        await t.get_overnight_policy_rate(container)
        return {"status": "ready", "upstream_check": "ok"}
    except Exception as exc:
        raise HTTPException(503, detail=f"Upstream unhealthy: {exc}") from exc


@app.get("/metrics", tags=["meta"])
async def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(generate_latest(get_metrics_registry()), media_type=CONTENT_TYPE_LATEST)


@app.get("/tools", tags=["tools"])
async def list_tools() -> dict[str, Any]:
    """List every tool with its description, mirroring MCP capability discovery."""
    return {
        "tools": [
            {"name": name, "description": (func.__doc__ or "").strip().split("\n")[0]}
            for name, func in t.ALL_TOOLS.items()
        ]
    }


@app.post("/tools/{name}", tags=["tools"])
async def invoke_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generic tool invocation — useful for n8n / Zapier / any HTTP client."""
    if name not in t.ALL_TOOLS:
        raise HTTPException(404, detail=f"Unknown tool: {name}")
    func = t.ALL_TOOLS[name]
    container = await get_container()
    with correlation_id() as cid:
        logger.info("rest_tool_called", tool=name, args=args, correlation_id=cid)
        result = await func(container, **(args or {}))
        return result.model_dump(mode="json")


# Convenience GET wrappers — friendly for browser/curl/n8n exploration.
@app.get("/v1/exchange-rates", tags=["bnm"])
async def exchange_rates(currency: str | None = Query(None)) -> dict[str, Any]:
    return (await t.get_exchange_rates(await get_container(), currency=currency)).model_dump(mode="json")


@app.get("/v1/opr", tags=["bnm"])
async def opr() -> dict[str, Any]:
    return (await t.get_overnight_policy_rate(await get_container())).model_dump(mode="json")


@app.get("/v1/base-rates", tags=["bnm"])
async def base_rates() -> dict[str, Any]:
    return (await t.get_base_rates(await get_container())).model_dump(mode="json")


@app.get("/v1/interbank-rates", tags=["bnm"])
async def interbank_rates() -> dict[str, Any]:
    return (await t.get_interbank_rates(await get_container())).model_dump(mode="json")


@app.get("/v1/islamic-interbank-rate", tags=["bnm"])
async def islamic_interbank_rate() -> dict[str, Any]:
    return (await t.get_islamic_interbank_rate(await get_container())).model_dump(mode="json")


@app.get("/v1/kijang-emas", tags=["bnm"])
async def kijang_emas() -> dict[str, Any]:
    return (await t.get_kijang_emas_price(await get_container())).model_dump(mode="json")


@app.get("/v1/consumer-alert", tags=["bnm"])
async def consumer_alert(query: str = Query(..., min_length=1)) -> dict[str, Any]:
    return (await t.check_consumer_alert(await get_container(), query=query)).model_dump(mode="json")


@app.get("/v1/usd-myr-reference-rate", tags=["bnm"])
async def usd_myr_reference_rate() -> dict[str, Any]:
    return (await t.get_usd_myr_reference_rate(await get_container())).model_dump(mode="json")


@app.get("/v1/fuel-prices", tags=["datagovmy"])
async def fuel_prices() -> dict[str, Any]:
    return (await t.get_fuel_prices(await get_container())).model_dump(mode="json")


@app.get("/v1/cpi", tags=["datagovmy"])
async def cpi_inflation() -> dict[str, Any]:
    return (await t.get_cpi_inflation(await get_container())).model_dump(mode="json")


@app.get("/v1/gdp", tags=["datagovmy"])
async def gdp() -> dict[str, Any]:
    return (await t.get_gdp_data(await get_container())).model_dump(mode="json")


@app.get("/v1/population", tags=["datagovmy"])
async def population(state: str = Query("Malaysia")) -> dict[str, Any]:
    return (await t.get_population_stats(await get_container(), state=state)).model_dump(mode="json")


@app.get("/v1/household-income", tags=["datagovmy"])
async def household_income(state: str = Query("Malaysia")) -> dict[str, Any]:
    return (await t.get_household_income(await get_container(), state=state)).model_dump(mode="json")


@app.get("/v1/zakat-nisab", tags=["derived"])
async def zakat_nisab() -> dict[str, Any]:
    return (await t.get_zakat_nisab_threshold(await get_container())).model_dump(mode="json")


@app.get("/v1/snapshot", tags=["composite"])
async def snapshot() -> dict[str, Any]:
    return (await t.get_malaysia_economic_snapshot(await get_container())).model_dump(mode="json")


def main() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "malaysia_data_mcp.presentation.http_server:app",
        host=s.http_host,
        port=s.http_port,
        log_level=s.log_level.lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()
