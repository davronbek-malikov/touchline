"""Qdrant index over Wikipedia style-of-play passages and scout notes.

Hybrid by default: each chunk has a dense vector (BAAI/bge-small-en-v1.5) and a
sparse BM25 vector, and search fuses both with reciprocal rank fusion. With
TOUCHLINE_SEARCH=bm25 the dense model is never loaded (about 200 MB less memory,
for 512 MB hosts) and search is keyword-only. The player_id filter is applied
inside each prefetch, not after retrieval.

Where the index lives:
  QDRANT_URL set           Qdrant server or cloud
  TOUCHLINE_INDEX=memory   in-process, rebuilt at startup from TOUCHLINE_PASSAGES
                           (a JSONL of Wikipedia chunks) plus saved scout notes
  otherwise                local files under state/qdrant
"""
import atexit
import json
import os
import re
import uuid
import warnings
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


def dense_enabled() -> bool:
    return os.environ.get("TOUCHLINE_SEARCH", "hybrid").lower() != "bm25"


@lru_cache(maxsize=1)
def _dense_model():
    from fastembed import TextEmbedding
    return TextEmbedding(DENSE_MODEL)


@lru_cache(maxsize=1)
def _sparse_model():
    from fastembed import SparseTextEmbedding
    return SparseTextEmbedding(SPARSE_MODEL)


def _embedders():
    """Both models (build-time warm-up and hybrid mode)."""
    return _dense_model(), _sparse_model()


def _sparse(v) -> models.SparseVector:
    return models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())


class PassageIndex:
    def __init__(self, client: QdrantClient, dense: bool | None = None):
        self.client = client
        self.dense = dense_enabled() if dense is None else dense
        if not client.collection_exists(COLLECTION):
            client.create_collection(
                COLLECTION,
                vectors_config={"dense": models.VectorParams(size=DENSE_DIM, distance=models.Distance.COSINE)}
                if self.dense else {},
                sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )
            with warnings.catch_warnings():  # local mode ignores payload indexes and warns; servers need one
                warnings.simplefilter("ignore", UserWarning)
                client.create_payload_index(COLLECTION, "player_id", models.PayloadSchemaType.INTEGER)

    def upsert(self, chunks: list[dict], batch: int = 64) -> int:
        sparse = _sparse_model()
        for i in range(0, len(chunks), batch):
            part = chunks[i:i + batch]
            texts = [c["text"] for c in part]
            dense_vecs = list(_dense_model().embed(texts)) if self.dense else [None] * len(part)
            points = []
            for c, d, s in zip(part, dense_vecs, sparse.embed(texts)):
                vec = {"bm25": _sparse(s)}
                if d is not None:
                    vec["dense"] = d.tolist()
                points.append(models.PointStruct(id=str(uuid.uuid5(_NS, c["chunk_id"])), vector=vec, payload=c))
            self.client.upsert(COLLECTION, points)
        return len(chunks)

    def search(self, query: str, player_id: int | None = None, limit: int = 5) -> list[dict]:
        flt = None
        if player_id is not None:
            flt = models.Filter(must=[models.FieldCondition(key="player_id", match=models.MatchValue(value=player_id))])
        prefetch = [models.Prefetch(query=_sparse(next(_sparse_model().query_embed(query))), using="bm25",
                                    limit=PREFETCH, filter=flt)]
        if self.dense:
            prefetch.insert(0, models.Prefetch(query=next(_dense_model().query_embed(query)).tolist(), using="dense",
                                               limit=PREFETCH, filter=flt))
        res = self.client.query_points(COLLECTION, prefetch=prefetch,
                                       query=models.FusionQuery(fusion=models.Fusion.RRF), limit=limit)
        return [p.payload | {"score": round(p.score, 4)} for p in res.points]

    def count(self) -> int:
        return self.client.count(COLLECTION).count


_override: PassageIndex | None = None


def set_index(index: PassageIndex | None) -> None:
    """Point search_notes at another index (tests)."""
    global _override
    _override = index
    _default.cache_clear()


def load_passages_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@lru_cache(maxsize=1)
def _default() -> PassageIndex:
    url = os.environ.get("QDRANT_URL")
    if url:
        return PassageIndex(QdrantClient(url=url, api_key=os.environ.get("QDRANT_API_KEY")))
    if os.environ.get("TOUCHLINE_INDEX") == "memory":
        from rag.notes import list_notes, note_chunks

        index = PassageIndex(QdrantClient(":memory:"))
        passages = Path(os.environ.get("TOUCHLINE_PASSAGES", ROOT / "deploy" / "seed" / "passages.jsonl"))
        index.upsert((load_passages_jsonl(passages) if passages.exists() else []) + note_chunks(list_notes()))
        return index
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
