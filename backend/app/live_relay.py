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
import collections
import json
import os

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
from loguru import logger

from . import persistence
from .config import settings
from .persona import SALON_PERSONA

router = APIRouter()

# Auth Vertex por ADC. En LOCAL usamos la SA appvoz-voice (fichero JSON); en Cloud Run
# ese fichero NO existe, asi que solo apuntamos a el si esta presente. Si no, el ADC usa
# la service account del runtime (metadata server) — fijar una ruta inexistente rompe la
# autenticacion en prod.
_sa = settings.google_application_credentials
if _sa and os.path.exists(_sa) and "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _sa
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

# Género de cada voz (doc oficial de Google Cloud TTS, columna "Gender"). Para filtrar
# el desplegable del panel: femenina | masculina.
VOICE_GENDER = {
    "Puck": "masculina", "Charon": "masculina", "Kore": "femenina", "Fenrir": "masculina",
    "Aoede": "femenina", "Leda": "femenina", "Orus": "masculina", "Zephyr": "femenina",
    "Callirrhoe": "femenina", "Autonoe": "femenina", "Enceladus": "masculina",
    "Iapetus": "masculina", "Umbriel": "masculina", "Algieba": "masculina",
    "Despina": "femenina", "Erinome": "femenina", "Algenib": "masculina",
    "Rasalgethi": "masculina", "Laomedeia": "femenina", "Achernar": "femenina",
    "Alnilam": "masculina", "Schedar": "masculina", "Gacrux": "femenina",
    "Pulcherrima": "femenina", "Achird": "masculina", "Zubenelgenubi": "masculina",
    "Vindemiatrix": "femenina", "Sadachbia": "masculina", "Sadaltager": "masculina",
    "Sulafat": "femenina",
}

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

# Modelo estable para CONTAR el tamano del prompt: los IDs Live no valen para
# count_tokens, pero el tokenizador de la familia 2.5 es el mismo, asi que el
# numero de tokens del texto es equivalente.
COUNT_MODEL = "gemini-2.5-flash"

# VAD por energía con histéresis + anti-pico (compensa el micro sensible al ruido):
# - abrir un turno es DIFÍCIL (umbral alto + varios frames seguidos) → el ruido de fondo
#   no dispara falsos turnos;
# - mantenerlo es FÁCIL (umbral más bajo) → no se corta en pasajes suaves a media frase.
OPEN_PEAK = 1300         # abrir turno por defecto: pico >= esto (silencio ~200-350, voz ~8000-15000)
OPEN_MIN, OPEN_MAX = 600, 3000   # límites del slider de sensibilidad del panel (umbral en vivo)
START_FRAMES = 2         # frames seguidos >= umbral para abrir (~170ms, anti-pico)
END_SILENCE = 12         # ~1s de silencio (frames de ~85ms) para cerrar el turno (default)
SILENCE_MIN, SILENCE_MAX = 3, 30   # límites del slider de "pausa fin de turno" (frames ~85ms)
BARGE_FRAMES = 6         # mientras el bot habla: ~0.5s de voz sostenida para cortarle (anti-tos)
BARGE_MIN, BARGE_MAX = 2, 12   # límites del slider de "resistencia a cortes" (frames ~85ms)


def _clamp_open(v) -> int:
    """Umbral de apertura saneado a [OPEN_MIN, OPEN_MAX]; OPEN_PEAK si no es válido."""
    try:
        return max(OPEN_MIN, min(OPEN_MAX, int(v)))
    except (TypeError, ValueError):
        return OPEN_PEAK


def _clamp_silence(v) -> int:
    """Pausa de fin de turno saneada a [SILENCE_MIN, SILENCE_MAX]; END_SILENCE si no vale."""
    try:
        return max(SILENCE_MIN, min(SILENCE_MAX, int(v)))
    except (TypeError, ValueError):
        return END_SILENCE


def _clamp_barge(v) -> int:
    """Resistencia a cortes saneada a [BARGE_MIN, BARGE_MAX]; BARGE_FRAMES si no vale."""
    try:
        return max(BARGE_MIN, min(BARGE_MAX, int(v)))
    except (TypeError, ValueError):
        return BARGE_FRAMES


def _vad_from_open(open_peak: int, end_silence: int = END_SILENCE,
                   barge_frames: int = BARGE_FRAMES) -> dict:
    """Construye el dict de VAD a partir del umbral de apertura (el resto se deriva)."""
    return {
        "open_peak": open_peak,
        "keep_peak": max(int(open_peak * 0.5), 600),  # histéresis: mantener cuesta la mitad que abrir
        "start_frames": START_FRAMES,
        "end_silence": end_silence,
        "barge_frames": barge_frames,
    }


