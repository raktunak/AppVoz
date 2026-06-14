-- AppVoz — esquema inicial
-- Se ejecuta automáticamente la primera vez que arranca el contenedor db.

-- 1) Activar pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2) Tabla de chunks del corpus (RAG) con aislamiento por materia
--    embedding vector(768) = dimensión de Gemini text-embedding-004
CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    subject_id  TEXT        NOT NULL,          -- materia / tenant (multitenancy)
    content     TEXT        NOT NULL,          -- texto del fragmento
    embedding   vector(768),                   -- vector del fragmento
    metadata    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3) Índices: filtro por materia + búsqueda vectorial (HNSW, distancia coseno)
CREATE INDEX IF NOT EXISTS idx_chunks_subject   ON chunks (subject_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops);
