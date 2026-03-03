# Quantum Protocol — Unified Python Engine + Dashboard
# Replaces Dockerfile.engine (Rust) and Dockerfile.platform (Python dashboard only)
FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r quantum && useradd -r -g quantum -d /app quantum
RUN mkdir -p /var/log/quantum && chown quantum:quantum /var/log/quantum

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY brain/ brain/
COPY src/ src/
COPY config/ config/

# Environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Ports: 8000 = FastAPI dashboard, 8501 = Streamlit dashboard
EXPOSE 8000
EXPOSE 8501

USER quantum

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Default: run the async engine (FastAPI dashboard served alongside)
CMD ["python", "-m", "brain.engine"]
