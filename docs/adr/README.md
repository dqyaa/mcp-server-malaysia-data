# Architecture Decision Records

ADRs document non-trivial decisions taken in this codebase. Each ADR captures:

- **Context** — what forces drove the decision
- **Decision** — what we picked
- **Consequences** — what follows (good and bad)
- **Alternatives** — what we considered and rejected

We use ADRs because anyone reading the code six months from now (a future
collaborator, a hiring manager, a code-review interviewer) deserves to know
*why* the codebase looks the way it does, not just *what* it does.

Format: [Michael Nygard's template](https://github.com/joelparkerhenderson/architecture-decision-record/blob/main/locales/en/templates/decision-record-template-by-michael-nygard/index.md).

## Index

- [0001 — FastMCP over the raw MCP SDK](./0001-fastmcp-over-raw-sdk.md)
- [0002 — Two-tier cache (memory + optional Redis)](./0002-two-tier-cache.md)
- [0003 — Circuit breaker for upstream APIs](./0003-circuit-breaker.md)
- [0004 — Why we exclude zakat advisory output](./0004-no-zakat-advice.md)
- [0005 — Dual transport: MCP and REST](./0005-dual-transport.md)
- [0006 — Pydantic v2 throughout](./0006-pydantic-v2.md)
- [0007 — Hexagonal architecture](./0007-hexagonal-architecture.md)
