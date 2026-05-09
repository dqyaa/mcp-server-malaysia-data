# Runbook

Operational guide for running this server in production.

## Smoke test after deploy

```bash
curl -fsS http://localhost:8000/healthz                                 # process alive
curl -fsS http://localhost:8000/readyz | jq                             # upstream healthy
curl -fsS http://localhost:8000/v1/opr | jq                             # tool returns data
curl -fsS http://localhost:8000/metrics | grep malaysia_data_tool_calls # metrics flowing
```

If `/readyz` returns 503, check:
1. Outbound network access from container/VM (BNM and data.gov.my reachable?).
2. Logs for `upstream_*` events.
3. Whether the circuit breaker is open: `malaysia_data_circuit_state` metric.

## Common incidents

### Symptom: tool error rate spiking

1. Check `malaysia_data_upstream_requests_total` by status. 5xx spike → BNM/DOSM
   degraded; circuit will open shortly. Wait for recovery; no action needed
   on our side.
2. If 4xx — likely upstream API contract drift. Check the daily contract
   workflow result; cross-reference with our `application/tools.py` parsing.

### Symptom: latency spike

1. Cache hit rate dropping → check `malaysia_data_cache_operations_total`.
   If L1 hit rate dropped after a deploy, a cold cache is warming. Should
   recover within minutes.
2. Upstream latency increased → check `malaysia_data_upstream_request_duration_seconds`
   p95 by upstream. BNM occasionally has slow days.
3. Rate limiting? aiolimiter throttling kicks in if QPS exceeds configured
   limit. Adjust `MALAYSIA_DATA_BNM_RATE_LIMIT_PER_MINUTE` if needed.

### Symptom: Redis connection errors

The L2 cache is optional. Errors degrade performance but don't break correctness.
Check Redis is reachable and `MALAYSIA_DATA_CACHE_REDIS_URL` is correct.

## Upstream API change response

When the daily `Upstream Contract Check` workflow opens an issue:

1. Read the failed test to identify which endpoint/field changed.
2. Verify with a manual `curl` call against the upstream.
3. Update the parsing in `infrastructure/clients/bnm.py` or `datagovmy.py`.
4. Update the test fixture in `tests/unit/test_tools.py`.
5. Add a regression test for the specific drift.
6. Deploy.

## Scaling

- Single instance: handles thousands of requests/min easily (most are cache hits).
- Multi-instance: enable Redis (set `CACHE_REDIS_URL`) so cache state is shared.
- For higher load, raise `cache_l1_max_size` and `cache_default_ttl_seconds`.
- BNM and data.gov.my are public APIs — be a good citizen. Keep
  `bnm_rate_limit_per_minute` ≤ 60 unless you know what you're doing.

## Rollback

```bash
docker compose -f deploy/docker-compose.yml down
docker tag malaysia-data-mcp:0.1.0 malaysia-data-mcp:rollback
docker compose -f deploy/docker-compose.yml up -d
```

State is in cache (ephemeral) and Redis (durable but TTL'd). No DB migrations
to roll back.
