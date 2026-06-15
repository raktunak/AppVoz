from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import text

from .chunking import chunk_text
from .db import engine
from .embeddings import embed_texts, to_pgvector

app = FastAPI(title="AppVoz — Motor Tutor por Voz", version="0.2.0")


# ---------- Salud ----------
@app.get("/")
async def root():
    """Info básica del servicio."""
    return {
        "app": "AppVoz — Motor Tutor por Voz",
        "version": app.version,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/db")
async def health_db():
    async with engine.connect() as conn:
        version = (
            await conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
        ).scalar()
        n_chunks = (await conn.execute(text("SELECT count(*) FROM chunks"))).scalar()
    return {"postgres": "ok", "pgvector": version or "NO INSTALADO", "chunks": n_chunks}


# ---------- RAG ----------
class IngestRequest(BaseModel):
    subject_id: str = Field(..., description="Materia / tenant del corpus")
    content: str = Field(..., description="Texto a ingerir")


class SearchRequest(BaseModel):
    subject_id: str
    query: str
    k: int = Field(5, ge=1, le=20)


@app.post("/ingest")
async def ingest(req: IngestRequest):
    """Trocea el texto, genera embeddings y los guarda por subject_id."""
    chunks = chunk_text(req.content)
    if not chunks:
        return {"subject_id": req.subject_id, "chunks_inserted": 0}

    embeddings = await embed_texts(chunks, task_type="RETRIEVAL_DOCUMENT")
    async with engine.begin() as conn:
        for content, emb in zip(chunks, embeddings):
            await conn.execute(
                text(
                    "INSERT INTO chunks (subject_id, content, embedding) "
                    "VALUES (:s, :c, CAST(:e AS vector))"
                ),
                {"s": req.subject_id, "c": content, "e": to_pgvector(emb)},
            )
    return {"subject_id": req.subject_id, "chunks_inserted": len(chunks)}


@app.post("/search")
async def search(req: SearchRequest):
    """Búsqueda semántica: recupera los fragmentos más cercanos a la consulta,
    aislados por subject_id (multitenancy)."""
    q_emb = (await embed_texts([req.query], task_type="RETRIEVAL_QUERY"))[0]
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT content, round((1 - (embedding <=> CAST(:q AS vector)))::numeric, 4) AS score "
                    "FROM chunks WHERE subject_id = :s "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
                ),
                {"q": to_pgvector(q_emb), "s": req.subject_id, "k": req.k},
            )
        ).mappings().all()
    return {
        "query": req.query,
        "subject_id": req.subject_id,
        "results": [{"content": r["content"], "score": float(r["score"])} for r in rows],
    }
