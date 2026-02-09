ARG BUILD_FROM
FROM ${BUILD_FROM}

# BUILD:20260209-1110

# Install system dependencies for pdfplumber
RUN apk add --no-cache \
    build-base \
    libffi-dev

# Copy application
COPY rootfs /

# Make run.sh executable
RUN chmod a+x /opt/mindhome/run.sh

# Install Python dependencies
RUN pip3 install --no-cache-dir -r /opt/mindhome/requirements.txt

# Cleanup build deps to save space
RUN apk del build-base libffi-dev

WORKDIR /opt/mindhome
