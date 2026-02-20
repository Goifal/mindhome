ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install minimal system dependencies + ffmpeg for voice audio conversion
RUN apk add --no-cache \
    py3-pip \
    gcc \
    musl-dev \
    python3-dev \
    ffmpeg

# Copy and install Python requirements
COPY rootfs/opt/mindhome/requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# Remove build dependencies to save space
RUN apk del gcc musl-dev python3-dev

# Copy application files
COPY rootfs /

# Download frontend libraries locally (avoid CDN dependency at runtime)
RUN mkdir -p /opt/mindhome/static/frontend/lib \
    && wget -q -O /opt/mindhome/static/frontend/lib/react.production.min.js \
       "https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js" \
    && wget -q -O /opt/mindhome/static/frontend/lib/react-dom.production.min.js \
       "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js" \
    && wget -q -O /opt/mindhome/static/frontend/lib/babel.min.js \
       "https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.6/babel.min.js"

# Create data directories
RUN mkdir -p /data/mindhome/db \
    && mkdir -p /data/mindhome/models \
    && mkdir -p /data/mindhome/backups \
    && mkdir -p /data/mindhome/logs

# Set permissions
RUN chmod a+x /opt/mindhome/run.sh

WORKDIR /opt/mindhome

CMD ["/opt/mindhome/run.sh"]
