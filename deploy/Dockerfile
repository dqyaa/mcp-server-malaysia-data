# =============================================================================
# Multi-stage Dockerfile for malaysia-data-mcp
#
# Stage 1 (builder): installs build deps + project, generates wheel
# Stage 2 (runtime): slim Python, only runtime deps, non-root user
#
# Final image is ~150MB (vs ~800MB if we used a single python:3.12 base).
# Multi-stage is the production standard — build artifacts don't leak into
# runtime, attack surface stays minimal.
# =============================================================================

# ---- Stage 1: builder ----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for hiredis, cryptography, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src

# Install project + redis extra. We do NOT install [dev], [agent] in the image.
RUN pip install --upgrade pip && \
    pip install --target=/install ".[redis]"

# ---- Stage 2: runtime ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

# Create non-root user — running as root in containers is a CVE waiting to happen.
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

# tini for proper PID 1 signal handling (Ctrl-C, k8s SIGTERM).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder (no compilers in runtime!).
COPY --from=builder /install /usr/local/lib/python3.12/site-packages
COPY --from=builder /build/src /app/src

# Drop privileges.
RUN chown -R app:app /app
USER app

# Health check — fails container if /healthz doesn't respond.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# Default to REST server (port 8000). Override CMD to run MCP stdio mode:
#   docker run ... python -m malaysia_data_mcp.presentation.mcp_server
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "malaysia_data_mcp.presentation.http_server"]
