from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from .chunking import chunk_text
from .db import engine
from .embeddings import embed_texts, to_pgvector
from .rag import retrieve
from .voice import router as voice_router

app = FastAPI(title="AppVoz — Motor Tutor por Voz", version="0.3.0")
app.include_router(voice_router)


# ---------- Salud ----------
@app.get("/")
async def root():
    return {
        "app": "AppVoz — Motor Tutor por Voz",
        "version": app.version,
        "banco_de_voz": "/ui/",
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
    results = await retrieve(req.subject_id, req.query, req.k)
    return {"query": req.query, "subject_id": req.subject_id, "results": results}


# El banco de pruebas de voz (estáticos). Se monta al final para no tapar la API.
app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")
