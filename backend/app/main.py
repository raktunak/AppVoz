from fastapi import FastAPI
from sqlalchemy import text

from .db import engine

app = FastAPI(title="AppVoz — Motor Tutor por Voz", version="0.1.0")


@app.get("/health")
async def health():
    """Liveness: la API responde."""
    return {"status": "ok"}


@app.get("/health/db")
async def health_db():
    """Readiness: la DB responde y pgvector está activo."""
    async with engine.connect() as conn:
        version = (
            await conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
        ).scalar()
        n_chunks = (await conn.execute(text("SELECT count(*) FROM chunks"))).scalar()
    return {
        "postgres": "ok",
        "pgvector": version or "NO INSTALADO",
        "chunks": n_chunks,
    }
