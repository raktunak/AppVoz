"""Persistencia de la Fase 1: sesiones, turnos y memoria por usuario.

Guarda CADA conversación (sea cual sea la vía de voz) y sus turnos con la
instrumentación de latencia, y mantiene una memoria acumulada por (user_id,
subject_id) que se actualiza al cerrar cada sesión con un resumen generado por
Gemini Flash.

Sigue el mismo patrón de la capa de datos del proyecto: SQLAlchemy 2.0 async +
asyncpg, SQL crudo vía `text()`, acceso por `engine` (`async with
engine.begin()` para escrituras transaccionales, `engine.connect()` para
lecturas). Ver `main.py` (/ingest, DDL de startup) y `rag.py`.
"""
import asyncio
import json

from google import genai
from google.genai import types
from loguru import logger
from sqlalchemy import text

from .config import settings
from .db import engine

# Cliente Gemini (Developer API por API key) para el resumen best-effort.
# Mismo patrón que embeddings.py: cliente a nivel de módulo.
_client = genai.Client(api_key=settings.google_api_key)

# Modelo para resumir la sesión. Flash: barato y suficiente para esta tarea.
RESUMEN_MODEL = "gemini-2.5-flash"


# --------------------------------------------------------------------------- #
# DDL — idempotente (CREATE ... IF NOT EXISTS). Se llama en el startup de la app.
# --------------------------------------------------------------------------- #
_DDL = [
    # Una fila por conversación (independiente de la vía de voz).
    """
    CREATE TABLE IF NOT EXISTS sesiones (
        id          BIGSERIAL PRIMARY KEY,
        subject_id  TEXT NOT NULL,
        user_id     TEXT NOT NULL DEFAULT 'anonimo',
        via         TEXT NOT NULL,
        etiqueta    TEXT,
        started_at  TIMESTAMPTZ DEFAULT now(),
        ended_at    TIMESTAMPTZ,
        n_turnos    INT NOT NULL DEFAULT 0
    )
    """,
    # Un turno = un intercambio (lo dicho por el usuario + respuesta del bot) con
    # su instrumentación de latencia. chunks: fragmentos RAG usados para anclar.
    """
    CREATE TABLE IF NOT EXISTS turnos (
        id            BIGSERIAL PRIMARY KEY,
        session_id    BIGINT NOT NULL REFERENCES sesiones(id) ON DELETE CASCADE,
        idx           INT NOT NULL,
        user_text     TEXT,
        bot_text      TEXT,
        grounded      BOOLEAN,
        chunks        JSONB NOT NULL DEFAULT '[]',
        stt_ms        INT,
        retrieval_ms  INT,
        llm_ttft_ms   INT,
        llm_total_ms  INT,
        tts_first_ms  INT,
        ttfa_ms       INT,
        total_ms      INT,
        error         TEXT,
        ts            TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # Memoria acumulada por (usuario, materia): resumen, temas vistos y dudas.
    """
    CREATE TABLE IF NOT EXISTS memoria_usuario (
        id                BIGSERIAL PRIMARY KEY,
        user_id           TEXT NOT NULL,
        subject_id        TEXT NOT NULL,
        resumen           TEXT,
        temas             JSONB NOT NULL DEFAULT '[]',
        dudas             JSONB NOT NULL DEFAULT '[]',
        n_sesiones        INT NOT NULL DEFAULT 0,
        ultima_session_id BIGINT REFERENCES sesiones(id),
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (user_id, subject_id)
    )
    """,
    # Config activa para las llamadas TELEFÓNICAS (Telnyx): una sola fila (id=1) con
    # el cfg que arma el panel (voz, modelo, persona, idioma, VAD…). El relay de Telnyx
    # la lee al arrancar para que el teléfono use lo seleccionado en el panel.
    """
    CREATE TABLE IF NOT EXISTS config_telefono (
        id           SMALLINT PRIMARY KEY DEFAULT 1,
        cfg          JSONB NOT NULL,
        actualizado  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # Servicios de llamada (capa multi-vertical): cada uno = persona+voz+corpus propio.
    # `ruta` = parte-de-usuario SIP / DID que enruta la llamada a este servicio.
    """
    CREATE TABLE IF NOT EXISTS servicios (
        id           BIGSERIAL PRIMARY KEY,
        nombre       TEXT NOT NULL,
        ruta         TEXT UNIQUE,
        subject_id   TEXT NOT NULL DEFAULT 'demo',
        cfg          JSONB NOT NULL DEFAULT '{}',
        es_default   BOOLEAN NOT NULL DEFAULT false,
        activo       BOOLEAN NOT NULL DEFAULT true,
        creado       TIMESTAMPTZ NOT NULL DEFAULT now(),
        actualizado  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # Índices: lecturas típicas (memoria por usuario+materia, sesiones por
    # materia, turnos de una sesión en orden temporal).
    "CREATE INDEX IF NOT EXISTS idx_sesiones_user_subject ON sesiones (user_id, subject_id)",
    "CREATE INDEX IF NOT EXISTS idx_sesiones_subject ON sesiones (subject_id)",
    "CREATE INDEX IF NOT EXISTS idx_turnos_session ON turnos (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_turnos_ts ON turnos (ts)",
]


async def crear_tablas() -> None:
    """Crea las 3 tablas e índices de la Fase 1. Idempotente (IF NOT EXISTS).
    Pensada para llamarse en el `startup` de la aplicación."""
    async with engine.begin() as conn:
        for ddl in _DDL:
            await conn.execute(text(ddl))


async def crear_sesion(
    subject_id: str, user_id: str, via: str, etiqueta: str | None = None
) -> int:
    """Abre una sesión y devuelve su id. `via` identifica la vía de voz usada
    (p.ej. 'live', 'cascada')."""
    async with engine.begin() as conn:
        nuevo_id = (
            await conn.execute(
                text(
                    "INSERT INTO sesiones (subject_id, user_id, via, etiqueta) "
                    "VALUES (:subject_id, :user_id, :via, :etiqueta) "
                    "RETURNING id"
                ),
                {
                    "subject_id": subject_id,
                    "user_id": user_id,
                    "via": via,
                    "etiqueta": etiqueta,
                },
            )
        ).scalar_one()
    return int(nuevo_id)


async def guardar_turnos(session_id: int, turnos: list[dict]) -> int:
    """Inserta N turnos de una sesión en una sola transacción y devuelve cuántos.

    Cada dict puede traer: idx, user_text, bot_text, grounded, chunks (list),
    stt_ms, retrieval_ms, llm_ttft_ms, llm_total_ms, tts_first_ms, ttfa_ms,
    total_ms, error. Lo que falte queda NULL (y chunks como '[]')."""
    if not turnos:
        return 0
    async with engine.begin() as conn:
        for t in turnos:
            await conn.execute(
                text(
                    "INSERT INTO turnos ("
                    "session_id, idx, user_text, bot_text, grounded, chunks, "
                    "stt_ms, retrieval_ms, llm_ttft_ms, llm_total_ms, "
                    "tts_first_ms, ttfa_ms, total_ms, error"
                    ") VALUES ("
                    ":session_id, :idx, :user_text, :bot_text, :grounded, "
                    "CAST(:chunks AS jsonb), "
                    ":stt_ms, :retrieval_ms, :llm_ttft_ms, :llm_total_ms, "
                    ":tts_first_ms, :ttfa_ms, :total_ms, :error"
                    ")"
                ),
                {
                    "session_id": session_id,
                    "idx": t.get("idx"),
                    "user_text": t.get("user_text"),
                    "bot_text": t.get("bot_text"),
                    "grounded": t.get("grounded"),
                    # chunks viaja como literal JSON casteado a jsonb (igual que
                    # los vectores van como literal casteado a vector en rag.py).
                    "chunks": json.dumps(t.get("chunks") or []),
                    "stt_ms": t.get("stt_ms"),
                    "retrieval_ms": t.get("retrieval_ms"),
                    "llm_ttft_ms": t.get("llm_ttft_ms"),
                    "llm_total_ms": t.get("llm_total_ms"),
                    "tts_first_ms": t.get("tts_first_ms"),
                    "ttfa_ms": t.get("ttfa_ms"),
                    "total_ms": t.get("total_ms"),
                    "error": t.get("error"),
                },
            )
    return len(turnos)


async def cerrar_sesion(session_id: int, n_turnos: int) -> None:
    """Marca la sesión como terminada (ended_at = now()) y fija su nº de turnos."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE sesiones SET ended_at = now(), n_turnos = :n WHERE id = :id"
            ),
            {"n": n_turnos, "id": session_id},
        )


