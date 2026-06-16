"""Motor de voz del banco de pruebas.

- HTTP  POST /voice/turn : turno completo no-streaming (Gemini TTS batch) — para comparar.
- WS    /voice/ws        : turno en STREAMING (Chirp 3 HD) — el tutor habla en <1s del
                           primer audio, audio progresivo. Es el camino del diseño (B).

Cascada: audio→texto (Gemini STT) → retrieval pgvector → Gemini Flash (grounded) →
texto→audio. Instrumenta la latencia de cada etapa.
"""
import asyncio
import base64
import json
import struct
import threading
import time

from fastapi import APIRouter, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from google import genai
from google.cloud import texttospeech as gtts
from google.genai import errors as genai_errors
from google.genai import types

from .config import settings
from .rag import retrieve

router = APIRouter(prefix="/voice", tags=["voice"])

_gemini = genai.Client(api_key=settings.google_api_key)
_tts_stream = gtts.TextToSpeechClient()  # usa GOOGLE_APPLICATION_CREDENTIALS (Chirp 3 HD)

LLM_MODEL = "gemini-2.5-flash"
STT_MODEL = "gemini-2.5-flash"
TTS_MODEL = "gemini-2.5-flash-preview-tts"  # solo para /turn (batch)
TTS_VOICE = "Kore"
CHIRP_VOICE = "es-ES-Chirp3-HD-Achernar"  # streaming, es-ES
CHIRP_RATE = 24000  # LINEAR16 mono

SYSTEM = (
    "Eres un tutor por voz. Responde SOLO con la información del MATERIAL. "
    "Si la respuesta no está en el material, di exactamente: 'Eso no está en el material.' "
    "Responde en español, breve y natural para ser hablado (2-4 frases)."
)


def pcm_to_wav(pcm: bytes, rate: int = 24000, ch: int = 1, bits: int = 16) -> bytes:
    byte_rate = rate * ch * bits // 8
    block_align = ch * bits // 8
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, ch, rate, byte_rate, block_align, bits)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


async def _retry(fn, tries: int = 3, base: float = 0.6):
    """Reintenta ante errores transitorios de Gemini (503/UNAVAILABLE) con backoff."""
    last = None
    for i in range(tries):
        try:
            return await fn()
        except genai_errors.ServerError as e:
            last = e
            if i < tries - 1:
                await asyncio.sleep(base * (i + 1))
    raise last


async def _stt(audio_wav: bytes) -> str:
    async def _call():
        r = await _gemini.aio.models.generate_content(
            model=STT_MODEL,
            contents=[
                types.Part.from_bytes(data=audio_wav, mime_type="audio/wav"),
                "Transcribe este audio en español. Devuelve solo el texto, sin comillas.",
            ],
        )
        return (r.text or "").strip()

    return await _retry(_call)


def _build_prompt(transcript: str, chunks: list[dict]) -> str:
    material = "\n\n".join(f"- {c['content']}" for c in chunks) or "(sin material)"
    return f"{SYSTEM}\n\nMATERIAL:\n{material}\n\nPREGUNTA DEL ALUMNO: {transcript}\n\nRespuesta:"


async def _llm_answer(prompt: str, m: dict) -> str:
    async def _call():
        t = time.perf_counter()
        first = None
        answer = ""
        stream = await _gemini.aio.models.generate_content_stream(model=LLM_MODEL, contents=prompt)
        async for ch in stream:
            if ch.text:
                if first is None:
                    first = time.perf_counter()
                    m["llm_ttft_ms"] = round((first - t) * 1000)
                answer += ch.text
        m["llm_total_ms"] = round((time.perf_counter() - t) * 1000)
        return answer.strip() or "Eso no está en el material."

    return await _retry(_call)


