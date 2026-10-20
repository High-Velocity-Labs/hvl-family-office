FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    LOCAL_MODE=1 \
    FAMILY_OFFICE_DATA_DIR=/app/data \
    PORT=5050

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies + bundled hvl_common first for layer caching
COPY requirements.txt ./
COPY vendor ./vendor
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure non-root runtime user and writable persistent data volume
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/data /app/.mm && \
    chown -R appuser:appuser /app

USER appuser

VOLUME ["/app/data"]
EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5050/api/health || exit 1

CMD ["gunicorn", "--workers", "2", "--threads", "4", "--timeout", "120", "--bind", "0.0.0.0:5050", "wsgi:app"]
