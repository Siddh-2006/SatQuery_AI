# orchestrator -- the FastAPI + LangChain brain. Deliberately light: no
# GPU, no giant model files baked in (those are the eocaptioner and
# llm-litert services' job, see ../docker-compose.yml). Plain
# python:3.11-slim, nothing exotic.
FROM python:3.11-slim

WORKDIR /orchestrator

# rasterio needs GDAL's runtime libraries present -- installed via apt
# rather than compiled from source, matching how rasterio's own wheels
# expect to find them at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal32 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the actual application code. gemma_models/ (the model file itself)
# is deliberately NOT copied here -- that belongs to litert_server, mounted
# as its own volume; this image never needs to be 2.5GB.
COPY app ./app
COPY tools ./tools
COPY data ./data
COPY storage ./storage
COPY system_prompts ./system_prompts
COPY gemma4_orchestrator_instructions.md .

ENV ORCHESTRATOR_PORT=8080
EXPOSE 8080

CMD ["python", "-m", "app.main"]
