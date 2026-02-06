ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-numpy \
    py3-scipy \
    nodejs \
    npm \
    gcc \
    musl-dev \
    python3-dev \
    linux-headers

# Copy and install Python requirements
COPY rootfs/opt/mindhome/requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

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
