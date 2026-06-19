"""Onboarding 4G: modelo del Canva + extracción DETERMINISTA por sección.

El "Canva" es la Plataforma Estratégica Personal del método 4G. Esta capa define las
SECCIONES (Visión → Misión → Valores → Pilares → Roles → Primer bloque), persiste el
Canva por usuario (tabla `canva_4g`, una fila JSONB por user_id) y extrae de la
conversación, sección a sección, los campos con Gemini Flash.

Clave del diseño (decisión MVP): la **compuerta "sección completa" la decide el CÓDIGO**
(`seccion_completa`: campos obligatorios no vacíos), no el criterio del LLM. El prompt de la
entrevistadora conduce la charla; aquí solo capturamos y validamos lo dicho.
"""
import asyncio
import json

from google import genai
from google.genai import types
from loguru import logger
from sqlalchemy import text

from .config import settings
from .db import engine

# Cliente Gemini (Developer API por API key), mismo patrón que persistence/embeddings.
_client = genai.Client(api_key=settings.google_api_key)
EXTRACT_MODEL = "gemini-2.5-flash"   # barato y suficiente para extracción estructurada


# --------------------------------------------------------------------------- #
# Secciones del Canva. `obligatorios` = campos que deben venir para dar la sección
# por completa. `lista` = el campo es una lista y exige >= 1 elemento. `shape` = la
# forma EXACTA del JSON que pedimos al extractor (para que las claves sean estables).
# --------------------------------------------------------------------------- #
SECCIONES = [
    {
        "key": "vision", "titulo": "Visión", "obligatorios": ["vision"],
        "descripcion": "La VISIÓN: lo que la persona quiere ser, hacer y tener (en ese orden); sus ideales y metas a largo plazo.",
        "shape": '{"vision": "<texto, o cadena vacía si aún no lo ha dicho>"}',
    },
    {
        "key": "mision", "titulo": "Misión", "obligatorios": ["mision"],
        "descripcion": "La MISIÓN: las acciones concretas para lograr la visión, ligadas a sus dones, talentos y a cómo sirve a otros.",
        "shape": '{"mision": "<texto, o cadena vacía>"}',
    },
    {
        "key": "valores", "titulo": "Valores", "obligatorios": ["valores"], "lista": "valores",
        "descripcion": "Los VALORES: principios que guían sus decisiones (hasta 5), cada uno con una breve explicación.",
        "shape": '{"valores": [{"valor": "<nombre>", "explicacion": "<breve>"}]}  (lista vacía si aún no ha dicho ninguno)',
    },
    {
        "key": "pilares", "titulo": "Pilares", "obligatorios": ["pilares"], "lista": "pilares",
        "descripcion": "Los 4 PILARES de vida (espiritual, mental-emocional, físico, social): cómo se siente o qué dice de cada uno.",
        "shape": '{"pilares": [{"area": "espiritual|mental|fisico|social", "nota": "<lo que dijo>"}]}  (lista vacía si aún nada)',
    },
    {
        "key": "roles", "titulo": "Roles", "obligatorios": ["roles"], "lista": "roles",
        "descripcion": "Los ROLES más importantes de su vida (máx. 8), cada uno con el pilar al que pertenece.",
        "shape": '{"roles": [{"nombre": "<rol>", "pilar": "espiritual|mental|fisico|social"}]}  (lista vacía si aún nada)',
    },
    {
        "key": "bloque", "titulo": "Primer bloque", "obligatorios": ["rol", "fecha_hora_iso"],
        "descripcion": "El PRIMER BLOQUE de tiempo a agendar: para qué rol/objetivo, y el día y la hora acordados.",
        "shape": '{"rol": "<rol/objetivo, o vacío>", "fecha_hora_iso": "<ISO 8601 con offset, p.ej. 2026-06-23T17:00:00+02:00, o vacío>"}',
    },
]

SECCIONES_POR_KEY = {s["key"]: s for s in SECCIONES}


def secciones_publicas() -> list[dict]:
    """Lista ligera (key + título) para el stepper del frontend."""
    return [{"key": s["key"], "titulo": s["titulo"]} for s in SECCIONES]


