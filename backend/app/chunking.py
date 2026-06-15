def chunk_text(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    """Trocea texto en fragmentos de ~size caracteres con solapamiento.

    Simple y suficiente para el MVP. Más adelante se puede afinar a límites
    de frase/párrafo por vertical.
    """
    text = " ".join(text.split())  # normaliza espacios/saltos
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    step = max(1, size - overlap)
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks
