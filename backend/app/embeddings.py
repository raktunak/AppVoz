import asyncio

from google import genai
from google.genai import types

from .config import settings

_client = genai.Client(api_key=settings.google_api_key)


def _embed_sync(texts: list[str], task_type: str) -> list[list[float]]:
    resp = _client.models.embed_content(
        model=settings.embedding_model,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=settings.embedding_dim,
        ),
    )
    return [e.values for e in resp.embeddings]


async def embed_texts(
    texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT"
) -> list[list[float]]:
    """Genera embeddings con Gemini. task_type:
    - RETRIEVAL_DOCUMENT al ingerir el corpus
    - RETRIEVAL_QUERY al buscar
    """
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, texts, task_type)


def to_pgvector(values: list[float]) -> str:
    """Formatea un vector como literal para castear a tipo `vector` en SQL."""
    return "[" + ",".join(f"{x:.6f}" for x in values) + "]"
