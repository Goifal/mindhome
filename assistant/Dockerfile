FROM python:3.12-slim

WORKDIR /app

# System-Dependencies (inkl. Tesseract OCR fuer Phase 14.2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI + Compose Plugin (fuer System-Management aus dem Dashboard)
RUN ARCH=$(uname -m) && \
    curl -fsSL "https://download.docker.com/linux/static/stable/${ARCH}/docker-27.5.1.tgz" \
    | tar xz --strip-components=1 -C /usr/local/bin docker/docker && \
    mkdir -p /usr/local/lib/docker/cli-plugins && \
    curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-${ARCH}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose && \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Python-Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# MindHome Assistant Code
COPY assistant/ ./assistant/
COPY config/ ./config/
COPY static/ ./static/

# Port
EXPOSE 8200

# Health Check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8200/api/assistant/health || exit 1

# Start
CMD ["python", "-m", "assistant.main"]
