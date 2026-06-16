"""Relay de voz DIRECTO a Gemini Live (sin Pipecat, sin WebRTC).

Navegador  ──WebSocket(PCM 16kHz)──►  FastAPI  ──►  Gemini Live API
           ◄──WebSocket(PCM 24kHz)──           ◄──  (audio + transcripción)

El backend queda EN MEDIO de los dos sentidos (clave para RAG/logging futuros) sin
perder inmersión (latencia despreciable). El VAD automático de Gemini Live no dispara
fiablemente por esta vía, así que detectamos el turno nosotros con un VAD por energía
y se lo señalizamos (activity_start / activity_end). Voz nativa + barge-in se mantienen.
"""
import array
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
from loguru import logger

from .config import settings
from .persona import SALON_PERSONA

router = APIRouter()
_client = genai.Client(api_key=settings.google_api_key)

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
VOICE = "Aoede"

CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=SALON_PERSONA,
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
        )
    ),
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
    # VAD automático de Gemini DESACTIVADO (no dispara fiable): señalizamos el turno nosotros
    realtime_input_config=types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
    ),
)

SPEECH_PEAK = 1000   # pico de amplitud >= esto = voz (silencio ~200-350, voz ~8000-15000)
END_SILENCE = 12     # ~1s de silencio (frames de ~80ms) para cerrar el turno


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
    """Audio + transcripción de Gemini → navegador. receive() entrega un turno y se
    cierra, por eso el while True lo reabre para el siguiente."""
    try:
        while True:
            async for response in session.receive():
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
    logger.info("WS navegador conectado; abriendo Gemini Live (directo)...")
    try:
        async with _client.aio.live.connect(model=MODEL, config=CONFIG) as session:
            logger.info("Gemini Live CONECTADO; ready (hablas tú primero)")
            await ws.send_text(json.dumps({"type": "ready"}))
            up = asyncio.create_task(_browser_to_gemini(ws, session))
            down = asyncio.create_task(_gemini_to_browser(ws, session))
            _, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            logger.info("Llamada finalizada")
    except WebSocketDisconnect:
        logger.info("WS navegador desconectado")
    except Exception:
        logger.exception("Error en /ws/call")
    finally:
        try:
            await ws.close()
        except Exception:
            pass
