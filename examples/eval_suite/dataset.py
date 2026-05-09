"""Evaluation dataset — 30 questions with expected tool calls.

Why this file exists (interview talking point):

LLM evaluation discipline is what separates production AI engineering from
hobby projects. Most candidates ship demos and call it a day. Senior engineers
write evals: a frozen set of inputs, expected outputs, and automated scoring.
This file is THE eval set for our MCP server's tool-selection behavior.

Each item declares:
  question:           User input the agent receives.
  expected_tools:     Tools the agent SHOULD call (set semantics).
  forbidden_tools:    Tools that signal misunderstanding if called.
  must_contain:       Substrings the answer must include (case-insensitive).
  must_not_contain:   Substrings that signal hallucination/error.
  category:           For per-category accuracy reporting.

Score model (per item, 0.0-1.0):
  +0.5 if expected_tools is a subset of called_tools (correct retrieval)
  +0.0 if any forbidden tool is called (penalty short-circuits)
  +0.3 if all must_contain strings appear in final answer
  +0.2 if no must_not_contain string appears

Aggregate: macro-average across categories. Per-category accuracy reported
separately so we can see where the agent struggles.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalCase:
    id: str
    category: str
    question: str
    expected_tools: set[str]
    forbidden_tools: set[str]
    must_contain: list[str]
    must_not_contain: list[str]


EVAL_SET: list[EvalCase] = [
    # ---- Exchange rates (5) ----
    EvalCase(
        id="fx-001",
        category="exchange_rates",
        question="What's today's USD to MYR exchange rate?",
        expected_tools={"get_exchange_rates"},
        forbidden_tools=set(),
        must_contain=["USD", "MYR"],
        must_not_contain=["I don't know", "I cannot"],
    ),
    EvalCase(
        id="fx-002",
        category="exchange_rates",
        question="How much MYR do I get for 1000 SGD at today's BNM rate?",
        expected_tools={"get_exchange_rates"},
        forbidden_tools=set(),
        must_contain=["SGD", "MYR"],
        must_not_contain=[],
    ),
    EvalCase(
        id="fx-003",
        category="exchange_rates",
        question="Give me the official KL USD/MYR reference rate published today.",
        expected_tools={"get_usd_myr_reference_rate"},
        forbidden_tools=set(),
        must_contain=["reference"],
        must_not_contain=[],
    ),
    EvalCase(
        id="fx-004",
        category="exchange_rates",
        question="Compare buying vs selling rate for JPY today.",
        expected_tools={"get_exchange_rates"},
        forbidden_tools=set(),
        must_contain=["JPY", "buying", "selling"],
        must_not_contain=[],
    ),
    EvalCase(
        id="fx-005",
        category="exchange_rates",
        question="What's the EUR/MYR middle rate?",
        expected_tools={"get_exchange_rates"},
        forbidden_tools=set(),
        must_contain=["EUR"],
        must_not_contain=[],
    ),
    # ---- Monetary policy (5) ----
    EvalCase(
        id="mp-001",
        category="monetary_policy",
        question="What's Malaysia's current OPR?",
        expected_tools={"get_overnight_policy_rate"},
        forbidden_tools=set(),
        must_contain=["OPR"],
        must_not_contain=[],
    ),
    EvalCase(
        id="mp-002",
        category="monetary_policy",
        question="What are the current Base Lending Rates of major Malaysian banks?",
        expected_tools={"get_base_rates"},
        forbidden_tools=set(),
        must_contain=["BLR"],
        must_not_contain=[],
    ),
    EvalCase(
        id="mp-003",
        category="monetary_policy",
        question="Show me current interbank money market rates.",
        expected_tools={"get_interbank_rates"},
        forbidden_tools=set(),
        must_contain=["interbank"],
        must_not_contain=[],
    ),
    EvalCase(
        id="mp-004",
        category="monetary_policy",
        question="What's the IIMM rate for overnight Islamic interbank?",
        expected_tools={"get_islamic_interbank_rate"},
        forbidden_tools=set(),
        must_contain=["Islamic"],
        must_not_contain=[],
    ),
    EvalCase(
        id="mp-005",
        category="monetary_policy",
        question="Has BNM changed the OPR recently?",
        expected_tools={"get_overnight_policy_rate"},
        forbidden_tools=set(),
        must_contain=["OPR"],
        must_not_contain=[],
    ),
    # ---- Commodity / gold / nisab (4) ----
    EvalCase(
        id="gold-001",
        category="gold",
        question="What's the current Kijang Emas gold price?",
        expected_tools={"get_kijang_emas_price"},
        forbidden_tools=set(),
        must_contain=["Kijang Emas"],
        must_not_contain=[],
    ),
    EvalCase(
        id="gold-002",
        category="gold",
        question="What's today's gold-standard nisab threshold in MYR?",
        expected_tools={"get_zakat_nisab_threshold"},
        forbidden_tools=set(),
        must_contain=["nisab"],
        must_not_contain=[],
    ),
    EvalCase(
        id="gold-003",
        category="gold",
        question="Calculate my zakat. I have RM 100,000 in savings.",
        expected_tools={"get_zakat_nisab_threshold"},
        # Agent should provide nisab + warning, NOT compute fiqh-binding output:
        forbidden_tools=set(),
        must_contain=["nisab", "authority"],  # must mention state authority
        must_not_contain=["RM 2,500"],  # the "answer" without consulting authority
    ),
    EvalCase(
        id="gold-004",
        category="gold",
        question="What's gold worth per gram in Malaysia today?",
        expected_tools={"get_kijang_emas_price"},
        forbidden_tools=set(),
        must_contain=["gram"],
        must_not_contain=[],
    ),
    # ---- Consumer alert / scam check (5) ----
    EvalCase(
        id="alert-001",
        category="consumer_alert",
        question="Has Bank Negara warned about Aurora Capital?",
        expected_tools={"check_consumer_alert"},
        forbidden_tools=set(),
        must_contain=["BNM"],
        must_not_contain=[],
    ),
    EvalCase(
        id="alert-002",
        category="consumer_alert",
        question="Is XYZ Crypto Investments on BNM's unauthorised list?",
        expected_tools={"check_consumer_alert"},
        forbidden_tools=set(),
        must_contain=["unauthorised"],
        must_not_contain=[],
    ),
    EvalCase(
        id="alert-003",
        category="consumer_alert",
        question="I want to invest with FirstGold Trading. Should I?",
        expected_tools={"check_consumer_alert"},
        forbidden_tools=set(),
        # Critical: agent must NOT give green light just because not on list.
        must_contain=["does not", "verify"],  # absence != authorised
        must_not_contain=["safe to invest", "go ahead"],
    ),
    EvalCase(
        id="alert-004",
        category="consumer_alert",
        question="Check if 'capital' appears anywhere on the BNM unauthorised list.",
        expected_tools={"check_consumer_alert"},
        forbidden_tools=set(),
        must_contain=["capital"],
        must_not_contain=[],
    ),
    EvalCase(
        id="alert-005",
        category="consumer_alert",
        question="My friend lost money to 'Crown Forex'. What does BNM say about them?",
        expected_tools={"check_consumer_alert"},
        forbidden_tools=set(),
        must_contain=["BNM"],
        must_not_contain=[],
    ),
    # ---- Cost of living (4) ----
    EvalCase(
        id="cost-001",
        category="cost_of_living",
        question="How much is petrol RON95 this week?",
        expected_tools={"get_fuel_prices"},
        forbidden_tools=set(),
        must_contain=["RON95"],
        must_not_contain=[],
    ),
    EvalCase(
        id="cost-002",
        category="cost_of_living",
        question="What's the latest CPI inflation rate?",
        expected_tools={"get_cpi_inflation"},
        forbidden_tools=set(),
        must_contain=["inflation"],
        must_not_contain=[],
    ),
    EvalCase(
        id="cost-003",
        category="cost_of_living",
        question="Did diesel prices change this week?",
        expected_tools={"get_fuel_prices"},
        forbidden_tools=set(),
        must_contain=["diesel"],
        must_not_contain=[],
    ),
    EvalCase(
        id="cost-004",
        category="cost_of_living",
        question="What's the median household income in Selangor?",
        expected_tools={"get_household_income"},
        forbidden_tools=set(),
        must_contain=["Selangor"],
        must_not_contain=[],
    ),
    # ---- Macroeconomic (3) ----
    EvalCase(
        id="macro-001",
        category="macro",
        question="What's Malaysia's latest GDP growth?",
        expected_tools={"get_gdp_data"},
        forbidden_tools=set(),
        must_contain=["GDP"],
        must_not_contain=[],
    ),
    EvalCase(
        id="macro-002",
        category="macro",
        question="What's the population of Penang?",
        expected_tools={"get_population_stats"},
        forbidden_tools=set(),
        must_contain=["Pulau Pinang"],
        must_not_contain=[],
    ),
    EvalCase(
        id="macro-003",
        category="macro",
        question="Give me a quick economic briefing of Malaysia.",
        # Either composite OR each individually is acceptable:
        expected_tools={"get_malaysia_economic_snapshot"},
        forbidden_tools=set(),
        must_contain=["OPR", "inflation"],
        must_not_contain=[],
    ),
    # ---- Negative / robustness (4) ----
    EvalCase(
        id="neg-001",
        category="negative",
        question="What's the price of RON95 in Singapore?",
        # No tool — Malaysia-only server should clarify.
        expected_tools=set(),
        forbidden_tools={"get_fuel_prices"},
        must_contain=["Malaysia"],
        must_not_contain=[],
    ),
    EvalCase(
        id="neg-002",
        category="negative",
        question="What's the weather like in KL today?",
        expected_tools=set(),
        forbidden_tools=set(),
        must_contain=[],  # graceful "I can't help with weather"
        must_not_contain=["sunny", "cloudy"],  # don't fabricate
    ),
    EvalCase(
        id="neg-003",
        category="negative",
        question="What's the OPR in Indonesia?",
        expected_tools=set(),
        forbidden_tools={"get_overnight_policy_rate"},
        must_contain=["Malaysia"],
        must_not_contain=[],
    ),
    EvalCase(
        id="neg-004",
        category="negative",
        question="Is BNM a scam?",  # provocative; agent should redirect, not search alert list
        expected_tools=set(),
        forbidden_tools={"check_consumer_alert"},
        must_contain=["central bank"],
        must_not_contain=[],
    ),
]


def by_category() -> dict[str, list[EvalCase]]:
    out: dict[str, list[EvalCase]] = {}
    for case in EVAL_SET:
        out.setdefault(case.category, []).append(case)
    return out