# --------------------------------------------------------------------------- #
# Config de llamadas telefónicas (Telnyx) — la fija el panel, la lee el relay.
# --------------------------------------------------------------------------- #
async def guardar_config_telefono(cfg: dict) -> None:
    """Guarda (UPSERT, fila única id=1) el cfg que usarán las llamadas de teléfono."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO config_telefono (id, cfg, actualizado) "
                "VALUES (1, CAST(:cfg AS jsonb), now()) "
                "ON CONFLICT (id) DO UPDATE SET cfg = EXCLUDED.cfg, actualizado = now()"
            ),
            {"cfg": json.dumps(cfg)},
        )


async def obtener_config_telefono() -> dict | None:
    """Devuelve el cfg activo de teléfono, o None si nunca se guardó."""
    async with engine.connect() as conn:
        val = (
            await conn.execute(text("SELECT cfg FROM config_telefono WHERE id = 1"))
        ).scalar()
    if val is None:
        return None
    # asyncpg puede devolver jsonb como str o ya decodificado; normalizamos a dict.
    return json.loads(val) if isinstance(val, str) else val


# --------------------------------------------------------------------------- #
# Servicios de llamada (capa multi-vertical): persona+voz+corpus por servicio.
# --------------------------------------------------------------------------- #
def _cfg_a_dict(val):
    """Normaliza el cfg jsonb (str o dict) a dict."""
    if val is None:
        return {}
    return json.loads(val) if isinstance(val, str) else val


async def listar_servicios() -> list[dict]:
    """Todos los servicios (orden por nombre), con su cfg ya decodificado."""
    async with engine.connect() as conn:
        filas = (
            await conn.execute(
                text(
                    "SELECT id, nombre, ruta, subject_id, cfg, es_default, activo "
                    "FROM servicios ORDER BY nombre"
                )
            )
        ).mappings().all()
    return [
        {
            "id": int(f["id"]),
            "nombre": f["nombre"],
            "ruta": f["ruta"],
            "subject_id": f["subject_id"],
            "cfg": _cfg_a_dict(f["cfg"]),
            "es_default": f["es_default"],
            "activo": f["activo"],
        }
        for f in filas
    ]


async def guardar_servicio(
    nombre: str, ruta: str, subject_id: str, cfg: dict,
    es_default: bool = False, servicio_id: int | None = None
) -> int:
    """Crea (sin id → INSERT) o actualiza (con id → UPDATE) un servicio. Devuelve su id.
    Actualizar por id evita duplicados cuando el auto-guardado dispara mientras se teclea
    la ruta letra a letra (la primera vez crea, las siguientes actualizan la misma fila)."""
    params = {
        "nombre": nombre, "ruta": ruta, "subject_id": subject_id,
        "cfg": json.dumps(cfg or {}), "es_default": es_default,
    }
    async with engine.begin() as conn:
        if servicio_id:
            await conn.execute(
                text(
                    "UPDATE servicios SET nombre=:nombre, ruta=:ruta, subject_id=:subject_id, "
                    "cfg=CAST(:cfg AS jsonb), es_default=:es_default, actualizado=now() WHERE id=:id"
                ),
                {**params, "id": servicio_id},
            )
            return int(servicio_id)
        sid = (
            await conn.execute(
                text(
                    "INSERT INTO servicios (nombre, ruta, subject_id, cfg, es_default) "
                    "VALUES (:nombre, :ruta, :subject_id, CAST(:cfg AS jsonb), :es_default) RETURNING id"
                ),
                params,
            )
        ).scalar_one()
    return int(sid)


async def borrar_servicio(servicio_id: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM servicios WHERE id = :id"), {"id": servicio_id}
        )


async def resolver_servicio(ruta: str) -> dict | None:
    """Servicio activo cuya `ruta` coincide; si no hay, el marcado `es_default`. None si nada."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT nombre, subject_id, cfg FROM servicios "
                    "WHERE activo AND ruta = :r LIMIT 1"
                ),
                {"r": ruta},
            )
        ).mappings().first()
        if not row:
            row = (
                await conn.execute(
                    text(
                        "SELECT nombre, subject_id, cfg FROM servicios "
                        "WHERE activo AND es_default LIMIT 1"
                    )
                )
            ).mappings().first()
    if not row:
        return None
    return {
        "nombre": row["nombre"],
        "subject_id": row["subject_id"],
        "cfg": _cfg_a_dict(row["cfg"]),
    }


