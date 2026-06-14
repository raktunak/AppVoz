# AppVoz — Motor Tutor por Voz

Tutor por voz en tiempo real que enseña **desde el material del dueño del producto** (RAG): el alumno habla → se recupera el fragmento del temario → un LLM responde → se devuelve hablado.

App **nueva e independiente**. Solo reutiliza las APIs de Google Cloud (Gemini/Vertex, STT/TTS) del proyecto `brainrot-walloop`. Su base de datos es propia (contenedor pgvector local).

## Stack
- **Backend:** FastAPI (Python 3.12)
- **Datos + RAG:** PostgreSQL 15 + **pgvector** (HNSW, distancia coseno)
- **IA:** Gemini (Vertex AI) · STT/TTS de Google · *(voz con Pipecat — fase siguiente)*

## Estructura
```
AppVoz/
├── docker-compose.yml      # db (pgvector) + api (FastAPI)
├── db/init/01_init.sql     # CREATE EXTENSION vector + tabla chunks
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── config.py       # settings desde .env
│       ├── db.py           # engine async + pgvector
│       └── main.py         # /health y /health/db
├── .env                    # secretos (gitignored)
└── .env.example
```

## Arrancar (desarrollo)
```bash
docker compose up -d --build
```
Comprobar:
- API viva: http://localhost:8080/health
- DB + pgvector: http://localhost:8080/health/db
- Docs: http://localhost:8080/docs

Postgres queda expuesto en `localhost:5434` (usuario/clave/db = `appvoz`).

## Próximas fases
1. Ingesta de corpus por `subject_id` (chunking + embeddings con Gemini).
2. Retrieval RAG con filtro `subject_id`.
3. Pipeline de voz en cascada (STT→LLM→TTS) sobre WebSocket con Pipecat.
