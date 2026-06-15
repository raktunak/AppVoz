from sqlalchemy import text

from .db import engine
from .embeddings import embed_texts, to_pgvector


async def retrieve(subject_id: str, query: str, k: int = 5) -> list[dict]:
    """Recupera los k fragmentos más cercanos a la consulta, aislados por
    subject_id (multitenancy). Reutilizado por /search y por el motor de voz."""
    q_emb = (await embed_texts([query], task_type="RETRIEVAL_QUERY"))[0]
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT content, round((1 - (embedding <=> CAST(:q AS vector)))::numeric, 4) AS score "
                    "FROM chunks WHERE subject_id = :s "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
                ),
                {"q": to_pgvector(q_emb), "s": subject_id, "k": k},
            )
        ).mappings().all()
    return [{"content": r["content"], "score": float(r["score"])} for r in rows]
