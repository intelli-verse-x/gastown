FROM python:3.12-slim

WORKDIR /opt/content-factory-wiring

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY services/postiz_webhook/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt

# App
COPY tools/ tools/
COPY services/ services/
COPY hermes/ hermes/

EXPOSE 8421

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8421/healthz || exit 1

ENV PYTHONPATH=/opt/content-factory-wiring

CMD ["uvicorn", "services.postiz_webhook.server:app", \
     "--host", "0.0.0.0", "--port", "8421", "--workers", "2"]
