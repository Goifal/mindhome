ARG BUILD_FROM
FROM ${BUILD_FROM}

# BUILD:20260209-1155

# Install minimal system dependencies
RUN apk add --no-cache \
    py3-pip \
    gcc \
    musl-dev \
    python3-dev \
    gfortran \
    openblas-dev

# Copy and install Python requirements
COPY rootfs/opt/mindhome/requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# Remove build dependencies to save space
RUN apk del gcc musl-dev python3-dev gfortran

# Copy application files
COPY rootfs /

# Create data directories
RUN mkdir -p /data/mindhome/db \
    && mkdir -p /data/mindhome/models \
    && mkdir -p /data/mindhome/backups \
    && mkdir -p /data/mindhome/logs

# Set permissions
RUN chmod a+x /opt/mindhome/run.sh

WORKDIR /opt/mindhome

CMD ["/opt/mindhome/run.sh"]
