# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies + git (required for google-adk GitHub install)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev libssl-dev git \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Cloud Run injects PORT at runtime — default to 8080 if not set
ENV PORT=8080
ENV APP_ENV=production

# Remove local dev files not needed in production
RUN rm -f .env && \
    rm -rf scripts/ && \
    find . -name "*.pyc" -delete && \
    find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Non-root user for security
RUN adduser --disabled-password --gecos "" sentinel && \
    chown -R sentinel:sentinel /app
USER sentinel

EXPOSE 8080

# Reads $PORT at runtime so Cloud Run can dynamically assign the port
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --log-level info"]