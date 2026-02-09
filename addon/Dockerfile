ARG BUILD_FROM
FROM ${BUILD_FROM}

# BUILD:20260209-1153

COPY rootfs /
RUN chmod a+x /opt/mindhome/run.sh
RUN pip3 install --no-cache-dir flask==3.0.0 sqlalchemy==2.0.23 requests==2.31.0 \
    websocket-client==1.7.0 python-dateutil==2.8.2 pytz==2023.3 \
    Werkzeug==3.0.1 Jinja2==3.1.2 MarkupSafe==2.1.3 pdfplumber==0.10.3
