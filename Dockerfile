# ai-hub — read-only autonomous agent (DEX monitoring, research, self-healing)
# Python 3.10-slim base, matches local dev env.
# Ollama runs as an EXTERNAL service (see docker-compose.yml).

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

# Minimal system deps: TLS certs + curl (compose healthcheck) + procps (pgrep)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl procps \
 && rm -rf /var/lib/apt/lists/*

# Non-root user (UID 1000 — совпадает с типичным host-user на macOS)
RUN useradd -m -u 1000 -s /bin/bash aihub
WORKDIR /app

# Python deps first (Docker cache layer)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (.dockerignore filters out archive/, .git/, HANDOFF-*, etc.)
COPY --chown=aihub:aihub . .

# Runtime dirs the agent writes to (self/curator, knowledge/, .cache)
RUN mkdir -p self/curator knowledge logs .cache \
 && chown -R aihub:aihub /app

USER aihub

# Healthcheck: self_daemon alive (pgrep reads its own cmdline prefix)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD pgrep -f "self_daemon.py" > /dev/null || exit 1

# Default: autonomous self-daemon (agent_daemon overridden in compose)
ENTRYPOINT ["python3", "scripts/research/self_daemon.py"]
