"""LangGraph agent that uses our MCP server via langchain-mcp-adapters.

Run with:
    pip install -e ".[agent]"
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/langgraph_agent.py

Why this file (interview talking point):

Agentic AI is the buzzword of 2026. Showing you can wire up an MCP server to
a LangGraph ReAct agent closes the loop on the entire promise of MCP. Most
candidates demo their MCP server only inside Claude Desktop. Adding a
programmatic agent client proves you understand the protocol from both ends.

The agent answers Malaysia-specific questions by calling the appropriate
tool(s) and grounding its response in real BNM/DOSM data.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


async def main() -> None:
    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langgraph.prebuilt import create_react_agent
    except ImportError as exc:
        print(
            'Missing agent dependencies. Install with:  pip install -e ".[agent]"',
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to run this example.", file=sys.stderr)
        raise SystemExit(1)

    repo_root = Path(__file__).resolve().parent.parent
    server_path = repo_root / "src" / "malaysia_data_mcp" / "presentation" / "mcp_server.py"

    client = MultiServerMCPClient(
        {
            "malaysia_data": {
                "command": sys.executable,
                "args": [str(server_path)],
                "transport": "stdio",
            }
        }
    )

    tools = await client.get_tools()
    print(f"Loaded {len(tools)} tools from malaysia-data MCP server")

    agent = create_react_agent(
        model=ChatAnthropic(
            model="claude-sonnet-4-5",
            temperature=0,
            max_tokens=2048,
        ),
        tools=tools,
        prompt=(
            "You are a Malaysian financial assistant. Answer questions using the "
            "available tools to fetch live data. Cite data sources (BNM, data.gov.my). "
            "When checking entities, always include BNM's warning that absence from "
            "the alert list does not prove authorisation."
        ),
    )

    questions = [
        "What is Malaysia's current OPR?",
        "I have RM 50,000 saved. What's today's gold-standard nisab threshold for zakat?",
        "Has Bank Negara warned about any entity called 'Aurora Capital'?",
        "Give me a quick economic briefing — OPR, USD/MYR, gold, and recent inflation.",
    ]

    for q in questions:
        print(f"\n{'=' * 80}\nQ: {q}\n{'-' * 80}")
        result = await agent.ainvoke({"messages": [{"role": "user", "content": q}]})
        final = result["messages"][-1].content
        if isinstance(final, list):
            final = "\n".join(part.get("text", "") for part in final if isinstance(part, dict))
        print(f"A: {final}\n")


if __name__ == "__main__":
    asyncio.run(main())
