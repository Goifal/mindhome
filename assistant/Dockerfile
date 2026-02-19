FROM python:3.12-slim

WORKDIR /app

# System-Dependencies (inkl. Tesseract OCR fuer Phase 14.2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Python-Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# MindHome Assistant Code
COPY assistant/ ./assistant/
COPY config/ ./config/

# Port
EXPOSE 8200

# Health Check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8200/api/assistant/health || exit 1

# Start
CMD ["python", "-m", "assistant.main"]