def _vad_params(cfg: dict) -> dict:
    """VAD inicial de la sesión según el panel (sensibilidad + pausa + resistencia a cortes)."""
    return _vad_from_open(
        _clamp_open(cfg.get("mic_threshold")),
        _clamp_silence(cfg.get("end_silence")),
        _clamp_barge(cfg.get("barge_frames")),
    )


@router.get("/api/live/defaults")
async def live_defaults():
    """Fuente de verdad para el panel del navegador: matriz de capacidades por modelo."""
    return {
        "models": MODELS,
        "default_model": DEFAULT_MODEL,
        "caps": MODELS_CAPS,
        "voice_genders": VOICE_GENDER,
        "persona": SALON_PERSONA,
        "location": settings.gcp_live_location,
        "usd_eur": USD_EUR,
    }


@router.post("/api/live/count_tokens")
async def count_tokens(payload: dict):
    """Cuenta los tokens reales del system instruction (tamano del prompt mientras se
    edita). count_tokens NO se factura como generacion; solo informa cuanto ocupa."""
    text = (payload.get("text") or "").strip()
    if not text:
        return {"tokens": 0}
    try:
        res = await _client.aio.models.count_tokens(model=COUNT_MODEL, contents=text)
        return {"tokens": getattr(res, "total_tokens", None)}
    except Exception as e:
        logger.exception("count_tokens fallo")
        return {"tokens": None, "error": str(e)}


@router.get("/api/live/sessions")
async def listar_sesiones(user_id: str, limit: int = 20):
    """Historial de conversaciones de un usuario (la más reciente primero)."""
    sesiones = await persistence.listar_sesiones(user_id, limit)
    return {"sessions": sesiones}


@router.get("/api/live/sessions/{session_id}")
async def obtener_sesion(session_id: int):
    """Detalle de una sesión con todos sus turnos. 404 si no existe."""
    sesion = await persistence.obtener_sesion(session_id)
    if sesion is None:
        raise HTTPException(status_code=404, detail="sesión no encontrada")
    return sesion


