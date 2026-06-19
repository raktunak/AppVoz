"""Vertical ONBOARDING 4G: la entrevistadora por voz que rellena el Canva en vivo.

Navegador (PCM 16k) ⇄ FastAPI /ws/4g ⇄ Gemini Live (Vertex). Reutiliza del relay web
(`live_relay.py`) el cliente Gemini, `_build_config`, el VAD por energía y la subida de
audio (`_browser_to_gemini`). Lo NUEVO aquí: tras cada turno completo, extraemos con Flash
los campos de la SECCIÓN activa del Canva (`canva4g`), los empujamos al navegador para que el
stepper se rellene en directo, y avanzamos de sección cuando el código la da por completa.
Al cerrar la última sección ("Primer bloque"), se agenda en Google Calendar (`agenda.py`),
de forma DETERMINISTA (no dependemos del tool-calling nativo del modelo).

Protocolo hacia el navegador (JSON salvo el audio, que va binario PCM 24k):
  ready    {secciones, activa, canva}    · al conectar
  user/bot {text}                        · transcripción en streaming
  canva    {canva}                       · estado completo del Canva tras cada extracción
  section  {activa}                      · cambió la sección activa
  booked   {ok, event|error}             · resultado de agendar el primer bloque
  interrupted {}                         · barge-in (vaciar reproducción)
"""
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google.genai import types
from loguru import logger

from . import agenda, canva4g, persistence
from .config import settings
from .live_relay import _browser_to_gemini, _build_config, _client, _vad_params

router = APIRouter()

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _firma_oblig(seccion: dict, datos: dict | None):
    """Firma de los campos obligatorios de una sección, para detectar ESTABILIDAD entre turnos
    (avanzar solo cuando el dato se repite → evita avanzar con el ruido del primer turno)."""
    datos = datos or {}
    if seccion.get("tipo") == "lista":
        return len(datos.get(seccion["lista"]) or [])
    return tuple(
        (datos.get(c) or "").strip() if isinstance(datos.get(c), str) else datos.get(c)
        for c in seccion["obligatorios"]
    )


async def _cargar_cfg_4g() -> tuple[dict, str]:
    """Config (persona/voz) y subject del servicio '4g'. Defaults si no existe el servicio."""
    try:
        svc = await persistence.resolver_servicio("4g")
    except Exception:
        logger.exception("[4g] error resolviendo servicio '4g'")
        svc = None
    if svc:
        return (svc.get("cfg") or {}), (svc.get("subject_id") or "libro-4g")
    logger.warning("[4g] no existe servicio '4g'; uso config por defecto")
    return {}, "libro-4g"


def _fecha_ctx() -> str:
    ahora = datetime.now(ZoneInfo(settings.agenda_timezone))
    return f"{DIAS[ahora.weekday()]} {ahora.strftime('%d/%m/%Y %H:%M')} ({settings.agenda_timezone})"


def _preparar_prompt(cfg: dict, fecha_str: str, canva_prev: dict) -> dict:
    """Añade al system_instruction la fecha de hoy (el modelo no la sabe) y, si la persona ya
    empezó, un resumen del Canva para que la guía RETOME con naturalidad sin repetir."""
    base = (cfg.get("system_instruction") or "").strip()
    extra = (
        f"\n\nContexto: hoy es {fecha_str}. Cuando propongas o confirmes un día y una hora, "
        f"resuélvelos a partir de esta fecha y confírmalos en voz alta antes de cerrar."
    )
    resumen = canva4g.resumen_canva(canva_prev)
    if resumen:
        extra += (
            "\n\nESTA PERSONA YA EMPEZÓ EN UNA SESIÓN ANTERIOR. Salúdala de nuevo con calidez, "
            "NO repitas lo ya hecho y retoma por lo que falta. Ya tiene capturado:\n" + resumen
        )
    return {**cfg, "system_instruction": base + extra}


