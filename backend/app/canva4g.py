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
import io
import json
import wave

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
            {"campo": "nombre", "etiqueta": "Nombre", "pregunta": "¿Cómo te llamas?"},
            {"campo": "tiempo_disponible", "etiqueta": "Tiempo disponible", "pregunta": "¿De cuánto tiempo dispones ahora?"},
        ],
        "obligatorios": ["nombre", "tiempo_disponible"],
        "descripcion": "Presentación: el NOMBRE de la persona y CUÁNTO TIEMPO tiene disponible ahora.",
        "shape": '{"nombre": "<nombre o vacío>", "tiempo_disponible": "<p.ej. 20 minutos, o vacío>"}',
    },
    {
        "key": "vision", "titulo": "Visión", "tipo": "fijo",
        "apartados": [
            {"campo": "ser", "etiqueta": "Quiere SER", "pregunta": "Si te quedaran tres meses de vida, ¿qué querrías SER?"},
            {"campo": "hacer", "etiqueta": "Quiere HACER", "pregunta": "¿Qué querrías HACER?"},
            {"campo": "tener", "etiqueta": "Quiere TENER", "pregunta": "¿Qué querrías TENER?"},
        ],
        "obligatorios": ["ser", "hacer", "tener"],
        "descripcion": "La VISIÓN desglosada en lo que la persona quiere SER, HACER y TENER (en ese orden).",
        "shape": '{"ser": "<o vacío>", "hacer": "<o vacío>", "tener": "<o vacío>"}',
    },
    {
        "key": "mision", "titulo": "Misión", "tipo": "fijo",
        "apartados": [{"campo": "mision", "etiqueta": "Misión", "pregunta": "¿Qué acciones, ligadas a tus dones y talentos, te llevarían a esa visión?"}],
        "obligatorios": ["mision"],
        "descripcion": "La MISIÓN: las acciones para lograr la visión, ligadas a sus dones y talentos.",
        "shape": '{"mision": "<o vacío>"}',
    },
    {
        "key": "valores", "titulo": "Valores", "tipo": "lista", "lista": "valores", "min_lista": 3,
        "apartados": [], "pregunta": "¿Qué principios guían tus decisiones? Dime al menos tres, cada uno con una breve explicación.",
        "descripcion": "Los VALORES: principios que guían sus decisiones (hasta 5), cada uno con breve explicación.",
        "shape": '{"valores": [{"valor": "<nombre>", "explicacion": "<breve>"}]}  (lista vacía si aún nada)',
    },
    {
        "key": "pilares", "titulo": "Pilares", "tipo": "fijo",
        "apartados": [
            {"campo": "espiritual", "etiqueta": "Espiritual", "pregunta": "¿Cómo te sientes en tu pilar espiritual?"},
            {"campo": "mental", "etiqueta": "Mental-emocional", "pregunta": "¿Y en el mental-emocional?"},
            {"campo": "fisico", "etiqueta": "Físico", "pregunta": "¿Y en el físico?"},
            {"campo": "social", "etiqueta": "Social", "pregunta": "¿Y en el social?"},
        ],
        "obligatorios": ["espiritual", "mental", "fisico", "social"],
        "descripcion": "Los 4 PILARES de vida: qué dice o cómo se siente en cada uno (espiritual, mental-emocional, físico, social).",
        "shape": '{"espiritual": "<o vacío>", "mental": "<o vacío>", "fisico": "<o vacío>", "social": "<o vacío>"}',
    },
    {
        "key": "roles", "titulo": "Roles", "tipo": "lista", "lista": "roles", "min_lista": 3,
        "apartados": [], "pregunta": "¿Cuáles son los papeles más importantes de tu vida? (máximo 8, cada uno con su área).",
        "descripcion": "Los ROLES más importantes de su vida (máx. 8), cada uno con el pilar al que pertenece.",
        "shape": '{"roles": [{"nombre": "<rol>", "pilar": "espiritual|mental|fisico|social"}]}  (lista vacía si aún nada)',
    },
    {
        "key": "bloque", "titulo": "Primer bloque", "tipo": "fijo",
        "apartados": [
            {"campo": "rol", "etiqueta": "Rol / objetivo", "pregunta": "¿Para qué rol u objetivo quieres reservar tu primer bloque?"},
            {"campo": "fecha_hora_iso", "etiqueta": "Día y hora", "pregunta": "¿Qué día y a qué hora te viene bien?"},
        ],
        "obligatorios": ["rol", "fecha_hora_iso"],
        "descripcion": "El PRIMER BLOQUE a agendar: para qué rol/objetivo, y el día y la hora acordados.",
        "shape": '{"rol": "<o vacío>", "fecha_hora_iso": "<ISO 8601 con offset, p.ej. 2026-06-23T17:00:00+02:00, o vacío>"}',
    },
]

SECCIONES_POR_KEY = {s["key"]: s for s in SECCIONES}

