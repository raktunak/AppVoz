"""Relay de voz DIRECTO a Gemini Live (sin Pipecat, sin WebRTC) — sobre VERTEX AI.

Navegador  ──WebSocket(PCM 16kHz)──►  FastAPI  ──►  Gemini Live API (Vertex AI)
           ◄──WebSocket(PCM 24kHz)──           ◄──  (audio + transcripción + uso)

El backend queda EN MEDIO de los dos sentidos (clave para RAG/logging futuros) sin
perder inmersión. El VAD automático de Gemini Live no dispara fiablemente por esta vía,
así que detectamos el turno nosotros con un VAD por energía y se lo señalizamos
(activity_start / activity_end). Voz nativa + barge-in se mantienen.

BANCO DE PRUEBAS: el cliente envía como PRIMER mensaje un JSON de configuración
{type:"config", model, voice, system_instruction}; el relay construye la sesión Live
con esos valores (validados contra whitelist). Además reenvía al navegador el CONSUMO
real de tokens (usage_metadata) que devuelve la API, para medir cuánto gasta cada llamada.
"""
import array
import asyncio
import json
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
from loguru import logger

from .config import settings
from .persona import SALON_PERSONA

router = APIRouter()

# Auth Vertex por ADC: la SA appvoz-voice (la misma que usa Chirp 3 HD).
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", settings.google_application_credentials)
_client = genai.Client(
    vertexai=True,
    project=settings.gcp_project_id,
    location=settings.gcp_live_location,
)

# --- Matriz de capacidades por modelo (opción (a): curada a mano desde la doc oficial) ---
# Cada modelo Live admite distinta config. Pasar una voz no soportada, o fijar idioma en
# native-audio, hace que la API RECHACE la sesión → por eso el panel se adapta al modelo.
# (gemini-2.0-flash-live-001 se omite: APAGADO el 2025-12-09.)
NATIVE_VOICES = [
    "Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina",
    "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar", "Alnilam", "Schedar",
    "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia",
    "Sadaltager", "Sulafat",
]
CASCADE_VOICES = ["Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr"]
CASCADE_LANGS = [
    "es-ES", "es-US", "en-US", "en-GB", "fr-FR", "de-DE", "it-IT", "pt-BR", "nl-NL",
    "ja-JP", "ko-KR", "cmn-CN", "hi-IN", "ar-XA", "ru-RU", "pl-PL", "tr-TR", "vi-VN",
    "id-ID", "th-TH",
]

# Precios oficiales Live API familia 2.5 Flash (USD por 1M tokens). Audio más caro que texto.
PRICING_25 = {"audio_in": 3.0, "audio_out": 12.0, "text_in": 0.5, "text_out": 2.0}
USD_EUR = 0.92  # conversión aproximada (el cambio fluctúa)

MODELS_CAPS = {
    "gemini-live-2.5-flash-native-audio": {
        "label": "2.5 Flash · Native Audio — más inmersivo (afecto + proactividad)",
        "voices": NATIVE_VOICES,
        "default_voice": "Puck",
        "language": {"configurable": False, "note": "Automático/multilingüe: el modelo elige el idioma."},
        "features": {"affective_dialog": True, "proactivity": True},
        "generation": {"temperature": True, "max_output_tokens": True},
        "response_modalities": ["AUDIO"],
        "pricing": PRICING_25,
    },
    "gemini-live-2.5-flash": {
        "label": "2.5 Flash · Half-cascade — idioma configurable, sin afecto",
        "voices": CASCADE_VOICES,
        "default_voice": "Puck",
        "language": {"configurable": True, "codes": CASCADE_LANGS, "default": "es-ES",
                     "note": "BCP-47 configurable (STT→LLM→TTS)."},
        "features": {"affective_dialog": False, "proactivity": False},
        "generation": {"temperature": True, "max_output_tokens": True},
        "response_modalities": ["AUDIO", "TEXT"],
        "pricing": PRICING_25,
    },
}
MODELS = list(MODELS_CAPS.keys())
DEFAULT_MODEL = MODELS[0]
DEFAULT_VOICE = MODELS_CAPS[DEFAULT_MODEL]["default_voice"]

