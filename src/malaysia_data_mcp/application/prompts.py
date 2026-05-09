"""MCP Prompts — reusable parameterised templates the host surfaces as slash commands.

Why prompts (interview talking point): the MCP spec defines three primitives —
Tools (POST-like, side effects), Resources (GET-like, addressable), and Prompts
(templated user-facing instructions). Most MCP servers ship only tools. Adding
prompts and resources signals you understand the full protocol surface, not
just the tool subset.

When a user types `/economic-briefing` in Claude Desktop, the host fetches the
prompt template from this server, fills in args, and sends as the user message.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptTemplate:
    name: str
    description: str
    arguments: list[dict[str, str]]
    template: str


ECONOMIC_BRIEFING = PromptTemplate(
    name="economic_briefing",
    description="Generate a Malaysia economic briefing using live BNM and DOSM data.",
    arguments=[
        {
            "name": "audience",
            "description": "Who's the briefing for? e.g. 'investor', 'policy researcher', 'general public'",
            "required": "false",
        },
    ],
    template="""Use the get_malaysia_economic_snapshot tool to fetch current data, \
then write a 4-paragraph briefing for {audience} covering:

1. Monetary stance (OPR + recent change context)
2. External position (USD/MYR rate, gold)
3. Cost of living (fuel prices, latest CPI)
4. One forward-looking observation a {audience} would care about

Use ONLY the data returned by the tool. Cite the BNM and data.gov.my sources \
inline. Avoid speculation about future rate decisions.""",
)


SCAM_CHECK = PromptTemplate(
    name="scam_check",
    description="Check whether a financial entity is on Bank Negara's unauthorised list.",
    arguments=[
        {
            "name": "entity_name",
            "description": "Company or platform name to check.",
            "required": "true",
        },
    ],
    template="""Run the check_consumer_alert tool with entity_name='{entity_name}'. \
Then summarise the result in plain language for a layperson:

- If found: clearly state it's on BNM's unauthorised list and give the date \
it was added. Tell the user not to transact with the entity and provide \
BNM's reporting hotline (+603-2174-1717).
- If not found: emphasise that absence from the list is NOT proof of \
authorisation. Recommend the user verify directly with BNM at \
bnm.gov.my/financial-consumer-alert-list before any transaction.

Always include the tool's `warning` field verbatim.""",
)


CURRENCY_PLANNER = PromptTemplate(
    name="currency_planner",
    description="Plan a foreign currency conversion using BNM rates.",
    arguments=[
        {
            "name": "currency",
            "description": "ISO code of the foreign currency (e.g. 'USD', 'SGD').",
            "required": "true",
        },
        {
            "name": "amount_myr",
            "description": "MYR amount to convert.",
            "required": "true",
        },
    ],
    template="""Use get_exchange_rates with currency='{currency}' and \
get_usd_myr_reference_rate. Then for an amount of MYR {amount_myr}:

1. State today's BNM middle rate for {currency}.
2. Calculate the amount the user would receive at: a) middle, b) buying, \
c) selling rates. Explain why these differ (bank spreads).
3. Note the rate's effective date and warn that real bank rates will be \
worse than BNM's interbank rate.""",
)


ALL_PROMPTS = [ECONOMIC_BRIEFING, SCAM_CHECK, CURRENCY_PLANNER]
