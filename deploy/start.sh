#!/bin/sh
# Seed the persistent volume with the passage index on first boot, then serve.
set -e
mkdir -p "$TOUCHLINE_STATE" "$TOUCHLINE_QDRANT_PATH"
if [ ! -d "$TOUCHLINE_QDRANT_PATH/collection" ]; then
  echo "seeding passage index into $TOUCHLINE_QDRANT_PATH"
  cp -r /app/seed/qdrant/. "$TOUCHLINE_QDRANT_PATH/"
fi
# One worker: the embedded Qdrant index and the in-memory spend caps live in this process.
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
