# Image that executes user code. Contains common data libraries, no network access at runtime.
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy==2.1.* pandas==2.2.* scipy==1.14.* matplotlib==3.9.* \
    && useradd -u 65534 -o -M -s /usr/sbin/nologin sandbox || true
ENV MPLBACKEND=Agg MPLCONFIGDIR=/tmp
USER 65534
WORKDIR /work