SPEECH_PEAK = 1000   # pico de amplitud >= esto = voz (silencio ~200-350, voz ~8000-15000)
END_SILENCE = 12     # ~1s de silencio (frames de ~80ms) para cerrar el turno


@router.get("/api/live/defaults")
async def live_defaults():
    """Fuente de verdad para el panel del navegador: matriz de capacidades por modelo."""
    return {
        "models": MODELS,
        "default_model": DEFAULT_MODEL,
        "caps": MODELS_CAPS,
        "persona": SALON_PERSONA,
        "location": settings.gcp_live_location,
        "usd_eur": USD_EUR,
    }


def _build_config(cfg: dict) -> tuple[str, types.LiveConnectConfig]:
    """Construye el LiveConnectConfig por conexión según las CAPACIDADES del modelo
    elegido: solo aplica voz/idioma/features que ese modelo admite (lo demás se ignora,
    para no provocar que la API rechace la sesión)."""
    model = cfg.get("model") if cfg.get("model") in MODELS_CAPS else DEFAULT_MODEL
    caps = MODELS_CAPS[model]
    voice = cfg.get("voice") if cfg.get("voice") in caps["voices"] else caps["default_voice"]
    system = (cfg.get("system_instruction") or "").strip() or SALON_PERSONA

    speech_kwargs = {
        "voice_config": types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
        )
    }
    # Idioma: SOLO si el modelo lo admite (half-cascade). En native-audio es automático.
    lang = cfg.get("language")
    if caps["language"].get("configurable") and lang and lang in caps["language"].get("codes", []):
        speech_kwargs["language_code"] = lang

    kwargs = dict(
        response_modalities=["AUDIO"],
        system_instruction=system,
        speech_config=types.SpeechConfig(**speech_kwargs),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # VAD automático de Gemini DESACTIVADO (no dispara fiable): señalizamos el turno nosotros
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
        ),
    )

    # Generación (ambos modelos): solo si el cliente manda un valor.
    temp = cfg.get("temperature")
    if temp not in (None, ""):
        try:
            kwargs["temperature"] = float(temp)
        except (TypeError, ValueError):
            pass
    mot = cfg.get("max_output_tokens")
    if mot:
        try:
            kwargs["max_output_tokens"] = int(mot)
        except (TypeError, ValueError):
            pass

    # Features EXCLUSIVAS de native-audio (opt-in, experimental). Defensivo: si el SDK/Vertex
    # no las acepta, se loguea y se sigue sin ellas (solo afecta cuando el usuario las activa).
    feats = caps["features"]
    try:
        if feats.get("affective_dialog") and cfg.get("affective_dialog"):
            kwargs["enable_affective_dialog"] = True
        if feats.get("proactivity") and cfg.get("proactivity"):
            kwargs["proactivity"] = types.ProactivityConfig(proactive_audio=True)
    except Exception:
        logger.exception("no pude activar feature native-audio; sigo sin ella")

    return model, types.LiveConnectConfig(**kwargs)


async def _recibir_config(ws: WebSocket) -> dict | None:
    """Primer mensaje del cliente: JSON {type:'config', ...}. Devuelve el dict de config,
    {} si no vino (usa defaults), o None si el cliente se desconectó en el handshake."""
    try:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return None
        txt = msg.get("text")
        if txt:
            data = json.loads(txt)
            if data.get("type") == "config":
                return data
        return {}
    except Exception:
        logger.exception("handshake de config falló; uso defaults")
        return {}


def _modalidades(details) -> dict:
    """ModalityTokenCount[] -> {modalidad: tokens} (defensivo ante cambios de la API)."""
    out: dict = {}
    for d in (details or []):
        mod = getattr(d, "modality", None)
        cnt = getattr(d, "token_count", None)
        if mod is not None:
            out[str(getattr(mod, "name", mod))] = cnt
    return out