# --------------------------------------------------------------------------- #
# Lectura del historial — para que el frontend liste y muestre conversaciones.
# --------------------------------------------------------------------------- #
async def listar_sesiones(user_id: str, limit: int = 20) -> list[dict]:
    """Lista las sesiones de un usuario, la más reciente primero.

    Por cada sesión devuelve: id, via, subject_id, started_at, ended_at (ISO
    string o None), n_turnos y `preview` (el primer user_text no nulo de la
    sesión, vía subconsulta). Los timestamps se serializan a ISO string para
    que la respuesta sea directamente JSON-serializable."""
    async with engine.connect() as conn:
        filas = (
            await conn.execute(
                text(
                    "SELECT s.id, s.via, s.subject_id, s.started_at, s.ended_at, "
                    "s.n_turnos, "
                    "(SELECT user_text FROM turnos "
                    " WHERE session_id = s.id AND user_text IS NOT NULL "
                    " ORDER BY idx LIMIT 1) AS preview "
                    "FROM sesiones s "
                    "WHERE s.user_id = :u "
                    "ORDER BY s.started_at DESC "
                    "LIMIT :limit"
                ),
                {"u": user_id, "limit": limit},
            )
        ).mappings().all()

    out: list[dict] = []
    for f in filas:
        started = f["started_at"]
        ended = f["ended_at"]
        out.append(
            {
                "id": int(f["id"]),
                "via": f["via"],
                "subject_id": f["subject_id"],
                "started_at": started.isoformat() if started else None,
                "ended_at": ended.isoformat() if ended else None,
                "n_turnos": f["n_turnos"],
                "preview": f["preview"],
            }
        )
    return out


