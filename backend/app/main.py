from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from .canva4g import crear_tablas_4g
from .chunking import chunk_text
from .db import engine
from .embeddings import embed_texts, to_pgvector
from .live_relay import router as live_router
from .onboarding_4g import router as onboarding_4g_router
from .persistence import crear_tablas
from .rag import retrieve
from .telnyx_relay import router as telnyx_router
from .voice import router as voice_router


class _NoCacheStatic(StaticFiles):
    """StaticFiles que pide al navegador NO cachear (el 4g está en desarrollo activo: que cada
    recarga normal traiga el último HTML/JS sin tener que forzar Ctrl+Shift+R)."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp


app = FastAPI(title="AppVoz — Motor Tutor por Voz", version="0.5.0")
app.include_router(voice_router)
app.include_router(live_router)  # /ws/call (Gemini Live directo)
app.include_router(telnyx_router)  # /telnyx/voice (webhook) + /ws/telnyx (media-stream)
app.include_router(onboarding_4g_router)  # /ws/4g (onboarding 4G por voz → Canva → Calendar)


@app.on_event("startup")
async def _startup():
    # Tablas de la Fase 1 (sesiones, turnos, memoria_usuario); idempotente.
    await crear_tablas()
    # Tabla del Canva 4G (onboarding); idempotente.
    await crear_tablas_4g()


# ---------- Salud ----------
@app.get("/")
async def root():
    return {
        "app": "AppVoz — Motor Tutor por Voz",
        "version": app.version,
        "llamada": "/call/",
        "banco_voz": "/ui/",
        "docs": "/docs",
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


# Frontends estáticos: onboarding 4G (/4g), llamada directa (/call) y banco de voz v1 (/ui)
app.mount("/4g", _NoCacheStatic(directory="static/4g", html=True), name="4g")
app.mount("/call", StaticFiles(directory="static/live", html=True), name="call")
app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")
