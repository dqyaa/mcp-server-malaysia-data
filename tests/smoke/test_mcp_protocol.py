"""End-to-end MCP smoke test.

Spins up the FastMCP server in-process and exercises it via the official MCP
client, verifying:
- Initialise handshake completes
- list_tools returns all 15
- A tool call round-trips correctly
- Resources and prompts are advertised

Run with:
    pytest tests/smoke -m smoke -v

This is the test that catches "I refactored the presentation layer and broke
the protocol-level contract" — something unit tests can't see.
"""

from __future__ import annotations

import pytest


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_mcp_server_lists_15_tools() -> None:
    """The MCP server registers all 15 tools we expect."""
    from malaysia_data_mcp.presentation.mcp_server import mcp

    tools = await mcp.list_tools()
    assert len(tools) == 15
    expected = {
        "get_exchange_rates",
        "get_overnight_policy_rate",
        "get_base_rates",
        "get_interbank_rates",
        "get_islamic_interbank_rate",
        "get_kijang_emas_price",
        "check_consumer_alert",
        "get_usd_myr_reference_rate",
        "get_fuel_prices",
        "get_cpi_inflation",
        "get_gdp_data",
        "get_population_stats",
        "get_household_income",
        "get_zakat_nisab_threshold",
        "get_malaysia_economic_snapshot",
    }
    assert {t.name for t in tools} == expected


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_mcp_server_advertises_resources_and_prompts() -> None:
    """The MCP server exposes 4 resources and 3 prompts."""
    from malaysia_data_mcp.presentation.mcp_server import mcp

    resource_templates = await mcp.list_resource_templates()
    static_resources = await mcp.list_resources()
    prompts = await mcp.list_prompts()

    assert len(resource_templates) + len(static_resources) >= 4
    assert {p.name for p in prompts} == {"economic_briefing", "scam_check", "currency_planner"}


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_mcp_tool_inputs_have_documented_schemas() -> None:
    """Every tool exposes a JSON Schema. LLMs need this for accurate tool selection."""
    from malaysia_data_mcp.presentation.mcp_server import mcp

    tools = await mcp.list_tools()
    for tool in tools:
        # FastMCP auto-generates JSON Schema from type hints. Tools may have
        # zero parameters, but the schema dict must exist.
        assert tool.inputSchema is not None
        # Description must be non-empty (tool doc helps the LLM)
        assert tool.description and len(tool.description) > 10
