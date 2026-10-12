FROM lscr.io/linuxserver/weixin:latest
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3-gi gir1.2-atspi-2.0 at-spi2-core libxtst6 && rm -rf /var/lib/apt/lists/*
COPY service /custom-services.d/wechat-lite
COPY admin-service /custom-services.d/wechat-admin
RUN chmod 755 /custom-services.d/wechat-lite /custom-services.d/wechat-admin
