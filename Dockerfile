# ── Build stage ──────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./
COPY src/ src/

# Install dependencies into a virtual env
RUN uv sync --frozen --no-dev

# ── Runtime stage ────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy the virtual env and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Copy config example so users can mount their own occ.yml
COPY occ.example.yml /app/occ.example.yml

# Put the venv on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Default entrypoint
ENTRYPOINT ["occ"]