async def _extraer_y_push(ws: WebSocket, shared: dict):
    """Extrae la sección activa de la conversación, actualiza el Canva, lo empuja al
    navegador y avanza de sección si el código la da por completa. Best-effort."""
    idx = shared["sec_idx"]
    if idx >= len(canva4g.SECCIONES):
        return
    seccion = canva4g.SECCIONES[idx]
    conv = shared.get("conv", "")
    if not conv.strip():
        return
    datos = await canva4g.extraer_seccion(seccion["key"], conv, shared["fecha_str"])
    if not datos:
        return
    # Merge no destructivo (no pisa datos ya capturados con vacíos).
    prev = shared["canva"].get(seccion["key"]) or {}
    shared["canva"][seccion["key"]] = canva4g.merge_seccion(seccion, prev, datos)
    logger.info(f"[4g] extracción '{seccion['key']}' -> {datos}")
    try:
        await ws.send_text(json.dumps({"type": "canva", "canva": shared["canva"]}))
    except Exception:
        return
    # Persistencia incremental (best-effort).
    try:
        await canva4g.guardar_canva(shared["user_id"], shared["canva"], shared["subject_id"])
    except Exception:
        logger.exception("[4g] no pude guardar canva (incremental)")
    # Compuerta CON CONFIRMACIÓN: avanzar solo si la sección está completa Y el dato es ESTABLE
    # (la misma información en dos extracciones seguidas). Así no se avanza con un dato del primer
    # turno (saludo/ruido, p.ej. tomar "gan" como nombre) y se da margen a que la guía confirme.
    key = seccion["key"]
    cur = shared["canva"].get(key)
    firmas = shared.setdefault("_firma", {})
    if canva4g.seccion_completa(seccion, cur):
        firma = _firma_oblig(seccion, cur)
        if firmas.get(key) == firma:                      # estable → confirmada
            if key == "bloque":
                await _agendar_bloque(ws, shared)
            if shared["sec_idx"] == idx:
                shared["sec_idx"] = min(idx + 1, len(canva4g.SECCIONES))
                try:
                    await ws.send_text(json.dumps({"type": "section", "activa": shared["sec_idx"]}))
                except Exception:
                    pass
                logger.info(f"[4g] sección '{key}' CONFIRMADA → activa={shared['sec_idx']}")
        else:                                             # 1ª vez completa: espera confirmación
            firmas[key] = firma
            logger.info(f"[4g] sección '{key}' completa; espero 2ª confirmación")
    else:
        firmas.pop(key, None)                             # dejó de estar completa → reset


async def _agendar_bloque(ws: WebSocket, shared: dict):
    """Agenda en Google Calendar el primer bloque (rol + fecha_hora_iso). Idempotente."""
    if shared.get("_booked"):
        return
    bloque = shared["canva"].get("bloque") or {}
    iso, rol = bloque.get("fecha_hora_iso"), bloque.get("rol")
    if not iso or not rol:
        return
    cal = settings.calendar_id
    if not cal:
        await ws.send_text(json.dumps({"type": "booked", "ok": False, "error": "Falta CALENDAR_ID"}))
        return
    try:
        inicio = datetime.fromisoformat(iso)
    except Exception:
        logger.warning(f"[4g] fecha_hora_iso no parseable: {iso}")
        await ws.send_text(json.dumps({"type": "booked", "ok": False, "error": "fecha no válida"}))
        return
    try:
        ev = await agenda.crear_evento(
            cal, inicio, duracion_min=120, resumen=f"{rol} (4G)",
            descripcion="Primer bloque creado en el onboarding 4G.",
            telefono=shared["user_id"], datos={"rol": rol, "origen": "4g"},
        )
        shared["_booked"] = True
        await ws.send_text(json.dumps({"type": "booked", "ok": True, "event": ev}))
        logger.info(f"[4g] bloque agendado rol='{rol}' inicio={iso} event={ev.get('event_id')}")
    except Exception as e:
        logger.exception("[4g] no pude agendar el bloque")
        await ws.send_text(json.dumps({"type": "booked", "ok": False, "error": str(e)}))


async def _gemini_to_browser_4g(ws: WebSocket, session, shared: dict):
    """Audio + transcripción de Gemini → navegador, acumulando la conversación. Al cierre
    de cada turno (turn_complete) dispara la extracción de la sección activa (en background,
    para no bloquear el audio)."""
    try:
        while True:
            async for response in session.receive():
                sc = response.server_content
                if not sc:
                    continue
                if sc.interrupted:
                    shared["bot_speaking"] = False
                    logger.info("[4g] INTERRUPTED (barge-in detectado)")
                    await ws.send_text(json.dumps({"type": "interrupted"}))
                if getattr(sc, "generation_complete", None) or getattr(sc, "turn_complete", None):
                    shared["bot_speaking"] = False
                if getattr(sc, "turn_complete", None):
                    # Fin de intercambio: extraer la sección activa (sin bloquear el loop).
                    asyncio.create_task(_extraer_y_push(ws, shared))
                if sc.model_turn:
                    for part in (sc.model_turn.parts or []):
                        inline = getattr(part, "inline_data", None)
                        if inline and inline.data:
                            shared["bot_speaking"] = True
                            await ws.send_bytes(inline.data)
                it = getattr(sc, "input_transcription", None)
                if it and getattr(it, "text", None):
                    if shared.get("_last") != "user":
                        shared["conv"] = shared.get("conv", "") + "\nPersona: "
                        shared["_last"] = "user"
                    shared["conv"] += it.text
                    await ws.send_text(json.dumps({"type": "user", "text": it.text}))
                ot = getattr(sc, "output_transcription", None)
                if ot and getattr(ot, "text", None):
                    if shared.get("_last") != "bot":
                        shared["conv"] = shared.get("conv", "") + "\nGuía: "
                        shared["_last"] = "bot"
                    shared["conv"] += ot.text
                    await ws.send_text(json.dumps({"type": "bot", "text": ot.text}))
    except Exception:
        logger.exception("[4g] gemini->browser ERROR")


