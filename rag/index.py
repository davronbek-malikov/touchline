"""Qdrant hybrid index over Wikipedia style-of-play passages and scout notes.

Each chunk has a dense vector (BAAI/bge-small-en-v1.5) and a sparse BM25 vector;
search runs both and fuses them with reciprocal rank fusion. The player_id
filter is applied inside each prefetch, not after retrieval.
"""
import atexit
import json
import os
import re
import uuid
from functools import lru_cache
from pathlib import Path

from qdrant_client import QdrantClient, models

from data.config import RAW, ROOT

COLLECTION = "touchline_passages"
DENSE_MODEL = "BAAI/bge-small-en-v1.5"
SPARSE_MODEL = "Qdrant/bm25"
DENSE_DIM = 384
PREFETCH = 30
WIKI_DIR = RAW / "wikipedia"
_NS = uuid.UUID("6f1d3a5e-6b3c-4f0e-9a51-1c0de7a11e55")


@lru_cache(maxsize=1)
def _embedders():
    from fastembed import SparseTextEmbedding, TextEmbedding
    return TextEmbedding(DENSE_MODEL), SparseTextEmbedding(SPARSE_MODEL)


def _sparse(v) -> models.SparseVector:
    return models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())


class PassageIndex:
    def __init__(self, client: QdrantClient):
        self.client = client
        if not client.collection_exists(COLLECTION):
            client.create_collection(
                COLLECTION,
                vectors_config={"dense": models.VectorParams(size=DENSE_DIM, distance=models.Distance.COSINE)},
                sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )
            client.create_payload_index(COLLECTION, "player_id", models.PayloadSchemaType.INTEGER)

    def upsert(self, chunks: list[dict], batch: int = 64) -> int:
        dense, sparse = _embedders()
        for i in range(0, len(chunks), batch):
            part = chunks[i:i + batch]
            texts = [c["text"] for c in part]
            points = [
                models.PointStruct(id=str(uuid.uuid5(_NS, c["chunk_id"])),
                                   vector={"dense": d.tolist(), "bm25": _sparse(s)}, payload=c)
                for c, d, s in zip(part, dense.embed(texts), sparse.embed(texts))
            ]
            self.client.upsert(COLLECTION, points)
        return len(chunks)

    def search(self, query: str, player_id: int | None = None, limit: int = 5) -> list[dict]:
        dense, sparse = _embedders()
        flt = None
        if player_id is not None:
            flt = models.Filter(must=[models.FieldCondition(key="player_id", match=models.MatchValue(value=player_id))])
        res = self.client.query_points(
            COLLECTION,
            prefetch=[
                models.Prefetch(query=next(dense.query_embed(query)).tolist(), using="dense", limit=PREFETCH, filter=flt),
                models.Prefetch(query=_sparse(next(sparse.query_embed(query))), using="bm25", limit=PREFETCH, filter=flt),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
        )
        return [p.payload | {"score": round(p.score, 4)} for p in res.points]

    def count(self) -> int:
        return self.client.count(COLLECTION).count


_override: PassageIndex | None = None


def set_index(index: PassageIndex | None) -> None:
    """Point search_notes at another index (tests)."""
    global _override
    _override = index
    _default.cache_clear()


@lru_cache(maxsize=1)
def _default() -> PassageIndex:
    url = os.environ.get("QDRANT_URL")
    if url:
        client = QdrantClient(url=url, api_key=os.environ.get("QDRANT_API_KEY"))
    else:
        client = QdrantClient(path=str(Path(os.environ.get("TOUCHLINE_QDRANT_PATH", ROOT / "state" / "qdrant"))))
    atexit.register(client.close)  # local mode otherwise errors while the interpreter shuts down
    return PassageIndex(client)


def get_index() -> PassageIndex:
    return _override or _default()


# --- chunking -------------------------------------------------------------------------

MIN_WORDS, MAX_WORDS = 110, 230  # ~150-300 tokens


def chunk_text(text: str) -> list[str]:
    """Group paragraphs into ~150-300 token chunks; split long paragraphs on sentences."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    pieces = []
    for p in paras:
        if len(p.split()) <= MAX_WORDS:
            pieces.append(p)
            continue
        cur = []
        for sent in re.split(r"(?<=[.!?])\s+", p):
            if cur and len(" ".join(cur + [sent]).split()) > MAX_WORDS:
                pieces.append(" ".join(cur))
                cur = []
            cur.append(sent)
        if cur:
            pieces.append(" ".join(cur))
    chunks, cur = [], ""
    for piece in pieces:
        if cur and len((cur + " " + piece).split()) > MAX_WORDS:
            chunks.append(cur)
            cur = piece
        else:
            cur = f"{cur}\n\n{piece}".strip()
        if len(cur.split()) >= MIN_WORDS:
            chunks.append(cur)
            cur = ""
    if cur:
        if chunks and len(cur.split()) < MIN_WORDS // 2 and len((chunks[-1] + cur).split()) <= MAX_WORDS * 1.3:
            chunks[-1] = f"{chunks[-1]}\n\n{cur}"
        else:
            chunks.append(cur)
    return chunks


def wikipedia_chunks(doc: dict) -> list[dict]:
    if not doc.get("style_of_play"):
        return []
    return [{
        "chunk_id": f"wiki:{doc['tm_player_id']}:{doc['revision_id']}:{i}", "player_id": doc["tm_player_id"],
        "source": "wikipedia", "source_id": f"wiki:{doc['tm_player_id']}:{i}",
        "title": f"Wikipedia: {doc['title']} (Style of play)", "url": doc["url"], "licence": doc["licence"],
        "revision_id": doc["revision_id"], "text": text,
    } for i, text in enumerate(chunk_text(doc["style_of_play"]))]


def load_wikipedia_chunks(wiki_dir: Path = WIKI_DIR) -> list[dict]:
    chunks = []
    for path in sorted(wiki_dir.glob("*.json")):
        chunks += wikipedia_chunks(json.loads(path.read_text(encoding="utf-8")))
    return chunks
