FROM python:3.12-slim

LABEL org.opencontainers.image.title="favtracks"
LABEL org.opencontainers.image.description="Visualize frequently used GPS activity segments"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (UID 1000 for bind-mount compatibility)
RUN groupadd -r -g 1000 appuser && useradd -r -u 1000 -g appuser -s /bin/false appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY templates/ ./templates/
COPY static/ ./static/
COPY __main__.py .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/data"]

USER appuser

EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]
