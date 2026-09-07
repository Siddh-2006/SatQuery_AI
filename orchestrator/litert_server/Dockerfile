# litert_server -- the local Gemma model, wrapped as a tiny HTTP service.
# CPU-only image: LiteRT-LM (see gemma_models/inference.py) is XNNPACK/CPU
# oriented, no GPU needed. Heavy part isn't the image, it's the model file
# itself (2.5GB) -- mounted as a volume (see ../../docker-compose.yml)
# rather than baked into the image, so rebuilding this image is fast and
# swapping model files never requires a rebuild.
FROM python:3.11-slim

WORKDIR /app

# rasterio/pyproj aren't needed here, but litert_lm's own native deps
# sometimes need basic build tools present -- kept minimal on purpose.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# MODEL_PATH is overridden by docker-compose.yml to point at the mounted
# model volume; the default here only matters for a bare `docker run`.
# LITERT_SERVER_PORT is also normally set by docker-compose (from .env's
# port map, see ../.env.example) -- this default only matters standalone.
ENV MODEL_PATH=/models/gemma-4-E2B-it.litertlm
ENV LITERT_SERVER_PORT=9001
EXPOSE 9001

CMD ["python", "server.py"]
