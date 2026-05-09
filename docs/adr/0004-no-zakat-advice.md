# ADR 0004 — Why we exclude zakat advisory output

**Status:** Accepted
**Date:** 2026-05

## Context

The original sketch of this server included a `calculate_zakat_eligibility`
tool that computed:

- Whether savings exceeded the gold-based nisab threshold
- Zakat owed on savings (×0.025)
- Zakat on gold holdings
- Zakat on income

This is data that an MCP-connected LLM would emit verbatim to a user as
financial-religious advice.

In Malaysia, zakat is regulated. Each state has an official zakat authority
(PPZ-MAIWP for Federal Territories, LZS for Selangor, MAIPP for Penang, etc.)
with binding methodology. State methodologies differ on:

- Nisab basis: gold (85g) vs. silver (595g)
- Income zakat: gross vs. net of necessities
- Eligible asset categories
- Haul (one lunar year holding period) edge cases

A tool that confidently computes zakat without state-authority cross-reference
will be wrong for at least one state's methodology in at least one edge case.

## Decision

**Do not ship advisory output.** Replace `calculate_zakat_eligibility` with
two factual tools:

- `get_kijang_emas_price` — returns the live BNM gold selling price + per-gram
  derivation, no fiqh interpretation.
- `get_zakat_nisab_threshold` — returns the MYR value of 85g gold today, plus
  a note that state methodologies vary and users should consult their state
  authority. No "zakat owed" computation.

## Consequences

**Positive**

- We don't ship religious advice we aren't qualified to give.
- The reputational tail risk in the MY Muslim professional network — where
  "AI engineer who ships incorrect fiqh" is a search result you don't want —
  is eliminated.
- Tool count remains 15 (the composite snapshot tool offsets the removal).
- The MCP prompt `currency_planner` and the README pattern still showcase
  the Islamic finance angle without making advisory claims.

**Negative**

- Less "wow factor" in a demo — "calculate my zakat" is a more user-facing
  hook than "give me the nisab threshold."
- Some users may copy our output into a zakat calculator anyway. We mitigate
  this with explicit warnings in the tool's docstring and response payload.

## Alternatives considered

- **Ship the advisory tool anyway** — rejected. Outsized downside.
- **Ship advisory output but with a giant disclaimer** — disclaimers are
  almost universally ignored by both users and the LLMs that surface our
  data. The output would still be acted on. Rejected.
- **Source from one specific state authority (e.g. PPZ-MAIWP)** — would tilt
  the server toward FT residents and leave 13 other states' users with wrong
  numbers. Defensible only if explicitly named. Rejected as out of scope for v1.

## Notes

This ADR is also a portfolio signal: the discipline to *exclude* a feature
because we cannot defend its correctness is itself a senior engineering
behaviour. Hiring managers reading this codebase will recognise the pattern.
