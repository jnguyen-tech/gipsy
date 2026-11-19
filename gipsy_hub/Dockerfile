# Gipsy Hub in a container.
# Ollama is NOT in here: it runs natively on Windows so it gets the GPU, and
# the hub reaches it at http://host.docker.internal:11434.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GIPSY_IN_DOCKER=1 \
    GIPSY_DATA_DIR=/data \
    GIPSY_OLLAMA_URL=http://host.docker.internal:11434 \
    HF_HOME=/models/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# Install the Python packages first so code changes don't redo this slow step.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./
COPY knowledge ./knowledge

# Run as a normal user, not root.
RUN useradd --create-home --uid 1000 gipsy \
 && mkdir -p /data /models \
 && chown -R gipsy:gipsy /app /data /models
USER gipsy

# /data   config.json, Piper voices, hub.log (keep it between updates)
# /models Whisper model cache
VOLUME ["/data", "/models"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4)"

CMD ["python", "gipsy_hub.py"]
