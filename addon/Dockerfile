ARG BUILD_FROM
FROM ${BUILD_FROM}

# BUILD:20260209-1145

# Copy application
COPY rootfs /

# Fix permissions
RUN chmod a+x /opt/mindhome/run.sh

# Install Python dependencies
RUN pip3 install --no-cache-dir -r /opt/mindhome/requirements.txt
