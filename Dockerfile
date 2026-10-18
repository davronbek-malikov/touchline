# Touchline API: FastAPI + LangGraph agent, DuckDB warehouse and Qdrant index baked in.
# Build context is assembled by `railway up --no-gitignore`; .railwayignore decides what's uploaded.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/app/models \
    TOUCHLINE_STATE=/data \
    TOUCHLINE_QDRANT_PATH=/data/qdrant \
    TOUCHLINE_NOTES_DB=/data/notes.sqlite \
    TRUSTED_PROXY_HOPS=1

WORKDIR /app

COPY deploy/requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY agent agent
COPY api api
COPY data data
COPY eval eval
COPY rag rag
COPY warehouse/touchline.duckdb warehouse/touchline.duckdb
COPY deploy/seed/qdrant seed/qdrant
COPY deploy/start.sh start.sh

# Download the embedding models at build time so startup needs no network.
RUN python -c "from rag.index import _embedders; _embedders()"

EXPOSE 8000
CMD ["sh", "start.sh"]
