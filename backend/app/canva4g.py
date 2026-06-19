"""Onboarding 4G: modelo del Canva + extracción DETERMINISTA por sección (con apartados).

El "Canva" es la Plataforma Estratégica Personal del método 4G. Cada sección tiene
**apartados** (sub-campos) que se rellenan y se marcan en verde en vivo según la extracción
los va capturando. Las secciones "fijas" tienen apartados con nombre (Visión: ser/hacer/tener;
Pilares: 4 áreas); las de "lista" (Valores, Roles) acumulan ítems.

Clave (decisión MVP): la **compuerta "sección completa" la decide el CÓDIGO** (`seccion_completa`),
no el LLM. El prompt de la guía conduce la charla; aquí capturamos, validamos y damos por
completa cada sección.
"""
import asyncio
import json

from google.genai import types
from loguru import logger
from sqlalchemy import text

from .db import engine
from .live_relay import _client  # Vertex AI (ADC) reutilizado: evita la cuota FREE-TIER del
                                 # Developer API key, que se agota en pruebas (429 RESOURCE_EXHAUSTED).

EXTRACT_MODEL = "gemini-2.5-flash"


# --------------------------------------------------------------------------- #
# Secciones del Canva. `tipo`: "fijo" (apartados con nombre) | "lista" (ítems).
# `apartados`: sub-campos a mostrar/rellenar. `obligatorios`: los que exige la
# compuerta (fijo). `min_lista`: nº mínimo de ítems para dar por completa (lista).
# `shape`: forma EXACTA del JSON que pedimos al extractor.
# --------------------------------------------------------------------------- #
SECCIONES = [
    {
        "key": "presentacion", "titulo": "Presentación", "tipo": "fijo",
        "apartados": [
            {"campo": "nombre", "etiqueta": "Nombre"},
            {"campo": "tiempo_disponible", "etiqueta": "Tiempo disponible"},
        ],
        "obligatorios": ["nombre"],
        "descripcion": "Presentación: el NOMBRE de la persona y CUÁNTO TIEMPO tiene disponible ahora.",
        "shape": '{"nombre": "<nombre o vacío>", "tiempo_disponible": "<p.ej. 20 minutos, o vacío>"}',
    },
    {
        "key": "vision", "titulo": "Visión", "tipo": "fijo",
        "apartados": [
            {"campo": "ser", "etiqueta": "Quiere SER"},
            {"campo": "hacer", "etiqueta": "Quiere HACER"},
            {"campo": "tener", "etiqueta": "Quiere TENER"},
        ],
        "obligatorios": ["ser", "hacer", "tener"],
        "descripcion": "La VISIÓN desglosada en lo que la persona quiere SER, HACER y TENER (en ese orden).",
        "shape": '{"ser": "<o vacío>", "hacer": "<o vacío>", "tener": "<o vacío>"}',
    },
    {
        "key": "mision", "titulo": "Misión", "tipo": "fijo",
        "apartados": [{"campo": "mision", "etiqueta": "Misión"}],
        "obligatorios": ["mision"],
        "descripcion": "La MISIÓN: las acciones para lograr la visión, ligadas a sus dones y talentos.",
        "shape": '{"mision": "<o vacío>"}',
    },
    {
        "key": "valores", "titulo": "Valores", "tipo": "lista", "lista": "valores", "min_lista": 3,
        "apartados": [],
        "descripcion": "Los VALORES: principios que guían sus decisiones (hasta 5), cada uno con breve explicación.",
        "shape": '{"valores": [{"valor": "<nombre>", "explicacion": "<breve>"}]}  (lista vacía si aún nada)',
    },
    {
        "key": "pilares", "titulo": "Pilares", "tipo": "fijo",
        "apartados": [
            {"campo": "espiritual", "etiqueta": "Espiritual"},
            {"campo": "mental", "etiqueta": "Mental-emocional"},
            {"campo": "fisico", "etiqueta": "Físico"},
            {"campo": "social", "etiqueta": "Social"},
        ],
        "obligatorios": ["espiritual", "mental", "fisico", "social"],
        "descripcion": "Los 4 PILARES de vida: qué dice o cómo se siente en cada uno (espiritual, mental-emocional, físico, social).",
        "shape": '{"espiritual": "<o vacío>", "mental": "<o vacío>", "fisico": "<o vacío>", "social": "<o vacío>"}',
    },
    {
        "key": "roles", "titulo": "Roles", "tipo": "lista", "lista": "roles", "min_lista": 3,
        "apartados": [],
        "descripcion": "Los ROLES más importantes de su vida (máx. 8), cada uno con el pilar al que pertenece.",
        "shape": '{"roles": [{"nombre": "<rol>", "pilar": "espiritual|mental|fisico|social"}]}  (lista vacía si aún nada)',
    },
    {
        "key": "bloque", "titulo": "Primer bloque", "tipo": "fijo",
        "apartados": [
            {"campo": "rol", "etiqueta": "Rol / objetivo"},
            {"campo": "fecha_hora_iso", "etiqueta": "Día y hora"},
        ],
        "obligatorios": ["rol", "fecha_hora_iso"],
        "descripcion": "El PRIMER BLOQUE a agendar: para qué rol/objetivo, y el día y la hora acordados.",
        "shape": '{"rol": "<o vacío>", "fecha_hora_iso": "<ISO 8601 con offset, p.ej. 2026-06-23T17:00:00+02:00, o vacío>"}',
    },
]

