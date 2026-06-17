"""Relay de TELEFONÍA: Telnyx Media Streaming (PSTN/SIP) ⇄ Gemini Live.

  Llamante ──SIP──► Telnyx ──webhook──► POST /telnyx/voice   (contestamos + streaming_start)
                    Telnyx ◄──WSS──► /ws/telnyx ◄──► Gemini Live (Vertex)

Mismo patrón "backend en medio" que `live_relay.py`, pero el transporte es el protocolo
de Media Streaming de Telnyx (JSON: connected | start | media | stop; audio en
`media.payload` base64). Reutilizamos del relay del navegador el cliente Gemini,
`_build_config`, el VAD por energía y `_AcumuladorTurnos`.

FORMATO (confirmado en el smoke-test): Telnyx entrega **L16 / 16 kHz / mono** = la tasa de
ENTRADA de Gemini → la entrada va passthrough (cero transcodificación). La SALIDA de Gemini
es PCM 24 kHz → la bajamos a 16 kHz (`audioop.ratecv`) y la devolvemos como frames `media`.
Para barge-in mandamos {"event":"clear"} (vacía el buffer de audio en curso en Telnyx).

FASE B (esto): persona fija `SALON_PERSONA`, sin RAG. La identidad del llamante (campo
`from` del `start`) se usa como user_id para la persistencia (via="telnyx").
"""
import array
import asyncio
import audioop
import base64
import collections
import json

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from google.genai import types
from loguru import logger

from . import persistence
from .config import settings
from .live_relay import (
    BARGE_MAX,
    _AcumuladorTurnos,
    _build_config,
    _client,
    _vad_params,
)

router = APIRouter()

TELNYX_API = "https://api.telnyx.com/v2"

# Códec/tasa objetivo del stream: L16 16 kHz (= entrada de Gemini, mínima transcodificación).
STREAM_CODEC = "L16"
STREAM_RATE = 16000
GEMINI_OUT_RATE = 24000          # Gemini Live emite PCM a 24 kHz
OUT_CHUNK = 640                  # 20 ms de L16 16k mono (320 muestras * 2 bytes)


