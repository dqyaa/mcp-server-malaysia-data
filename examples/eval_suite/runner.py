"""Runs the agent against EVAL_SET, scores tool selection + answer content.

Run with:
    pip install -e ".[agent]"
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m examples.eval_suite.runner

Output: JSON results to stdout + summary table by category.

This is the file recruiters actually look for — proof you wrote evals before
calling the project done.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from examples.eval_suite.dataset import EVAL_SET, EvalCase, by_category


@dataclass
class CaseResult:
    case_id: str
    category: str
    called_tools: list[str]
    expected_tools: list[str]
    forbidden_tools_used: list[str]
    final_answer: str
    must_contain_hits: list[str]
    must_not_contain_hits: list[str]
    score_retrieval: float
    score_content: float
    score_total: float
    duration_seconds: float


def _score(case: EvalCase, called: set[str], answer: str, duration: float) -> CaseResult:
    forbidden_used = list(called & case.forbidden_tools)
    if forbidden_used:
        s_retrieval = 0.0  # forbidden tool → instant zero on retrieval
    elif case.expected_tools.issubset(called):
        s_retrieval = 0.5
    elif case.expected_tools and not (case.expected_tools & called):
        s_retrieval = 0.0
    else:
        s_retrieval = 0.25  # partial overlap

    answer_lower = answer.lower()
    must_hits = [s for s in case.must_contain if s.lower() in answer_lower]
    must_not_hits = [s for s in case.must_not_contain if s.lower() in answer_lower]

    s_must = 0.3 if (not case.must_contain or len(must_hits) == len(case.must_contain)) else 0.0
    s_no = 0.2 if not must_not_hits else 0.0

    s_content = s_must + s_no
    return CaseResult(
        case_id=case.id,
        category=case.category,
        called_tools=sorted(called),
        expected_tools=sorted(case.expected_tools),
        forbidden_tools_used=forbidden_used,
        final_answer=answer[:500],
        must_contain_hits=must_hits,
        must_not_contain_hits=must_not_hits,
        score_retrieval=s_retrieval,
        score_content=s_content,
        score_total=s_retrieval + s_content,
        duration_seconds=round(duration, 2),
    )


async def run_one(agent: object, case: EvalCase) -> CaseResult:
    import time

    start = time.perf_counter()
    result = await agent.ainvoke({"messages": [{"role": "user", "content": case.question}]})  # type: ignore[attr-defined]
    duration = time.perf_counter() - start

    called: set[str] = set()
    answer_parts: list[str] = []
    for msg in result["messages"]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                called.add(tc.get("name", ""))
        if hasattr(msg, "content"):
            content = msg.content
            if isinstance(content, str):
                answer_parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        answer_parts.append(part["text"])

    final = result["messages"][-1].content
    if isinstance(final, list):
        final = "\n".join(p.get("text", "") for p in final if isinstance(p, dict))

    return _score(case, called, str(final), duration)


async def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    from langchain_anthropic import ChatAnthropic
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langgraph.prebuilt import create_react_agent

    repo_root = Path(__file__).resolve().parents[2]
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

    agent = create_react_agent(
        model=ChatAnthropic(model="claude-sonnet-4-5", temperature=0, max_tokens=2048),
        tools=tools,
        prompt=(
            "You are a Malaysian financial data assistant. Use tools to fetch live data "
            "from BNM and data.gov.my. If a question is outside Malaysia's scope or "
            "outside available tools, say so plainly."
        ),
    )

    results: list[CaseResult] = []
    for i, case in enumerate(EVAL_SET, 1):
        print(f"[{i}/{len(EVAL_SET)}] {case.id}: {case.question[:60]}...", file=sys.stderr)
        try:
            results.append(await run_one(agent, case))
        except Exception as exc:  # noqa: BLE001
            print(f"   ! error: {exc}", file=sys.stderr)
            results.append(
                CaseResult(
                    case_id=case.id,
                    category=case.category,
                    called_tools=[],
                    expected_tools=sorted(case.expected_tools),
                    forbidden_tools_used=[],
                    final_answer=f"ERROR: {exc}",
                    must_contain_hits=[],
                    must_not_contain_hits=[],
                    score_retrieval=0.0,
                    score_content=0.0,
                    score_total=0.0,
                    duration_seconds=0.0,
                )
            )

    # ---- summary ----
    print("\n" + "=" * 80)
    print(f"Eval results — {len(results)} cases")
    print("=" * 80)
    for cat, cases in by_category().items():
        cat_scores = [r.score_total for r in results if r.category == cat]
        if cat_scores:
            print(f"  {cat:20s}  {sum(cat_scores) / len(cat_scores):.2f}  ({len(cat_scores)})")
    overall = sum(r.score_total for r in results) / max(len(results), 1)
    print(f"  {'OVERALL':20s}  {overall:.2f}")

    # JSON output for archival
    print("\n" + json.dumps([asdict(r) for r in results], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