SECCIONES_POR_KEY = {s["key"]: s for s in SECCIONES}


def secciones_publicas() -> list[dict]:
    """Para el frontend: key, título, tipo, apartados y campo-lista de cada sección."""
    return [
        {"key": s["key"], "titulo": s["titulo"], "tipo": s.get("tipo", "fijo"),
         "apartados": s.get("apartados", []), "lista": s.get("lista")}
        for s in SECCIONES
    ]


def seccion_completa(seccion: dict, datos: dict | None) -> bool:
    """La COMPUERTA del flujo (la decide el código). Fijo: todos los obligatorios rellenos.
    Lista: al menos `min_lista` ítems."""
    datos = datos or {}
    if seccion.get("tipo") == "lista":
        v = datos.get(seccion["lista"])
        return isinstance(v, list) and len(v) >= seccion.get("min_lista", 1)
    for campo in seccion["obligatorios"]:
        v = datos.get(campo)
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


def merge_seccion(seccion: dict, prev: dict | None, datos: dict | None) -> dict:
    """Funde lo nuevo sobre lo previo SIN pisar con vacíos. En listas, se queda con la lista
    más completa (la extracción devuelve la lista entera de la conversación acumulada)."""
    prev = dict(prev or {})
    datos = datos or {}
    if seccion.get("tipo") == "lista":
        campo = seccion["lista"]
        nuevos = datos.get(campo)
        if isinstance(nuevos, list) and len(nuevos) >= len(prev.get(campo) or []):
            prev[campo] = nuevos
        return prev
    for k, v in datos.items():
        if v not in (None, "", []):   # nunca borrar un dato ya capturado con un vacío
            prev[k] = v
    return prev


def resumen_canva(canva: dict | None) -> str:
    """Resumen breve de lo ya capturado (para inyectar al RETOMAR y que la guía no repita)."""
    canva = canva or {}
    lineas = []
    for s in SECCIONES:
        d = canva.get(s["key"]) or {}
        if s.get("tipo") == "lista":
            arr = d.get(s["lista"]) or []
            items = ", ".join(
                (x.get("valor") or x.get("nombre") or "") for x in arr if isinstance(x, dict)
            ).strip(", ")
            if items:
                lineas.append(f"- {s['titulo']}: {items}")
        else:
            partes = [f"{a['etiqueta']}: {d.get(a['campo'])}"
                      for a in s.get("apartados", []) if d.get(a["campo"])]
            if partes:
                lineas.append(f"- {s['titulo']}: " + "; ".join(partes))
    return "\n".join(lineas)


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
    async with engine.begin() as conn:
        await conn.execute(text(_DDL))


async def obtener_canva(user_id: str) -> dict:
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


async def borrar_canva(user_id: str) -> None:
    """Borra el Canva de un usuario (reinicio para pruebas)."""
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM canva_4g WHERE user_id = :u"), {"u": user_id})


# --------------------------------------------------------------------------- #
# Extracción por sección (Flash → JSON). Síncrono en hilo (no bloquea el loop).
# --------------------------------------------------------------------------- #
def _extraer_sync(seccion_key: str, conversacion: str, fecha_ctx: str) -> dict:
    seccion = SECCIONES_POR_KEY[seccion_key]
    ctx_tiempo = (
        f"Contexto temporal: hoy es {fecha_ctx}. Para 'fecha_hora_iso' convierte la fecha y hora "
        f"acordadas (aunque se digan en relativo, p.ej. 'el martes a las cinco') a ISO 8601 con "
        f"offset de Europe/Madrid.\n"
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
    try:
        return await asyncio.to_thread(_extraer_sync, seccion_key, conversacion, fecha_ctx)
    except Exception:
        logger.exception(f"[4g] extraer_seccion '{seccion_key}' falló")
        return {}