async def _telnyx_cmd(ccid: str, action: str, body: dict | None = None) -> bool:
    """Lanza un comando de Call Control (answer, streaming_start, …) vía API v2.
    Devuelve True si Telnyx lo aceptó. No lanza: loguea el error y sigue."""
    if not settings.telnyx_api_key:
        logger.error("[telnyx] falta TELNYX_API_KEY; no puedo mandar comandos")
        return False
    url = f"{TELNYX_API}/calls/{ccid}/actions/{action}"
    headers = {"Authorization": f"Bearer {settings.telnyx_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=body or {})
        if r.status_code >= 300:
            logger.error(f"[telnyx] {action} -> {r.status_code}: {r.text[:400]}")
            return False
        logger.info(f"[telnyx] {action} OK")
        return True
    except Exception:
        logger.exception(f"[telnyx] excepción en comando {action}")
        return False


@router.post("/telnyx/voice")
async def telnyx_voice(request: Request):
    """Webhook de la Voice API application: al entrar la llamada la contestamos y, al
    quedar contestada, arrancamos el media-stream bidireccional hacia /ws/telnyx.

    OJO (pendiente Fase 5): falta verificar la FIRMA Ed25519 del webhook. De momento se
    omite para las pruebas — a un ccid inválido el comando falla, pero conviene cerrarlo."""
    try:
        body = await request.json()
    except Exception:
        logger.warning("[telnyx] webhook sin JSON válido")
        return {}

    data = body.get("data") or {}
    event = data.get("event_type")
    payload = data.get("payload") or {}
    ccid = payload.get("call_control_id")
    logger.info(
        f"[telnyx] webhook event={event} ccid={ccid} "
        f"from={payload.get('from')} to={payload.get('to')} dir={payload.get('direction')}"
    )

    if event == "call.initiated":
        await _telnyx_cmd(ccid, "answer")
    elif event == "call.answered":
        host = request.headers.get("host")
        ws_url = settings.telnyx_public_ws_url or f"wss://{host}/ws/telnyx"
        logger.info(f"[telnyx] streaming_start -> {ws_url} ({STREAM_CODEC}@{STREAM_RATE})")
        await _telnyx_cmd(ccid, "streaming_start", {
            "stream_url": ws_url,
            "stream_track": "inbound_track",
            "stream_codec": STREAM_CODEC,
            "stream_bidirectional_mode": "rtp",
            "stream_bidirectional_codec": STREAM_CODEC,
            "stream_bidirectional_sampling_rate": STREAM_RATE,
            "stream_bidirectional_target_legs": "self",
        })
    return {}


# --- Config de las llamadas telefónicas: la fija el panel (/call), la lee el relay ---
_CFG_KEYS = (
    "model", "voice", "language", "temperature", "max_output_tokens",
    "affective_dialog", "proactivity", "system_instruction",
    "mic_threshold", "end_silence", "barge_frames",
)


@router.get("/api/telnyx/config")
async def get_telnyx_config():
    """Config activa de las llamadas telefónicas (la última guardada desde el panel)."""
    return {"cfg": await persistence.obtener_config_telefono() or {}}


@router.post("/api/telnyx/config")
async def set_telnyx_config(payload: dict):
    """Guarda la selección actual del panel (voz/persona/modelo/VAD) para el teléfono."""
    cfg = {k: payload.get(k) for k in _CFG_KEYS}
    await persistence.guardar_config_telefono(cfg)
    logger.info(f"[telnyx] config de teléfono guardada: model={cfg.get('model')} "
                f"voice={cfg.get('voice')}")
    return {"ok": True, "cfg": cfg}


# --- Servicios telefónicos (capa multi-vertical): cada ruta/DID = persona+voz+corpus ---
@router.get("/api/servicios")
async def api_listar_servicios():
    return {"servicios": await persistence.listar_servicios()}


@router.post("/api/servicios")
async def api_guardar_servicio(payload: dict):
    """Crea/actualiza (UPSERT por `ruta`) un servicio con la config del panel."""
    nombre = (payload.get("nombre") or "").strip()
    ruta = (payload.get("ruta") or "").strip()
    subject_id = (payload.get("subject_id") or "demo").strip() or "demo"
    if not nombre or not ruta:
        return {"ok": False, "error": "nombre y ruta son obligatorios"}
    cfg = {k: payload.get(k) for k in _CFG_KEYS}
    sid = await persistence.guardar_servicio(
        nombre, ruta, subject_id, cfg, bool(payload.get("es_default")))
    logger.info(f"[telnyx] servicio guardado id={sid} nombre='{nombre}' ruta={ruta} subject={subject_id}")
    return {"ok": True, "id": sid}


@router.delete("/api/servicios/{servicio_id}")
async def api_borrar_servicio(servicio_id: int):
    await persistence.borrar_servicio(servicio_id)
    return {"ok": True}


async def _send_audio(ws: WebSocket, pcm16: bytes, stream_id: str | None):
    """Trocea PCM L16 16k en frames de ~20 ms y los manda a Telnyx como eventos `media`."""
    for i in range(0, len(pcm16), OUT_CHUNK):
        out = {"event": "media",
               "media": {"payload": base64.b64encode(pcm16[i:i + OUT_CHUNK]).decode()}}
        if stream_id:
            out["stream_id"] = stream_id
        await ws.send_text(json.dumps(out))


async def _telnyx_to_gemini(ws: WebSocket, session, vad: dict, shared: dict):
    """Audio del llamante (Telnyx) → Gemini, con el mismo VAD por energía del relay web
    (histéresis + anti-pico + anti-corte). La entrada ya es L16 16k → passthrough."""
    open_peak, keep_peak = vad["open_peak"], vad["keep_peak"]
    start_frames, end_silence = vad["start_frames"], vad["end_silence"]
    barge_frames = vad["barge_frames"]
    in_speech, sil, hot = False, 0, 0
    prefix = collections.deque(maxlen=BARGE_MAX)
    dbg_max, dbg_n = 0, 0
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                if in_speech:
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                logger.info("[telnyx] WS disconnect (in)")
                return
            raw = msg.get("text")
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            event = data.get("event")
            if event == "start":
                start = data.get("start") or {}
                shared["stream_id"] = data.get("stream_id") or start.get("stream_id")
                shared["from"] = start.get("from")
                logger.info(f"[telnyx] START stream_id={shared['stream_id']} "
                            f"from={shared.get('from')} fmt={start.get('media_format')}")
                continue
            if event == "stop":
                if in_speech:
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                logger.info("[telnyx] STOP (in)")
                return
            if event != "media":
                continue
            payload = (data.get("media") or {}).get("payload")
            if not payload:
                continue
            audio = base64.b64decode(payload)
            try:
                s = array.array("h"); s.frombytes(audio)
                peak = max((abs(x) for x in s), default=0)
            except Exception:
                peak = 0

            if not in_speech:
                prefix.append(audio)
                need = barge_frames if shared.get("bot_speaking") else start_frames
                hot = min(need, hot + 1) if peak >= open_peak else max(0, hot - 1)
                dbg_max = max(dbg_max, peak); dbg_n += 1
                if dbg_n >= 100:                       # ~2 s: ayuda a tunear el VAD en banda telefónica
                    logger.info(f"[telnyx VAD] esperando voz: peak_max~{dbg_max} "
                                f"umbral={open_peak} hot={hot} need={need}")
                    dbg_max, dbg_n = 0, 0
                if hot >= need:
                    logger.info(f"[telnyx VAD] turno ABIERTO peak={peak}")
                    await session.send_realtime_input(activity_start=types.ActivityStart())
                    in_speech, sil, hot = True, 0, 0
                    for buf in list(prefix)[-need:]:
                        await session.send_realtime_input(
                            audio=types.Blob(data=buf, mime_type="audio/pcm;rate=16000"))
                    prefix.clear()
                continue

            await session.send_realtime_input(
                audio=types.Blob(data=audio, mime_type="audio/pcm;rate=16000"))
            if peak >= keep_peak:
                sil = 0
            else:
                sil += 1
                if sil >= end_silence:
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                    in_speech, sil = False, 0
    except WebSocketDisconnect:
        logger.info("[telnyx] WS cerrado (in)")
    except Exception:
        logger.exception("[telnyx] ERROR telnyx->gemini")


async def _gemini_to_telnyx(ws: WebSocket, session, acc: "_AcumuladorTurnos", shared: dict):
    """Audio + transcripción de Gemini → Telnyx. La salida 24 kHz se baja a 16 kHz y se
    trocea en frames `media`. En `interrupted` mandamos `clear` (barge-in: vacía el buffer)."""
    rs_state = None
    try:
        while True:
            async for response in session.receive():
                sc = response.server_content
                if not sc:
                    continue
                if sc.interrupted:
                    shared["bot_speaking"] = False
                    out = {"event": "clear"}
                    if shared.get("stream_id"):
                        out["stream_id"] = shared["stream_id"]
                    await ws.send_text(json.dumps(out))
                if getattr(sc, "generation_complete", None) or getattr(sc, "turn_complete", None):
                    shared["bot_speaking"] = False
                if sc.model_turn:
                    for part in (sc.model_turn.parts or []):
                        inline = getattr(part, "inline_data", None)
                        if inline and inline.data:
                            shared["bot_speaking"] = True
                            pcm16, rs_state = audioop.ratecv(
                                inline.data, 2, 1, GEMINI_OUT_RATE, STREAM_RATE, rs_state)
                            await _send_audio(ws, pcm16, shared.get("stream_id"))
                it = getattr(sc, "input_transcription", None)
                if it and getattr(it, "text", None):
                    acc.add_user(it.text)
                ot = getattr(sc, "output_transcription", None)
                if ot and getattr(ot, "text", None):
                    acc.add_bot(ot.text)
    except Exception:
        logger.exception("[telnyx] ERROR gemini->telnyx")


@router.websocket("/ws/telnyx")
async def ws_telnyx(ws: WebSocket):
    """Media-stream de Telnyx ⇄ sesión Gemini Live. ENRUTA por el número marcado (`to`):
    cada servicio (peluquería, jardines…) tiene su voz/persona/subject_id. Si no hay
    servicio para esa ruta, usa el `es_default` o la config por defecto del panel. El
    llamante habla primero."""
    await ws.accept()
    logger.info("[telnyx] WS conectado")
    # 1) Esperar el `start` para saber a qué servicio enruta (campo `to`).
    to = frm = stream_id = None
    while True:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        raw = msg.get("text")
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        ev = data.get("event")
        if ev == "start":
            st = data.get("start") or {}
            to, frm = st.get("to"), st.get("from")
            stream_id = data.get("stream_id") or st.get("stream_id")
            logger.info(f"[telnyx] START to={to} from={frm} fmt={st.get('media_format')}")
            break
        if ev == "stop":
            return
    # 2) Resolver el servicio por la parte-de-usuario del `to` ('100@...' -> '100').
    ruta = (to or "").split("@")[0].strip()
    svc = None
    try:
        svc = await persistence.resolver_servicio(ruta) if ruta else None
    except Exception:
        logger.exception("[telnyx] error resolviendo servicio")
    if svc:
        cfg = svc.get("cfg") or {}
        subject_id = svc.get("subject_id") or "demo"
        logger.info(f"[telnyx] servicio='{svc.get('nombre')}' ruta={ruta} subject={subject_id}")
    else:
        try:
            cfg = await persistence.obtener_config_telefono() or {}
        except Exception:
            cfg = {}
        subject_id = "demo"
        logger.info(f"[telnyx] sin servicio para ruta='{ruta}'; uso config por defecto del panel")
    # 3) Abrir Gemini con la config resuelta.
    model, live_config = _build_config(cfg)
    vad = _vad_params(cfg)
    logger.info(f"[telnyx] sesión model={model} voice={cfg.get('voice', 'default')} "
                f"subject={subject_id} vad_open={vad['open_peak']}")
    acc = _AcumuladorTurnos()
    shared = {"stream_id": stream_id, "bot_speaking": False, "from": frm, "subject_id": subject_id}
    try:
        async with _client.aio.live.connect(model=model, config=live_config) as session:
            logger.info(f"[telnyx] Gemini Live CONECTADO model={model}")
            up = asyncio.create_task(_telnyx_to_gemini(ws, session, vad, shared))
            down = asyncio.create_task(_gemini_to_telnyx(ws, session, acc, shared))
            _, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            logger.info("[telnyx] llamada finalizada")
    except Exception as e:
        logger.exception("[telnyx] error en /ws/telnyx")
    finally:
        # Persistir la conversación (best-effort: nunca rompe el cierre del WS).
        try:
            turnos = acc.finalizar()
            if turnos:
                user_id = (shared.get("from") or "telefono").strip() or "telefono"
                session_id = await persistence.crear_sesion(
                    shared.get("subject_id") or "demo", user_id, via="telnyx")
                n = await persistence.guardar_turnos(session_id, turnos)
                await persistence.cerrar_sesion(session_id, n)
                asyncio.create_task(persistence.resumir_sesion(session_id))
                logger.info(f"[telnyx] sesión {session_id} persistida ({n} turnos)")
        except Exception:
            logger.exception("[telnyx] no pude persistir la sesión; se ignora")
        try:
            await ws.close()
        except Exception:
            pass