def seccion_completa(seccion: dict, datos: dict | None) -> bool:
    """True si todos los campos obligatorios de la sección están rellenos.
    La COMPUERTA del flujo: la decide el código, no el LLM."""
    datos = datos or {}
    for campo in seccion["obligatorios"]:
        v = datos.get(campo)
        if seccion.get("lista") == campo:
            if not isinstance(v, list) or len(v) == 0:
                return False
        else:
            if not v or (isinstance(v, str) and not v.strip()):
                return False
    return True


def primera_incompleta(canva: dict | None) -> int:
    """Índice de la primera sección no completa (para retomar). len(SECCIONES) si todo está."""
    canva = canva or {}
    for i, s in enumerate(SECCIONES):
        if not seccion_completa(s, canva.get(s["key"])):
            return i
    return len(SECCIONES)


# --------------------------------------------------------------------------- #
# Persistencia del Canva (una fila JSONB por usuario). DDL idempotente.
# --------------------------------------------------------------------------- #
_DDL = """
CREATE TABLE IF NOT EXISTS canva_4g (
    user_id     TEXT PRIMARY KEY,
    subject_id  TEXT NOT NULL DEFAULT 'libro-4g',
    datos       JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


async def crear_tablas_4g() -> None:
    """Crea la tabla canva_4g (idempotente). Se llama en el startup de la app."""
    async with engine.begin() as conn:
        await conn.execute(text(_DDL))


async def obtener_canva(user_id: str) -> dict:
    """Canva guardado del usuario (dict por sección), o {} si no hay."""
    async with engine.connect() as conn:
        val = (
            await conn.execute(
                text("SELECT datos FROM canva_4g WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar()
    if val is None:
        return {}
    return json.loads(val) if isinstance(val, str) else val


async def guardar_canva(user_id: str, datos: dict, subject_id: str = "libro-4g") -> None:
    """UPSERT del Canva del usuario."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO canva_4g (user_id, subject_id, datos, updated_at) "
                "VALUES (:u, :s, CAST(:d AS jsonb), now()) "
                "ON CONFLICT (user_id) DO UPDATE SET datos = EXCLUDED.datos, "
                "subject_id = EXCLUDED.subject_id, updated_at = now()"
            ),
            {"u": user_id, "s": subject_id, "d": json.dumps(datos)},
        )


# --------------------------------------------------------------------------- #
# Extracción por sección (Flash → JSON). Síncrono en hilo (no bloquea el loop).
# --------------------------------------------------------------------------- #
def _extraer_sync(seccion_key: str, conversacion: str, fecha_ctx: str) -> dict:
    seccion = SECCIONES_POR_KEY[seccion_key]
    ctx_tiempo = (
        f"Contexto temporal: hoy es {fecha_ctx}. Para 'fecha_hora_iso' convierte la fecha y hora "
        f"acordadas (aunque se digan de forma relativa, p.ej. 'el martes a las cinco') a ISO 8601 "
        f"con offset de Europe/Madrid.\n"
        if seccion_key == "bloque" else ""
    )
    prompt = (
        "Eres un extractor de datos. De la siguiente conversación entre una GUÍA y una PERSONA, "
        "extrae ÚNICAMENTE los datos de esta sección del Canva 4G y devuelve EXCLUSIVAMENTE un JSON válido.\n\n"
        f"SECCIÓN: {seccion['titulo']} — {seccion['descripcion']}\n"
        f"FORMA EXACTA del JSON a devolver: {seccion['shape']}\n\n"
        "REGLAS:\n"
        "- Extrae solo lo que la PERSONA haya dicho CLARAMENTE. No inventes ni completes tú.\n"
        "- Si un campo aún no se ha dicho, déjalo como cadena vacía (o lista vacía).\n"
        "- Devuelve solo el JSON, sin texto alrededor.\n"
        f"{ctx_tiempo}\n"
        f"CONVERSACIÓN:\n{conversacion}\n"
    )
    resp = _client.models.generate_content(
        model=EXTRACT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    try:
        return json.loads(resp.text)
    except Exception:
        logger.warning(f"[4g] extracción '{seccion_key}': JSON no parseable: {resp.text[:200]}")
        return {}


async def extraer_seccion(seccion_key: str, conversacion: str, fecha_ctx: str) -> dict:
    """Extrae (en hilo) los campos de una sección a partir de la conversación. {} si falla."""
    try:
        return await asyncio.to_thread(_extraer_sync, seccion_key, conversacion, fecha_ctx)
    except Exception:
        logger.exception(f"[4g] extraer_seccion '{seccion_key}' falló")
        return {}
