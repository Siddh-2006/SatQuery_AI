# server/ (EOCaptioner) -- the one specialist model that's actually ready
# (orchestrator/DESIGN.md §4). This is the heaviest piece of the whole
# system: TerraFM + an LLM, ideally on a GPU. This image is CPU-capable
# (serve.py auto-detects cuda vs cpu) but will be slow on CPU alone --
# the whole point of this being its own container is that it CAN be run
# on a separate, more powerful machine instead (see ../docker-compose.yml
# and its EOCAPTIONER_URL env var).
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal32 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY serve.py .
COPY static ./static
# offline_model/ (the actual model weights, ~GBs) is deliberately NOT
# copied into the image -- mounted as a read-only volume instead (see
# docker-compose.yml), so this image builds fast and updating weights
# never requires a rebuild.

# EOCAPTIONER_PORT is normally set by docker-compose (from .env's port
# map, see ../orchestrator/.env.example) -- this default only matters
# standalone. Deliberately not passed as a `--port` CLI arg in CMD below:
# serve.py's own argparse default already reads this env var (see its
# `if __name__ == "__main__"` block), so leaving --port off here means one
# env var controls the port instead of two things needing to agree.
ENV MODEL_BUNDLE_DIR=/app/offline_model
ENV EOCAPTIONER_PORT=8000
EXPOSE 8000

CMD ["python", "serve.py", "--bundle", "/app/offline_model", "--host", "0.0.0.0"]
