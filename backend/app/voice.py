"""Banco de pruebas de voz (v1, push-to-talk).

Cascada vía API de Gemini: audio→texto (STT) → retrieval pgvector → Gemini Flash
(grounded) → texto→audio (TTS). Instrumenta la latencia de cada etapa.

NOTA: v1 usa la API de Gemini con API key (sin credenciales GCP ni Pipecat) para
medir el timing cuanto antes. La arquitectura de producción (Pipecat + Google STT v2
streaming + barge-in) es la v2.
"""
import base64
import struct
import time

from fastapi import APIRouter, File, Form, UploadFile
from google import genai
from google.genai import types

from .config import settings
from .rag import retrieve

router = APIRouter(prefix="/voice", tags=["voice"])

_client = genai.Client(api_key=settings.google_api_key)

LLM_MODEL = "gemini-2.5-flash"
STT_MODEL = "gemini-2.5-flash"
TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_VOICE = "Kore"

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


@router.post("/turn")
async def voice_turn(
    subject_id: str = Form(...),
    k: int = Form(5),
    audio: UploadFile | None = File(None),
    text_input: str | None = Form(None),
):
    """Un turno de conversación. Acepta audio (WAV) o `text_input` (para probar
    sin micro). Devuelve transcripción, respuesta, audio (WAV base64) y métricas."""
    m: dict[str, int] = {}
    t0 = time.perf_counter()

    # --- 1) STT (o bypass por texto) ---
    if text_input:
        transcript = text_input.strip()
        m["stt_ms"] = 0
    else:
        data = await audio.read()
        stt = await _client.aio.models.generate_content(
            model=STT_MODEL,
            contents=[
                types.Part.from_bytes(data=data, mime_type="audio/wav"),
                "Transcribe este audio en español. Devuelve solo el texto, sin comillas.",
            ],
        )
        transcript = (stt.text or "").strip()
        m["stt_ms"] = round((time.perf_counter() - t0) * 1000)

    # --- 2) Retrieval (RAG) ---
    t = time.perf_counter()
    chunks = await retrieve(subject_id, transcript, k) if transcript else []
    m["retrieval_ms"] = round((time.perf_counter() - t) * 1000)
    material = "\n\n".join(f"- {c['content']}" for c in chunks) or "(sin material)"
    prompt = (
        f"{SYSTEM}\n\nMATERIAL:\n{material}\n\n"
        f"PREGUNTA DEL ALUMNO: {transcript}\n\nRespuesta:"
    )

    # --- 3) LLM Gemini Flash (streaming → TTFT) ---
    t = time.perf_counter()
    first = None
    answer = ""
    stream = await _client.aio.models.generate_content_stream(model=LLM_MODEL, contents=prompt)
    async for chunk in stream:
        if chunk.text:
            if first is None:
                first = time.perf_counter()
                m["llm_ttft_ms"] = round((first - t) * 1000)
            answer += chunk.text
    m["llm_total_ms"] = round((time.perf_counter() - t) * 1000)
    answer = answer.strip() or "Eso no está en el material."

    # --- 4) TTS (texto → audio) ---
    t = time.perf_counter()
    tts = await _client.aio.models.generate_content(
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
    wav = pcm_to_wav(pcm, rate=24000)

    m["total_ms"] = round((time.perf_counter() - t0) * 1000)
    return {
        "transcript": transcript,
        "answer": answer,
        "audio_wav_b64": base64.b64encode(wav).decode(),
        "chunks": chunks,
        "metrics": m,
    }
