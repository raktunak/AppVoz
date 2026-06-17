"""Relay de TELEFONÍA: Telnyx Media Streaming (PSTN/SIP) ⇄ backend.

  Llamante ──SIP──► Telnyx ──webhook──► POST /telnyx/voice   (contestamos + streaming_start)
                    Telnyx ◄──WSS──► /ws/telnyx              (audio en ambos sentidos)

FASE A (esto, smoke-test SIN Gemini): el WS hace ECO — devuelve el audio que entra.
Sirve para validar TODA la cadena (webhook → answer → streaming → WS → bidireccional)
y, sobre todo, para VER en los logs el esquema real de mensajes y el `media_format`
que manda Telnyx, antes de meter la complejidad de Gemini.

FASE B (siguiente): sustituir el eco por una sesión Gemini Live (reutilizando
`_build_config`/`_AcumuladorTurnos` de live_relay), con transcodificación L16 16k ⇄ 24k.

El protocolo WS de Telnyx Media Streaming va calcado al de Twilio: mensajes JSON con
`event` = connected | start | media | stop; el audio viaja en `media.payload` (base64).
Para DEVOLVER audio (bidireccional) mandamos {"event":"media","media":{"payload": b64}}
y, para barge-in, {"event":"clear"}. Escribimos defensivo + log del primer `start`
porque los nombres exactos de algunos campos hay que confirmarlos contra la cuenta real.
"""
import json

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from loguru import logger

from .config import settings

router = APIRouter()

TELNYX_API = "https://api.telnyx.com/v2"

# Códec/tasa objetivo del stream: L16 16 kHz = la tasa de entrada de Gemini (mínima
# transcodificación en Fase B). En la Fase A de eco solo reenviamos el payload tal cual.
STREAM_CODEC = "L16"
STREAM_RATE = 16000


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
    """Webhook de la Voice API application. Telnyx avisa de los eventos de llamada y
    nosotros respondemos con comandos REST (answer + streaming_start).

    OJO (pendiente Fase 5): aquí debería verificarse la FIRMA Ed25519 del webhook
    (cabeceras telnyx-signature-ed25519 / telnyx-timestamp). De momento se omite para
    el smoke-test — cualquiera podría POSTear, pero a un ccid inválido el comando falla."""
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
        # Contestamos en cuanto entra; el streaming lo arrancamos al quedar contestada.
        await _telnyx_cmd(ccid, "answer")
    elif event == "call.answered":
        # URL pública del WS = mismo host que recibió el webhook (Cloud Run o túnel).
        host = request.headers.get("host")
        ws_url = settings.telnyx_public_ws_url or f"wss://{host}/ws/telnyx"
        logger.info(f"[telnyx] streaming_start -> {ws_url} ({STREAM_CODEC}@{STREAM_RATE})")
        await _telnyx_cmd(ccid, "streaming_start", {
            "stream_url": ws_url,
            "stream_track": "inbound_track",          # audio del llamante hacia nosotros
            "stream_codec": STREAM_CODEC,             # entrada en L16 (si Telnyx puede transcodificar)
            "stream_bidirectional_mode": "rtp",       # queremos devolver audio
            "stream_bidirectional_codec": STREAM_CODEC,
            "stream_bidirectional_sampling_rate": STREAM_RATE,
            "stream_bidirectional_target_legs": "self",  # el audio inyectado lo oye el llamante (1 solo leg)
        })
    # call.hangup, streaming.started/stopped, etc.: solo log; respondemos 200 siempre.
    return {}


@router.websocket("/ws/telnyx")
async def ws_telnyx(ws: WebSocket):
    """WS del media-stream de Telnyx. FASE A: ECO — todo lo que entra se devuelve.
    Loguea el primer `start` entero para conocer el `media_format` real."""
    await ws.accept()
    logger.info("[telnyx] WS conectado (eco)")
    stream_id = None
    n_media = 0
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                logger.info("[telnyx] WS disconnect")
                return
            raw = msg.get("text")
            if not raw:
                # Telnyx manda JSON en texto; si llega binario, lo ignoramos (no esperado).
                continue
            try:
                data = json.loads(raw)
            except Exception:
                logger.warning(f"[telnyx] frame no-JSON: {raw[:200]}")
                continue

            event = data.get("event")
            if event == "media":
                n_media += 1
                payload = (data.get("media") or {}).get("payload")
                if payload:
                    out = {"event": "media", "media": {"payload": payload}}
                    if stream_id:
                        out["stream_id"] = stream_id
                    await ws.send_text(json.dumps(out))
                if n_media in (1, 50, 250):   # muestreo para no inundar el log
                    logger.info(f"[telnyx] media #{n_media} (eco) len_b64={len(payload or '')}")
            elif event == "start":
                stream_id = data.get("stream_id") or (data.get("start") or {}).get("stream_id")
                logger.info(f"[telnyx] START stream_id={stream_id} :: {json.dumps(data)[:900]}")
            elif event == "connected":
                logger.info(f"[telnyx] CONNECTED :: {raw[:300]}")
            elif event == "stop":
                logger.info(f"[telnyx] STOP (total media={n_media})")
                return
            else:
                logger.info(f"[telnyx] evento '{event}' :: {raw[:300]}")
    except WebSocketDisconnect:
        logger.info("[telnyx] WS cerrado")
    except Exception:
        logger.exception("[telnyx] ERROR en /ws/telnyx")
    finally:
        try:
            await ws.close()
        except Exception:
            pass