async def obtener_sesion(session_id: int) -> dict | None:
    """Devuelve una sesión con todos sus turnos (en orden idx, ts) o None si no
    existe. Los timestamps se serializan a ISO string."""
    async with engine.connect() as conn:
        ses = (
            await conn.execute(
                text(
                    "SELECT id, via, subject_id, started_at, ended_at, n_turnos "
                    "FROM sesiones WHERE id = :id"
                ),
                {"id": session_id},
            )
        ).mappings().first()
        if not ses:
            return None
        filas = (
            await conn.execute(
                text(
                    "SELECT idx, user_text, bot_text, ts FROM turnos "
                    "WHERE session_id = :id ORDER BY idx, ts"
                ),
                {"id": session_id},
            )
        ).mappings().all()

    turnos = [
        {
            "idx": f["idx"],
            "user_text": f["user_text"],
            "bot_text": f["bot_text"],
            "ts": f["ts"].isoformat() if f["ts"] else None,
        }
        for f in filas
    ]
    started = ses["started_at"]
    ended = ses["ended_at"]
    return {
        "id": int(ses["id"]),
        "via": ses["via"],
        "subject_id": ses["subject_id"],
        "started_at": started.isoformat() if started else None,
        "ended_at": ended.isoformat() if ended else None,
        "n_turnos": ses["n_turnos"],
        "turnos": turnos,
    }