# Consulta de RAG por bloque: recupera del corpus del libro las ideas de Fabián que ANCLAN el
# coaching de esa fase (se inyectan como MATERIAL en el relevo de agente). None = sin anclaje
# (la presentación no necesita material del libro).
RAG_QUERIES = {
    "presentacion": None,
    "vision": "la visión personal: qué quieres ser, hacer y tener; imaginar tres meses de vida",
    "mision": "la misión personal ligada a tus dones y talentos; la dotación",
    "valores": "los valores: principios que guían tus decisiones",
    "pilares": "los cuatro pilares de la vida: espiritual, mental-emocional, físico, social; rueda de la vida",
    "roles": "qué es un rol; la parrilla de los ocho roles por pilar",
    "bloque": "bloques de tiempo, time blocking; si no está en la agenda no existe",
}


def secciones_publicas() -> list[dict]:
    """Para el frontend: key, título, tipo, apartados y campo-lista de cada sección."""
    return [
        {"key": s["key"], "titulo": s["titulo"], "tipo": s.get("tipo", "fijo"),
         "apartados": s.get("apartados", []), "lista": s.get("lista"),
         "pregunta": s.get("pregunta")}
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


def completas(canva: dict | None) -> list[str]:
    """Keys de las secciones ya completas (para que el frontend marque ✓ cada bloque por sus DATOS,
    no por un índice lineal: con botón por bloque el usuario puede rellenarlas en cualquier orden)."""
    canva = canva or {}
    return [s["key"] for s in SECCIONES if seccion_completa(s, canva.get(s["key"]))]


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
def _extraer_sync(seccion_key: str, conversacion: str, fecha_ctx: str, stt_fiable: str = "") -> dict:
    seccion = SECCIONES_POR_KEY[seccion_key]
    ctx_tiempo = (
        f"Contexto temporal: hoy es {fecha_ctx}. Para 'fecha_hora_iso' convierte la fecha y hora "
        f"acordadas (aunque se digan en relativo, p.ej. 'el martes a las cinco') a ISO 8601 con "
        f"offset de Europe/Madrid.\n"
        if seccion_key == "bloque" else ""
    )
    fiable = (
        f"TRANSCRIPCIÓN FIABLE (STT en español) de la ÚLTIMA intervención de la PERSONA: «{stt_fiable}»\n\n"
        if stt_fiable else ""
    )
    prompt = (
        "Eres un extractor de datos. De la siguiente conversación entre una GUÍA y una PERSONA, "
        "extrae ÚNICAMENTE los datos de esta sección del Canva 4G y devuelve EXCLUSIVAMENTE un JSON válido.\n\n"
        f"SECCIÓN: {seccion['titulo']} — {seccion['descripcion']}\n"
        f"FORMA EXACTA del JSON a devolver: {seccion['shape']}\n\n"
        "REGLAS:\n"
        "- La transcripción de la PERSONA dentro de CONVERSACIÓN puede venir MAL (otro idioma o "
        "palabras equivocadas). Por orden de FIABILIDAD usa: (1) la TRANSCRIPCIÓN FIABLE de arriba "
        "si existe; (2) lo que la GUÍA CONFIRMA de forma explícita (p. ej. 'he entendido que te "
        "llamas Jose'); y en último lugar el texto crudo de la PERSONA.\n"
        "- Extrae solo datos dichos CLARAMENTE; no inventes ni completes.\n"
        "- Si un campo aún no se ha dicho, déjalo como cadena vacía (o lista vacía).\n"
        "- Si un nombre propio viniera en otro alfabeto, pásalo a alfabeto LATINO del español.\n"
        "- Devuelve solo el JSON, sin texto alrededor.\n"
        f"{ctx_tiempo}\n"
        f"{fiable}"
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


async def extraer_seccion(seccion_key: str, conversacion: str, fecha_ctx: str, stt_fiable: str = "") -> dict:
    try:
        return await asyncio.to_thread(_extraer_sync, seccion_key, conversacion, fecha_ctx, stt_fiable)
    except Exception:
        logger.exception(f"[4g] extraer_seccion '{seccion_key}' falló")
        return {}


# --------------------------------------------------------------------------- #
# STT FIABLE de respaldo: re-transcribe el audio del último turno con Gemini forzando ESPAÑOL, para
# no depender de la transcripción de native-audio (que confunde nombres: 'José'→'Suchen'/'Rosa').
# --------------------------------------------------------------------------- #
def _pcm_to_wav(pcm: bytes, rate: int = 16000) -> bytes:
    """Envuelve PCM16 mono en un contenedor WAV (Gemini no acepta PCM crudo, sí WAV)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _stt_sync(pcm: bytes) -> str:
    resp = _client.models.generate_content(
        model=EXTRACT_MODEL,
        contents=[
            types.Part.from_bytes(data=_pcm_to_wav(pcm), mime_type="audio/wav"),
            "Transcribe literalmente, en ESPAÑOL, lo que dice la persona. Devuelve solo el texto, "
            "sin comillas ni comentarios.",
        ],
    )
    return (resp.text or "").strip()


async def transcribir_audio(pcm: bytes) -> str:
    """STT fiable (Gemini, español) del audio de un turno; '' si no hay audio o falla."""
    if not pcm:
        return ""
    try:
        return await asyncio.to_thread(_stt_sync, pcm)
    except Exception:
        logger.exception("[4g] transcribir_audio falló")
        return ""