def _usage_dict(um) -> dict:
    """Serializa usage_metadata de Live a un dict simple para el navegador."""
    return {
        "total": getattr(um, "total_token_count", None),
        "prompt": getattr(um, "prompt_token_count", None),
        "response": getattr(um, "response_token_count", None),
        "prompt_by_modality": _modalidades(getattr(um, "prompt_tokens_details", None)),
        "response_by_modality": _modalidades(getattr(um, "response_tokens_details", None)),
    }


async def _browser_to_gemini(ws: WebSocket, session):
    """Audio del navegador → Gemini, con VAD por energía que señaliza el turno."""
    in_speech, sil = False, 0
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                if in_speech:
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                logger.info("browser->gemini: navegador desconectó")
                return
            audio = msg.get("bytes")
            if not audio:
                continue
            try:
                s = array.array("h"); s.frombytes(audio)
                peak = max((abs(x) for x in s), default=0)
            except Exception:
                peak = 0

            if peak >= SPEECH_PEAK:
                if not in_speech:
                    await session.send_realtime_input(activity_start=types.ActivityStart())
                    in_speech = True
                sil = 0
            elif in_speech:
                sil += 1
                if sil >= END_SILENCE:
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                    in_speech = False
                    sil = 0

            await session.send_realtime_input(
                audio=types.Blob(data=audio, mime_type="audio/pcm;rate=16000")
            )
    except WebSocketDisconnect:
        logger.info("browser->gemini: WS cerrado")
    except Exception:
        logger.exception("browser->gemini ERROR")


async def _gemini_to_browser(ws: WebSocket, session):
    """Audio + transcripción + consumo de Gemini → navegador. receive() entrega un turno
    y se cierra, por eso el while True lo reabre para el siguiente."""
    try:
        while True:
            async for response in session.receive():
                # Consumo de tokens (puede venir en cualquier mensaje del turno)
                um = getattr(response, "usage_metadata", None)
                if um:
                    await ws.send_text(json.dumps({"type": "usage", "usage": _usage_dict(um)}))
                sc = response.server_content
                if not sc:
                    continue
                if sc.interrupted:
                    await ws.send_text(json.dumps({"type": "interrupted"}))
                if sc.model_turn:
                    for part in (sc.model_turn.parts or []):
                        inline = getattr(part, "inline_data", None)
                        if inline and inline.data:
                            await ws.send_bytes(inline.data)
                it = getattr(sc, "input_transcription", None)
                if it and getattr(it, "text", None):
                    await ws.send_text(json.dumps({"type": "user", "text": it.text}))
                ot = getattr(sc, "output_transcription", None)
                if ot and getattr(ot, "text", None):
                    await ws.send_text(json.dumps({"type": "bot", "text": ot.text}))
    except Exception:
        logger.exception("gemini->browser ERROR")


@router.websocket("/ws/call")
async def ws_call(ws: WebSocket):
    await ws.accept()
    logger.info("WS navegador conectado; esperando config...")
    cfg = await _recibir_config(ws)
    if cfg is None:
        logger.info("cliente se fue en el handshake")
        return
    model, live_config = _build_config(cfg)
    logger.info(f"abriendo Gemini Live (Vertex) model={model} voice={cfg.get('voice', DEFAULT_VOICE)}")
    try:
        async with _client.aio.live.connect(model=model, config=live_config) as session:
            logger.info("Gemini Live CONECTADO; ready (hablas tú primero)")
            await ws.send_text(json.dumps({"type": "ready", "model": model}))
            up = asyncio.create_task(_browser_to_gemini(ws, session))
            down = asyncio.create_task(_gemini_to_browser(ws, session))
            _, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            logger.info("Llamada finalizada")
    except WebSocketDisconnect:
        logger.info("WS navegador desconectado")
    except Exception as e:
        logger.exception("Error en /ws/call")
        try:
            await ws.send_text(json.dumps({"type": "error", "detail": str(e)}))
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
