ARG BUILD_FROM
FROM ${BUILD_FROM}

# BUILD:20260209-1150

# Install build tools for numpy/scikit-learn
RUN apk add --no-cache build-base gfortran openblas-dev

# Copy application
COPY rootfs /

# Fix permissions
RUN chmod a+x /opt/mindhome/run.sh

# Install Python dependencies
RUN pip3 install --no-cache-dir -r /opt/mindhome/requirements.txt

# Remove build tools to save space
RUN apk del build-base gfortran