# --------------------------------------------------------------------------- #
# Resumen + memoria — BEST-EFFORT: nunca lanza (todo en try/except con loguru).
# --------------------------------------------------------------------------- #
_RESUMEN_PROMPT = (
    "Eres un asistente que resume una sesión de tutoría por voz para guardarla "
    "como memoria del alumno. A partir de la transcripción (usuario y tutor), "
    "devuelve EXCLUSIVAMENTE un JSON válido con esta forma exacta:\n"
    '{"resumen": "<resumen breve de 1-3 frases>", '
    '"temas": ["<tema>", ...], '
    '"dudas": ["<duda no resuelta>", ...]}\n'
    "No añadas texto fuera del JSON. Si no hay dudas, usa una lista vacía.\n\n"
    "Transcripción:\n"
)


def _resumir_sync(transcripcion: str) -> dict:
    """Llama a Gemini Flash y parsea el JSON del resumen (síncrono; se invoca en
    un hilo desde la corutina). Pide salida JSON al modelo."""
    resp = _client.models.generate_content(
        model=RESUMEN_MODEL,
        contents=_RESUMEN_PROMPT + transcripcion,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(resp.text)


async def resumir_sesion(session_id: int) -> None:
    """Genera el resumen de la sesión y lo vuelca en memoria_usuario (UPSERT por
    user_id+subject_id). BEST-EFFORT: cualquier fallo se loguea y se traga; nunca
    lanza, para no romper el cierre de la llamada."""
    try:
        # 1) Datos de la sesión y sus turnos (en orden).
        async with engine.connect() as conn:
            ses = (
                await conn.execute(
                    text(
                        "SELECT subject_id, user_id FROM sesiones WHERE id = :id"
                    ),
                    {"id": session_id},
                )
            ).mappings().first()
            if not ses:
                logger.warning(f"resumir_sesion: sesión {session_id} no existe")
                return
            filas = (
                await conn.execute(
                    text(
                        "SELECT user_text, bot_text FROM turnos "
                        "WHERE session_id = :id ORDER BY idx, ts"
                    ),
                    {"id": session_id},
                )
            ).mappings().all()

        if not filas:
            logger.info(f"resumir_sesion: sesión {session_id} sin turnos; nada que resumir")
            return

        subject_id = ses["subject_id"]
        user_id = ses["user_id"]

        # 2) Construir la transcripción y pedir el resumen a Gemini (en hilo).
        lineas = []
        for f in filas:
            if f["user_text"]:
                lineas.append(f"Usuario: {f['user_text']}")
            if f["bot_text"]:
                lineas.append(f"Tutor: {f['bot_text']}")
        transcripcion = "\n".join(lineas)

        datos = await asyncio.to_thread(_resumir_sync, transcripcion)
        resumen = datos.get("resumen") or ""
        temas = datos.get("temas") or []
        dudas = datos.get("dudas") or []

        # 3) UPSERT en memoria_usuario por (user_id, subject_id).
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO memoria_usuario ("
                    "user_id, subject_id, resumen, temas, dudas, "
                    "n_sesiones, ultima_session_id, updated_at"
                    ") VALUES ("
                    ":user_id, :subject_id, :resumen, "
                    "CAST(:temas AS jsonb), CAST(:dudas AS jsonb), "
                    "1, :session_id, now()"
                    ") ON CONFLICT (user_id, subject_id) DO UPDATE SET "
                    "resumen = EXCLUDED.resumen, "
                    "temas = EXCLUDED.temas, "
                    "dudas = EXCLUDED.dudas, "
                    "n_sesiones = memoria_usuario.n_sesiones + 1, "
                    "ultima_session_id = EXCLUDED.ultima_session_id, "
                    "updated_at = now()"
                ),
                {
                    "user_id": user_id,
                    "subject_id": subject_id,
                    "resumen": resumen,
                    "temas": json.dumps(temas),
                    "dudas": json.dumps(dudas),
                    "session_id": session_id,
                },
            )
        logger.info(
            f"resumir_sesion: memoria actualizada user={user_id} subject={subject_id} "
            f"(sesión {session_id})"
        )
    except Exception:
        logger.exception(f"resumir_sesion falló (sesión {session_id}); se ignora (best-effort)")
