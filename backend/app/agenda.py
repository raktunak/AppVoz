"""Agenda de citas sobre Google Calendar (Fase 1 del plan de agenda).

Capa fina sobre la Calendar API para **crear / buscar / borrar** citas en un
calendario, usada por la "secretaria" de voz. Auth por la **misma service account**
que ya usamos para Vertex (`appvoz-voice.json`), añadiendo el scope de Calendar; el
calendario destino debe estar **compartido con el email de la SA** con permiso de
"hacer cambios en eventos" (paso humano, Fase 0). No hace falta secreto nuevo.

Diseño:
- La librería `googleapiclient` es SÍNCRONA → el núcleo es síncrono y se expone con
  envoltorios `async` vía `asyncio.to_thread`, para no bloquear el event-loop del relay
  (mismo patrón que `persistence._resumir_sync`).
- El teléfono y el nombre del cliente se guardan en `extendedProperties.private`, así
  podemos **localizar las citas de un cliente por su teléfono** (para cancelar) sin
  depender de adivinar sobre el texto del evento.
- Zona horaria fija `Europe/Madrid` (configurable por `AGENDA_TIMEZONE`). El `datetime`
  de inicio se normaliza a esa zona (maneja el horario de verano, CEST en junio).
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger

from .config import settings

# Scope completo de Calendar: cubre crear/listar/borrar eventos y, a futuro, la consulta
# de disponibilidad (freebusy, R6). La SA no pasa por pantalla de consentimiento, así que
# la minimización de scope (que sí importará en el OAuth por usuario de la Fase 5) aquí no aplica.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Servicio de Calendar construido una vez y cacheado a nivel de módulo (lazy).
_service = None


def _resolver_credenciales() -> str:
    """Ruta utilizable al JSON de la SA. Prueba la ruta de settings tal cual (relativa al
    cwd, p.ej. en Docker el working dir es la carpeta de la app) y, si no está, la resuelve
    relativa a la carpeta del backend (para correr el script de prueba desde la raíz del repo)."""
    ruta = settings.google_application_credentials
    if ruta and os.path.exists(ruta):
        return ruta
    # backend/app/agenda.py -> backend/  (dos niveles arriba) + la ruta relativa de settings
    alt = os.path.join(os.path.dirname(os.path.dirname(__file__)), ruta)
    if os.path.exists(alt):
        return alt
    raise FileNotFoundError(
        f"No encuentro el JSON de la service account ('{ruta}'). Necesario para la agenda."
    )


def _get_service():
    """Cliente de Calendar (cacheado). cache_discovery=False evita el warning/escritura de
    caché del discovery doc en entornos sin disco escribible (Cloud Run)."""
    global _service
    if _service is None:
        creds = service_account.Credentials.from_service_account_file(
            _resolver_credenciales(), scopes=SCOPES
        )
        _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        logger.info("[agenda] cliente Calendar construido (SA + scope calendar)")
    return _service


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.agenda_timezone)


def _a_zona(dt: datetime) -> datetime:
    """Normaliza el datetime a la zona de la agenda: si viene naive le asigna la zona;
    si ya es aware lo convierte. Así 'mañana a las 5' acaba siendo la hora local correcta."""
    tz = _tz()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


# --------------------------------------------------------------------------- #
# Núcleo síncrono (googleapiclient es sync). No llamar desde el event-loop:
# usar los envoltorios async de más abajo.
# --------------------------------------------------------------------------- #
def _crear_evento_sync(
    service, calendar_id: str, inicio: datetime, duracion_min: int, resumen: str,
    descripcion: str | None, telefono: str | None, nombre: str | None,
    datos: dict | None,
) -> dict:
    inicio = _a_zona(inicio)
    fin = inicio + timedelta(minutes=duracion_min)
    tz_name = settings.agenda_timezone
    private = {"origen": "appvoz"}
    if telefono:
        private["telefono"] = telefono
    if nombre:
        private["nombre"] = nombre
    if datos:
        # extendedProperties solo admite valores string → serializamos el JSONB del vertical.
        private["datos"] = json.dumps(datos, ensure_ascii=False)
    body = {
        "summary": resumen,
        "description": descripcion or "",
        "start": {"dateTime": inicio.isoformat(), "timeZone": tz_name},
        "end": {"dateTime": fin.isoformat(), "timeZone": tz_name},
        "extendedProperties": {"private": private},
    }
    ev = service.events().insert(calendarId=calendar_id, body=body).execute()
    logger.info(f"[agenda] cita creada id={ev['id']} inicio={inicio.isoformat()} cal={calendar_id}")
    return {
        "event_id": ev["id"],
        "html_link": ev.get("htmlLink"),
        "inicio": ev["start"].get("dateTime"),
        "fin": ev["end"].get("dateTime"),
    }


def _buscar_eventos_sync(calendar_id: str, telefono: str, desde: datetime | None) -> list[dict]:
    desde = _a_zona(desde) if desde else datetime.now(_tz())
    res = (
        _get_service().events().list(
            calendarId=calendar_id,
            privateExtendedProperty=f"telefono={telefono}",
            timeMin=desde.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=10,
        ).execute()
    )
    out = []
    for e in res.get("items", []):
        priv = (e.get("extendedProperties") or {}).get("private") or {}
        out.append({
            "event_id": e["id"],
            "resumen": e.get("summary"),
            "inicio": (e.get("start") or {}).get("dateTime"),
            "fin": (e.get("end") or {}).get("dateTime"),
            "nombre": priv.get("nombre"),
        })
    logger.info(f"[agenda] búsqueda telefono={telefono} -> {len(out)} cita(s)")
    return out


def _borrar_evento_sync(calendar_id: str, event_id: str) -> bool:
    """Borra el evento. Si ya no existe (404/410) lo trata como borrado (idempotente)."""
    try:
        _get_service().events().delete(calendarId=calendar_id, eventId=event_id).execute()
        logger.info(f"[agenda] cita borrada id={event_id} cal={calendar_id}")
        return True
    except HttpError as e:
        if e.resp is not None and e.resp.status in (404, 410):
            logger.info(f"[agenda] cita id={event_id} ya no existía (status {e.resp.status})")
            return True
        raise


# --------------------------------------------------------------------------- #
# API pública async (la que usa el relay / la tool). asyncio.to_thread mantiene
# el event-loop libre mientras la llamada HTTP a Calendar está en curso.
# --------------------------------------------------------------------------- #
def _service_de_creds(creds):
    """Cliente de Calendar a partir de credenciales OAuth de un USUARIO (no la SA)."""
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


async def crear_evento(
    calendar_id: str, inicio: datetime, *, duracion_min: int = 30, resumen: str | None = None,
    descripcion: str | None = None, telefono: str | None = None, nombre: str | None = None,
    datos: dict | None = None,
) -> dict:
    """Crea una cita con la SERVICE ACCOUNT (calendario compartido). `inicio` puede venir
    naive (se asume zona de la agenda) o aware. Si no se pasa `resumen`, se arma uno básico."""
    resumen = resumen or (f"Cita: {nombre}" if nombre else "Cita")
    return await asyncio.to_thread(
        lambda: _crear_evento_sync(_get_service(), calendar_id, inicio, duracion_min, resumen,
                                   descripcion, telefono, nombre, datos))


async def crear_evento_con_creds(
    creds, inicio: datetime, *, calendar_id: str = "primary", duracion_min: int = 30,
    resumen: str | None = None, descripcion: str | None = None, datos: dict | None = None,
) -> dict:
    """Crea una cita en el Google Calendar DEL USUARIO con sus credenciales OAuth propias.
    `calendar_id='primary'` = su calendario principal. Cliente y alta van en un hilo."""
    resumen = resumen or "Bloque (4G)"
    return await asyncio.to_thread(
        lambda: _crear_evento_sync(_service_de_creds(creds), calendar_id, inicio, duracion_min,
                                   resumen, descripcion, None, None, datos))


async def buscar_eventos(calendar_id: str, telefono: str, desde: datetime | None = None) -> list[dict]:
    """Citas futuras de un cliente (por su teléfono), ordenadas por inicio. Para cancelar:
    se leen de vuelta y se confirma antes de borrar (no borramos a ciegas)."""
    return await asyncio.to_thread(_buscar_eventos_sync, calendar_id, telefono, desde)


async def borrar_evento(calendar_id: str, event_id: str) -> bool:
    """Cancela (borra) una cita por su event_id. Idempotente."""
    return await asyncio.to_thread(_borrar_evento_sync, calendar_id, event_id)
