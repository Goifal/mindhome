ARG BUILD_FROM
FROM ${BUILD_FROM}

# BUILD:20260209-1115

# Install system dependencies for pdfplumber
RUN apk add --no-cache \
    build-base \
    libffi-dev

# Copy application
COPY rootfs /

# Fix permissions (Git may strip execute bit)
RUN chmod -R a+x /opt/mindhome/run.sh && \
    find /opt/mindhome -name "*.sh" -exec chmod a+x {} \; && \
    find /opt/mindhome -name "*.py" -exec chmod a+r {} \;

# Install Python dependencies
RUN pip3 install --no-cache-dir -r /opt/mindhome/requirements.txt

# Cleanup build deps to save space
RUN apk del build-base libffi-dev

WORKDIR /opt/mindhome