def _build_config(cfg: dict, tools: list | None = None) -> tuple[str, types.LiveConnectConfig]:
    """Construye el LiveConnectConfig por conexión según las CAPACIDADES del modelo
    elegido: solo aplica voz/idioma/features que ese modelo admite (lo demás se ignora,
    para no provocar que la API rechace la sesión). `tools` (opcional): herramientas de
    function-calling para la sesión (p.ej. el Probador del 4g); el resto de vías no las usan."""
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

    # STT de ENTRADA: si el cfg fija idioma (p.ej. el onboarding 4g: 'es-ES'), forzarlo para que la
    # transcripción del micro no salte de idioma; si no, automático (el panel multi-idioma).
    stt_lang = cfg.get("stt_language")
    input_tx = (types.AudioTranscriptionConfig(language_codes=[stt_lang]) if stt_lang
                else types.AudioTranscriptionConfig())

    kwargs = dict(
        response_modalities=["AUDIO"],
        system_instruction=system,
        speech_config=types.SpeechConfig(**speech_kwargs),
        input_audio_transcription=input_tx,
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

    if tools:
        kwargs["tools"] = tools

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


async def _browser_to_gemini(ws: WebSocket, session, vad: dict, shared: dict, on_control=None):
    """Audio del navegador → Gemini, con VAD por energía (histéresis + anti-pico + gate)
    que señaliza el turno. Mientras NO hay turno no reenviamos audio a Gemini (el ruido de
    fondo nunca llega); al abrir, volcamos un pequeño preludio para no clipar el inicio.

    Anti-corte por ruido: para ABRIR turno en silencio basta `start_frames`; pero para
    CORTAR al bot mientras habla (barge-in) se exige `barge_frames` de voz sostenida, así
    una tos o un ruido corto no le interrumpe. El contador `hot` es "con fugas" (sube con
    voz, baja con silencio) para distinguir un pico puntual de habla continua."""
    open_peak, keep_peak = vad["open_peak"], vad["keep_peak"]
    start_frames, end_silence = vad["start_frames"], vad["end_silence"]
    barge_frames = vad["barge_frames"]
    in_speech, sil, hot = False, 0, 0
    prefix = collections.deque(maxlen=BARGE_MAX)  # preludio (cubre hasta el barge-in más largo)
    turno = bytearray()   # audio del turno en curso (STT fiable de respaldo; solo se guarda si la vía lo pide)
    dbg_max, dbg_n = 0, 0   # TEMP: diagnóstico de por qué no abre la compuerta
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                if in_speech:
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                logger.info("browser->gemini: navegador desconectó")
                return
            txt = msg.get("text")
            if txt:                              # mensaje de control: ajuste de VAD en vivo
                try:
                    data = json.loads(txt)
                    if data.get("type") == "vad":
                        if data.get("threshold") is not None:
                            nv = _vad_from_open(_clamp_open(data.get("threshold")))
                            open_peak, keep_peak = nv["open_peak"], nv["keep_peak"]
                        if data.get("end_silence") is not None:
                            end_silence = _clamp_silence(data.get("end_silence"))
                        if data.get("barge_frames") is not None:
                            barge_frames = _clamp_barge(data.get("barge_frames"))
                        logger.info(
                            f"VAD en vivo: open_peak={open_peak} end_silence={end_silence} "
                            f"barge={barge_frames}")
                    elif on_control is not None:
                        # Otros mensajes de control específicos de la vía (p.ej. 4g: cambiar de bloque).
                        await on_control(data, session, shared)
                except Exception:
                    logger.exception("browser->gemini: on_control/VAD ERROR")
                continue
            audio = msg.get("bytes")
            if not audio:
                continue
            try:
                s = array.array("h"); s.frombytes(audio)
                peak = max((abs(x) for x in s), default=0)
            except Exception:
                peak = 0

            if not in_speech:
                prefix.append(audio)
                # Anti-eco (vías que lo pidan, p.ej. onboarding 4g): mientras el bot habla,
                # ignorar el micro por completo (no abrir turno) para que su propio audio por el
                # altavoz no le interrumpa. Desactiva el barge-in solo en esas vías.
                if shared.get("no_barge") and shared.get("bot_speaking"):
                    hot = 0
                    continue
                # Cortar al bot exige más evidencia (voz sostenida) que abrir en silencio.
                need = barge_frames if shared.get("bot_speaking") else start_frames
                hot = min(need, hot + 1) if peak >= open_peak else max(0, hot - 1)
                dbg_max = max(dbg_max, peak); dbg_n += 1   # TEMP
                if dbg_n >= 25:                              # TEMP: ~2s
                    logger.info(f"[VAD dbg] esperando voz: peak_max~{dbg_max} umbral={open_peak} "
                                f"hot={hot} need={need} bot={shared.get('bot_speaking')}")
                    dbg_max, dbg_n = 0, 0
                if hot >= need:
                    logger.info(f"[VAD dbg] turno ABIERTO peak={peak} need={need}")   # TEMP
                    await session.send_realtime_input(activity_start=types.ActivityStart())
                    in_speech, sil, hot = True, 0, 0
                    turno = bytearray()
                    for buf in list(prefix)[-need:]:           # vuelca el preludio: no se clipa
                        turno += buf
                        await session.send_realtime_input(
                            audio=types.Blob(data=buf, mime_type="audio/pcm;rate=16000"))
                    prefix.clear()
                continue                                      # sin turno: NO mandamos ruido a Gemini

            # en turno: reenviamos el audio y vigilamos el silencio para cerrar
            turno += audio
            await session.send_realtime_input(
                audio=types.Blob(data=audio, mime_type="audio/pcm;rate=16000")
            )
            if peak >= keep_peak:                             # histéresis: mantener es fácil
                sil = 0
            else:
                sil += 1
                if sil >= end_silence:
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                    in_speech, sil = False, 0
                    if shared.get("_captura_turno"):   # vías que usan STT fiable (p.ej. 4g)
                        shared["_turno_audio"] = bytes(turno)
                    turno = bytearray()
    except WebSocketDisconnect:
        logger.info("browser->gemini: WS cerrado")
    except Exception:
        logger.exception("browser->gemini ERROR")


class _AcumuladorTurnos:
    """Agrupa los fragmentos de transcripción que llegan en streaming en TURNOS para
    persistirlos al cerrar la llamada.

    Las transcripciones llegan troceadas y alternando rol (usuario vs tutor). Aquí
    concatenamos fragmentos consecutivos del MISMO rol y, cuando llega texto de
    usuario después de texto del tutor, damos por cerrado el turno anterior y
    abrimos uno nuevo. La vía Live no tiene RAG ni métricas, así que los turnos
    guardan solo user_text/bot_text (las columnas RAG/latencia quedan en NULL/[])."""

    def __init__(self):
        self.turnos: list[dict] = []
        self._user = ""   # texto de usuario acumulado del turno en curso
        self._bot = ""    # texto del tutor acumulado del turno en curso

    def _flush(self):
        """Cierra el turno en curso (si tiene contenido) y lo añade a la lista."""
        if self._user or self._bot:
            self.turnos.append({
                "idx": len(self.turnos),
                "user_text": self._user or None,
                "bot_text": self._bot or None,
                # La vía Live no tiene RAG/métricas: columnas en NULL/[].
                "chunks": [],
            })
        self._user, self._bot = "", ""

    def add_user(self, texto: str):
        # Usuario tras respuesta del tutor → empieza un turno nuevo.
        if self._bot:
            self._flush()
        self._user += texto

    def add_bot(self, texto: str):
        self._bot += texto

    def finalizar(self) -> list[dict]:
        """Cierra el último turno pendiente y devuelve todos los turnos."""
        self._flush()
        return self.turnos


async def _gemini_to_browser(ws: WebSocket, session, acc: "_AcumuladorTurnos", shared: dict):
    """Audio + transcripción + consumo de Gemini → navegador. receive() entrega un turno
    y se cierra, por eso el while True lo reabre para el siguiente.

    Además de reenviar las transcripciones al navegador, las acumula en `acc` para
    persistir la conversación al cerrar la llamada. Mantiene `shared['bot_speaking']`
    (lo lee el VAD para exigir más voz antes de dejar que un ruido corte al bot)."""
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
                    shared["bot_speaking"] = False
                    await ws.send_text(json.dumps({"type": "interrupted"}))
                # Fin de generación/turno: el bot dejó de hablar (vuelve la apertura fácil).
                if getattr(sc, "generation_complete", None) or getattr(sc, "turn_complete", None):
                    shared["bot_speaking"] = False
                if sc.model_turn:
                    for part in (sc.model_turn.parts or []):
                        inline = getattr(part, "inline_data", None)
                        if inline and inline.data:
                            shared["bot_speaking"] = True   # el bot está emitiendo audio
                            await ws.send_bytes(inline.data)
                it = getattr(sc, "input_transcription", None)
                if it and getattr(it, "text", None):
                    acc.add_user(it.text)
                    await ws.send_text(json.dumps({"type": "user", "text": it.text}))
                ot = getattr(sc, "output_transcription", None)
                if ot and getattr(ot, "text", None):
                    acc.add_bot(ot.text)
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
    # Identidad para persistir la conversación. La vía Live aún no tiene materia:
    # defaults user_id='anonimo', subject_id='demo'.
    user_id = (cfg.get("user_id") or "anonimo").strip() or "anonimo"
    subject_id = (cfg.get("subject_id") or "demo").strip() or "demo"
    model, live_config = _build_config(cfg)
    vad = _vad_params(cfg)
    logger.info(
        f"abriendo Gemini Live (Vertex) model={model} voice={cfg.get('voice', DEFAULT_VOICE)} "
        f"vad_open={vad['open_peak']}"
    )
    acc = _AcumuladorTurnos()
    try:
        async with _client.aio.live.connect(model=model, config=live_config) as session:
            logger.info("Gemini Live CONECTADO; ready (hablas tú primero)")
            await ws.send_text(json.dumps({"type": "ready", "model": model}))
            shared = {"bot_speaking": False}   # estado compartido VAD ↔ salida (anti-corte)
            up = asyncio.create_task(_browser_to_gemini(ws, session, vad, shared))
            down = asyncio.create_task(_gemini_to_browser(ws, session, acc, shared))
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
        # Persistir la conversación (best-effort: nunca debe romper el cierre del WS).
        try:
            turnos = acc.finalizar()
            if turnos:
                session_id = await persistence.crear_sesion(
                    subject_id, user_id, via="gemini_live"
                )
                n = await persistence.guardar_turnos(session_id, turnos)
                await persistence.cerrar_sesion(session_id, n)
                # Resumen → memoria: fire-and-forget (no bloquea el cierre).
                asyncio.create_task(persistence.resumir_sesion(session_id))
                logger.info(f"sesión {session_id} persistida ({n} turnos)")
        except Exception:
            logger.exception("no pude persistir la sesión Live; se ignora")
        try:
            await ws.close()
        except Exception:
            pass