@router.websocket("/ws/4g")
async def ws_4g(ws: WebSocket):
    """Onboarding 4G por voz. El navegador manda primero {type:'config', user_id} y luego
    audio PCM16 16k; nosotros conducimos la entrevista con la persona del servicio '4g' y
    rellenamos el Canva en vivo."""
    await ws.accept()
    logger.info("[4g] WS conectado; esperando config…")
    user_id = "anonimo"
    try:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        txt = msg.get("text")
        if txt:
            data = json.loads(txt)
            user_id = (data.get("user_id") or "anonimo").strip() or "anonimo"
    except Exception:
        logger.exception("[4g] handshake de config falló; sigo con anonimo")

    cfg, subject_id = await _cargar_cfg_4g()
    fecha_str = _fecha_ctx()
    canva_prev = await canva4g.obtener_canva(user_id)
    cfg = _preparar_prompt(cfg, fecha_str, canva_prev)
    model, live_config = _build_config(cfg)
    vad = _vad_params(cfg)

    shared = {
        "bot_speaking": False, "user_id": user_id, "subject_id": subject_id,
        "canva": canva_prev or {}, "sec_idx": canva4g.primera_incompleta(canva_prev),
        "fecha_str": fecha_str, "conv": "", "_last": None,
        "no_barge": True,   # anti-eco: el micro se ignora mientras Faro habla
    }
    logger.info(f"[4g] sesión user={user_id} model={model} voz={cfg.get('voice')} "
                f"sec_idx={shared['sec_idx']}")
    try:
        async with _client.aio.live.connect(model=model, config=live_config) as session:
            await ws.send_text(json.dumps({
                "type": "ready", "model": model,
                "secciones": canva4g.secciones_publicas(),
                "activa": shared["sec_idx"], "canva": shared["canva"],
            }))
            up = asyncio.create_task(_browser_to_gemini(ws, session, vad, shared))
            down = asyncio.create_task(_gemini_to_browser_4g(ws, session, shared))
            # Faro habla PRIMERO: disparamos su presentación sin esperar a que el usuario diga "hola".
            # Marcamos bot_speaking ANTES para que el saludo exija voz sostenida (barge_frames) y un
            # pico de ruido/eco no lo corte; el turn_complete del saludo lo vuelve a poner en False.
            shared["bot_speaking"] = True
            try:
                await session.send_client_content(
                    turns=[types.Content(role="user", parts=[types.Part(
                        text="Estoy listo para empezar. Preséntate brevemente como Faro y "
                             "pregúntame solo mi nombre.")])],
                    turn_complete=True,
                )
            except Exception:
                logger.exception("[4g] no pude disparar el saludo inicial (el usuario puede hablar primero)")
            _, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            logger.info("[4g] sesión finalizada")
    except WebSocketDisconnect:
        logger.info("[4g] navegador desconectado")
    except Exception as e:
        logger.exception("[4g] error en /ws/4g")
        try:
            await ws.send_text(json.dumps({"type": "error", "detail": str(e)}))
        except Exception:
            pass
    finally:
        try:
            await canva4g.guardar_canva(user_id, shared["canva"], subject_id)
        except Exception:
            logger.exception("[4g] no pude guardar el canva final")
        try:
            await ws.close()
        except Exception:
            pass


@router.post("/api/4g/reset")
async def reset_4g(payload: dict):
    """Reinicia el onboarding de un usuario PARA PRUEBAS: borra su Canva (tabla canva_4g) y
    sus citas de Calendar creadas por el 4g (las que llevan su user_id). Solo afecta a ese
    user_id, no a otros usuarios de prueba."""
    user_id = (payload.get("user_id") or "").strip()
    if not user_id:
        return {"ok": False, "error": "falta user_id"}
    borrados = 0
    cal = settings.calendar_id
    if cal:
        try:
            desde = datetime(2020, 1, 1, tzinfo=ZoneInfo(settings.agenda_timezone))
            for e in await agenda.buscar_eventos(cal, user_id, desde):
                if await agenda.borrar_evento(cal, e["event_id"]):
                    borrados += 1
        except Exception:
            logger.exception("[4g] reset: fallo borrando eventos de Calendar")
    await canva4g.borrar_canva(user_id)
    logger.info(f"[4g] reset user={user_id}: Canva borrado, {borrados} evento(s) de Calendar")
    return {"ok": True, "eventos_borrados": borrados}


@router.get("/api/4g/canva")
async def get_canva(user_id: str):
    """Canva guardado + sección activa (para pintar el estado real al entrar; arregla que el
    stepper marcara como hecha una sección por existir la clave en vez de por estar completa)."""
    canva = await canva4g.obtener_canva(user_id)
    return {"canva": canva, "secciones": canva4g.secciones_publicas(),
            "activa": canva4g.primera_incompleta(canva)}