# ---------- HTTP no-streaming (comparación) ----------
@router.post("/turn")
async def voice_turn(
    subject_id: str = Form(...),
    k: int = Form(5),
    audio: UploadFile | None = File(None),
    text_input: str | None = Form(None),
):
    m: dict[str, int] = {}
    t0 = time.perf_counter()
    if text_input:
        transcript = text_input.strip()
        m["stt_ms"] = 0
    else:
        transcript = await _stt(await audio.read())
        m["stt_ms"] = round((time.perf_counter() - t0) * 1000)

    t = time.perf_counter()
    chunks = await retrieve(subject_id, transcript, k) if transcript else []
    m["retrieval_ms"] = round((time.perf_counter() - t) * 1000)
    answer = await _llm_answer(_build_prompt(transcript, chunks), m)

    t = time.perf_counter()
    tts = await _gemini.aio.models.generate_content(
        model=TTS_MODEL,
        contents=answer,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
                )
            ),
        ),
    )
    pcm = tts.candidates[0].content.parts[0].inline_data.data
    m["tts_ms"] = round((time.perf_counter() - t) * 1000)
    m["total_ms"] = round((time.perf_counter() - t0) * 1000)
    return {
        "transcript": transcript,
        "answer": answer,
        "audio_wav_b64": base64.b64encode(pcm_to_wav(pcm, 24000)).decode(),
        "chunks": chunks,
        "metrics": m,
    }


# ---------- WebSocket STREAMING (Chirp 3 HD) ----------
def _chirp_to_queue(text: str, q: "asyncio.Queue", loop: asyncio.AbstractEventLoop) -> None:
    """Sintetiza `text` con Chirp 3 HD en streaming y empuja chunks PCM a la cola async."""
    cfg = gtts.StreamingSynthesizeConfig(
        voice=gtts.VoiceSelectionParams(language_code="es-ES", name=CHIRP_VOICE)
    )

    def reqs():
        yield gtts.StreamingSynthesizeRequest(streaming_config=cfg)
        yield gtts.StreamingSynthesizeRequest(input=gtts.StreamingSynthesisInput(text=text))

    try:
        for resp in _tts_stream.streaming_synthesize(reqs()):
            if resp.audio_content:
                asyncio.run_coroutine_threadsafe(q.put(resp.audio_content), loop)
    finally:
        asyncio.run_coroutine_threadsafe(q.put(None), loop)


@router.websocket("/ws")
async def voice_ws(ws: WebSocket):
    await ws.accept()
    subject_id = ws.query_params.get("subject_id", "demo_voz")
    k = int(ws.query_params.get("k", 5))
    try:
        m: dict[str, int] = {}
        t0 = time.perf_counter()

        # --- 1) Recibir turno: binario (WAV) o texto JSON {"text": "..."} ---
        msg = await ws.receive()
        if msg.get("text") is not None:
            payload = json.loads(msg["text"])
            transcript = (payload.get("text") or "").strip()
            subject_id = payload.get("subject_id", subject_id)
            m["stt_ms"] = 0
        elif msg.get("bytes") is not None:
            transcript = await _stt(msg["bytes"])
            m["stt_ms"] = round((time.perf_counter() - t0) * 1000)
        else:
            await ws.close()
            return
        await ws.send_text(json.dumps({"type": "transcript", "text": transcript}))

        # --- 2) Retrieval ---
        t = time.perf_counter()
        chunks = await retrieve(subject_id, transcript, k) if transcript else []
        m["retrieval_ms"] = round((time.perf_counter() - t) * 1000)

        # --- 3) LLM Flash (grounded) ---
        answer = await _llm_answer(_build_prompt(transcript, chunks), m)
        await ws.send_text(json.dumps({"type": "answer", "text": answer}))

        # --- 4) TTS Chirp 3 HD en streaming → audio progresivo ---
        await ws.send_text(json.dumps({"type": "audio_start", "sample_rate": CHIRP_RATE}))
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        t_tts = time.perf_counter()
        threading.Thread(target=_chirp_to_queue, args=(answer, q, loop), daemon=True).start()
        first_audio = None
        while True:
            chunk = await q.get()
            if chunk is None:
                break
            if first_audio is None:
                first_audio = time.perf_counter()
                m["tts_first_ms"] = round((first_audio - t_tts) * 1000)
                m["ttfa_ms"] = round((first_audio - t0) * 1000)  # voz-a-primer-audio
            await ws.send_bytes(chunk)

        m["total_ms"] = round((time.perf_counter() - t0) * 1000)
        await ws.send_text(json.dumps({"type": "metrics", "metrics": m}))
        await ws.close()
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001 — reportar al cliente en vez de cortar en seco
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(e)[:200]}))
            await ws.close()
        except Exception:
            pass
