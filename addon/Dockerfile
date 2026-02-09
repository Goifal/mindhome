ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install system dependencies for pdfplumber (needs C compiler for pdfminer)
RUN apk add --no-cache \
    build-base \
    libffi-dev

# Copy application
COPY rootfs /

# Install Python dependencies
RUN pip3 install --no-cache-dir -r /opt/mindhome/requirements.txt

# Cleanup build deps to save space
RUN apk del build-base libffi-dev

# Set working directory
WORKDIR /opt/mindhome

# Start script
CMD [ "/opt/mindhome/run.sh" ]
