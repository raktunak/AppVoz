"""Vertical ONBOARDING 4G: la guía por voz que rellena el Canva en vivo, SECCIÓN A SECCIÓN.

Navegador (PCM 16k) ⇄ FastAPI /ws/4g ⇄ Gemini Live (Vertex). Reutiliza del relay web
(`live_relay.py`) el cliente Gemini, `_build_config`, las constantes/clamps de VAD y `_vad_params`.

Lo NUEVO (decisión 2026-06-20): cada SECCIÓN del Canva es una **sesión Gemini independiente**
(ventana pequeña, conversación reseteada) que el usuario abre/cierra desde su botón "Hablar"; el
navegador mantiene UN solo WebSocket y un solo micro, y por debajo ciclamos la sesión Gemini. Así
ganamos: fidelidad (prompt enfocado + preguntas literales inyectadas), ventana limpia (sin arrastrar
30 min de conversación), coste/latencia y un modelo mental de CURSO. La continuidad entre secciones
se da inyectando el RESUMEN del Canva (estado estructurado) en el prompt de cada sección, no
manteniendo una ventana gigante.

Arquitectura del WS:
- El **control loop** (`ws_4g`) es el ÚNICO que lee del WebSocket: despacha cada frame de audio a
  la sesión activa (vía `_Vad.feed`) y procesa los mensajes de control del navegador.
- Cada sección corre en su propia tarea (`_run_section`) con su `async with live.connect(...)`.
- Iniciar una sección **cierra automáticamente** la anterior (`_iniciar_seccion` → `_detener_seccion`).

La compuerta "sección completa" la decide el CÓDIGO (`canva4g.seccion_completa`, con confirmación
por estabilidad). Al completar "Primer bloque" se agenda en Google Calendar de forma DETERMINISTA.

Protocolo navegador→backend (JSON salvo el audio binario PCM16 16k):
  config        {user_id}                              · handshake (no arranca ninguna sección)
  start_section {idx}                                  · abre/reabre la sección idx (cierra la activa)
  stop_section  {}                                     · cierra la sección activa
  vad           {threshold,end_silence,barge_frames}   · ajuste de VAD en vivo

Protocolo backend→navegador (JSON salvo el audio binario PCM 24k):
  ready          {secciones, activa, canva, completas}
  section_started{idx, key}     · se abrió una sección (Faro va a hablar)
  section_stopped{idx, key}     · se cerró la sección activa
  user/bot       {text}         · transcripción en streaming
  canva          {canva}        · estado del Canva tras cada extracción
  section_done   {idx, key}     · la sección quedó completa (el usuario decide seguir/revisar)
  booked         {ok, event|error}
  interrupted    {}             · barge-in (vaciar reproducción)
"""
import array
import asyncio
import collections
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google.genai import types
from loguru import logger

from . import agenda, canva4g, persistence
from .config import settings
from .live_relay import (
    BARGE_MAX,
    _build_config,
    _clamp_barge,
    _clamp_open,
    _clamp_silence,
    _client,
    _vad_from_open,
    _vad_params,
)

router = APIRouter()

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Registro de sesiones WS activas por user_id. Lo usa /api/4g/reset para limpiar el Canva EN
# MEMORIA de una sesión viva: si no, al desconectar el WS re-guardaría el Canva viejo y desharía
# el reset (la fila se borra en la BD pero la copia en memoria la vuelve a escribir al cerrar).
_SESIONES_4G: dict[str, dict] = {}


def _parse_minutos(texto) -> int | None:
    """Minutos disponibles a partir de texto libre ('20 minutos', '5 minutillos', 'media hora',
    'una hora'); None si no se puede. Modula la invitación a avanzar (>15 min)."""
    if not texto:
        return None
    t = str(texto).lower()
    m = re.search(r"\d+", t)
    if m:
        n = int(m.group())
        return n * 60 if "hora" in t else n
    if "media hora" in t:
        return 30
    if "hora" in t:
        return 60
    return None


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


def _preparar_prompt(cfg: dict, fecha_str: str, canva: dict) -> dict:
    """Base del system_instruction de una sección: persona + (a) fecha de hoy, (b) reglas de
    operación, (c) resumen del Canva ya capturado (continuidad). La conducción concreta de la
    sección (las preguntas) la añade `_instruccion_seccion`; aquí va lo común a todas."""
    base = (cfg.get("system_instruction") or "").strip()
    extra = (
        f"\n\nContexto: hoy es {fecha_str}. Cuando propongas o confirmes un día y una hora, "
        f"resuélvelos a partir de esta fecha y confírmalos en voz alta antes de cerrar."
        "\n\nCÓMO TRABAJAS: sigue al pie de la letra las instrucciones de esta conversación. Haz "
        "las preguntas que se te indican de forma LITERAL, palabra por palabra, una sola por turno, "
        "y espera la respuesta. NUNCA leas en voz alta el texto entre paréntesis ( ) ni entre "
        "corchetes [ ]: son indicaciones para ti, no para decirlas. No narres lo que hace la persona."
    )
    resumen = canva4g.resumen_canva(canva)
    if resumen:
        extra += (
            "\n\nLO QUE ESTA PERSONA YA TE HA CONTADO (para dar continuidad; NO lo repreguntes):\n"
            + resumen
        )
    return {**cfg, "system_instruction": base + extra}


def _valores_seccion(seccion: dict, datos: dict | None) -> str:
    """Texto legible con lo ya capturado en una sección (para el guion de revisión)."""
    datos = datos or {}
    if seccion.get("tipo") == "lista":
        arr = datos.get(seccion["lista"]) or []
        return "; ".join(
            (x.get("valor") or x.get("nombre") or "") for x in arr if isinstance(x, dict)
        ).strip("; ")
    return "; ".join(
        f"{a['etiqueta']}: {datos.get(a['campo'])}"
        for a in seccion.get("apartados", []) if datos.get(a["campo"])
    )


def _instruccion_seccion(seccion: dict, arranque: bool, reanuda: bool, datos: dict) -> str:
    """Bloque de conducción de la sección que va al SYSTEM_INSTRUCTION (NO se vocaliza): saludo según
    el momento + las preguntas literales a hacer (captura) o el resumen para corregir (revisión).
    Al ir en el prompt de sistema y no en el canal hablado, Faro las SIGUE en vez de leerlas."""
    if arranque and not reanuda:
        saludo = "Es el comienzo: preséntate en una sola frase como Faro."
    elif arranque and reanuda:
        saludo = "Retomas una sesión anterior: salúdala de nuevo en una frase, sin repetir lo ya hecho."
    else:
        saludo = "Vienes de la parte anterior: NO te presentes ni saludes de nuevo; enlaza con naturalidad."
    if canva4g.seccion_completa(seccion, datos):   # revisión
        vals = _valores_seccion(seccion, datos)
        return (
            f"AHORA estás en la parte «{seccion['titulo']}», que YA está rellena con: {vals}. "
            f"{saludo} Resúmela en una frase y pregúntale si quiere CORREGIR o AMPLIAR algo; "
            f"no la interrogues de cero ni repitas las preguntas."
        )
    preguntas = canva4g.preguntas_seccion(seccion)
    lista = "  ".join(f"{i + 1}) «{q}»" for i, q in enumerate(preguntas))
    return (
        f"AHORA estás en la parte «{seccion['titulo']}». {saludo} Haz estas preguntas, UNA A UNA y "
        f"TAL CUAL (palabra por palabra, sin reformular ni inventar otras, sin adelantar las "
        f"siguientes), esperando la respuesta a cada una antes de la próxima: {lista} "
        f"Acoge cada respuesta con naturalidad pero NO la confirmes con '¿correcto?' ni encadenes "
        f"otra pregunta sin esperar. Cuando tengas TODAS las respuestas, ESPERA mi indicación para "
        f"recapitular y proponer seguir; no recapitules ni propongas avanzar por tu cuenta."
    )


async def _disparar(session, shared: dict) -> None:
    """Da el turno inicial a Faro con un mínimo ENTRE PARÉNTESIS (la persona tiene la regla de no
    leer paréntesis), para que arranque siguiendo su system_instruction sin vocalizar la indicación."""
    shared["bot_speaking"] = True
    try:
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text="(Empieza tu turno ahora.)")])],
            turn_complete=True,
        )
    except Exception:
        logger.exception("[4g] no pude dar el turno inicial")


def _guion_confirmacion(seccion: dict, recap: str, siguiente: str | None, minutos: int | None) -> str:
    """Indicación BREVE y ENTRE PARÉNTESIS (no se lee) para que Faro recapitule y pida confirmación.
    En Presentación modula la invitación según el tiempo (>15 min anima; <=15 deja elegir)."""
    destino = f"«{siguiente}»" if siguiente else "cerrar tu Canva"
    extra = ""
    if seccion["key"] == "presentacion" and minutos is not None:
        extra = (f" Tiene unos {minutos} minutos, tiempo de sobra: anímale a seguir." if minutos > 15
                 else f" Solo tiene unos {minutos} minutos y la Visión pide calma: dile que puede "
                      "seguir igual o dejarla para otra sesión, y que elija.")
    return (
        f"(Ya tienes todas las respuestas de esta parte. Menciónalas de pasada y con naturalidad "
        f"({recap}), SIN preguntar si son correctas —el usuario ya las ve en pantalla—. Luego, en "
        f"tono de INVITACIÓN, propón seguir: algo como «si todo está bien, te invito a seguir con "
        f"{destino}». Si te corrige algún dato, acéptalo con naturalidad.{extra})"
    )


async def _pedir_confirmacion(ws: WebSocket, shared: dict, idx: int) -> None:
    """Inyecta el guion de confirmación (recap + invitación) y marca el estado AWAITING_CONFIRM."""
    ses = shared.get("session")
    if ses is None:
        return
    seccion = canva4g.SECCIONES[idx]
    datos = shared["canva"].get(seccion["key"]) or {}
    recap = _valores_seccion(seccion, datos) or "tus respuestas"
    nxt = _siguiente_pendiente(shared["canva"], idx)
    siguiente = canva4g.SECCIONES[nxt]["titulo"] if nxt is not None else None
    minutos = _parse_minutos(datos.get("tiempo_disponible")) if seccion["key"] == "presentacion" else None
    txt = _guion_confirmacion(seccion, recap, siguiente, minutos)
    shared["_await_confirm"] = True
    shared["_conv_confirm"] = len(shared.get("conv", ""))
    shared["bot_speaking"] = True
    try:
        await ses.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text=txt)])],
            turn_complete=True,
        )
        logger.info(f"[4g] pido confirmación '{seccion['key']}' (recap; siguiente={siguiente})")
    except Exception:
        logger.exception("[4g] no pude pedir confirmación")


# --------------------------------------------------------------------------- #
# VAD por-frame: misma lógica que live_relay._browser_to_gemini, pero SIN ser dueño del
# ws.receive() (el control loop le pasa cada frame). Permite ciclar la sesión por debajo.
# --------------------------------------------------------------------------- #
class _Vad:
    """Detector de turno por energía (histéresis + anti-pico + anti-eco), por-frame."""

    def __init__(self, vad: dict):
        self.open_peak = vad["open_peak"]
        self.keep_peak = vad["keep_peak"]
        self.start_frames = vad["start_frames"]
        self.end_silence = vad["end_silence"]
        self.barge_frames = vad["barge_frames"]
        self.in_speech = False
        self.sil = 0
        self.hot = 0
        self.prefix = collections.deque(maxlen=BARGE_MAX)  # preludio: cubre hasta el barge más largo
        self.turn = bytearray()                            # audio del turno en curso (para STT fiable)

    async def feed(self, session, audio: bytes, shared: dict) -> None:
        try:
            s = array.array("h")
            s.frombytes(audio)
            peak = max((abs(x) for x in s), default=0)
        except Exception:
            peak = 0

        if not self.in_speech:
            self.prefix.append(audio)
            # Anti-eco: mientras Faro habla, ignorar el micro por completo (su audio por el
            # altavoz no debe abrir turno ni interrumpirla en esta vía).
            if shared.get("no_barge") and shared.get("bot_speaking"):
                self.hot = 0
                return
            # Frames de voz sostenida para ABRIR turno. En la fase de confirmación esperamos una
            # respuesta CORTA (sí/no) y basta UN frame: un "sí" de ~150ms no junta 2 frames y se
            # perdía. Falsos positivos baratos: el recap + clasificar_intencion descartan lo que no
            # sea sí/no, y abrir aunque sea por ruido cuenta como input → no deja morir la sesión.
            if shared.get("bot_speaking"):
                need = self.barge_frames
            elif shared.get("_await_confirm"):
                need = 1
            else:
                need = self.start_frames
            self.hot = min(need, self.hot + 1) if peak >= self.open_peak else max(0, self.hot - 1)
            self._dbg_max = max(getattr(self, "_dbg_max", 0), peak)   # TEMP diagnóstico VAD
            self._dbg_n = getattr(self, "_dbg_n", 0) + 1
            if self._dbg_n >= 25:
                logger.info(
                    f"[4g VAD] esperando voz peak_max~{self._dbg_max} umbral={self.open_peak} "
                    f"hot={self.hot} need={need} bot={shared.get('bot_speaking')}")
                self._dbg_max, self._dbg_n = 0, 0
            if self.hot >= need:
                logger.info(f"[4g VAD] turno ABIERTO peak={peak} need={need}")   # TEMP
                await session.send_realtime_input(activity_start=types.ActivityStart())
                self.in_speech, self.sil, self.hot = True, 0, 0
                self.turn = bytearray()
                for buf in list(self.prefix)[-need:]:           # vuelca el preludio: no se clipa
                    self.turn += buf
                    await session.send_realtime_input(
                        audio=types.Blob(data=buf, mime_type="audio/pcm;rate=16000"))
                self.prefix.clear()
            return

        # en turno: reenviamos audio (y lo bufferizamos para el STT fiable) y vigilamos el silencio
        self.turn += audio
        await session.send_realtime_input(
            audio=types.Blob(data=audio, mime_type="audio/pcm;rate=16000"))
        if peak >= self.keep_peak:
            self.sil = 0
        else:
            self.sil += 1
            if self.sil >= self.end_silence:
                await session.send_realtime_input(activity_end=types.ActivityEnd())
                self.in_speech, self.sil = False, 0
                shared["_turno_audio"] = bytes(self.turn)   # turno completo → disponible para STT
                self.turn = bytearray()


def _siguiente_pendiente(canva: dict, desde: int) -> int | None:
    """Índice de la siguiente sección NO completa tras `desde` (recoge también las anteriores que
    se hubieran saltado); None si están todas. Es el destino del auto-avance al terminar una sección."""
    n = len(canva4g.SECCIONES)
    for i in list(range(desde + 1, n)) + list(range(0, desde)):
        s = canva4g.SECCIONES[i]
        if not canva4g.seccion_completa(s, canva.get(s["key"])):
            return i
    return None


async def _extraer_y_push(ws: WebSocket, shared: dict, idx: int):
    """Extrae la sección `idx`, actualiza el Canva y lo empuja al navegador. Cuando los datos están
    completos pide CONFIRMACIÓN al usuario (recap + invitación) y solo al confirmar marca
    `section_done`, fija el auto-avance y cierra la sesión. Best-effort."""
    if idx >= len(canva4g.SECCIONES):
        return
    if shared.get("sec_idx") != idx:
        return   # tarea obsoleta: la sección activa ya cambió (no contaminar a la nueva)
    seccion = canva4g.SECCIONES[idx]
    conv = shared.get("conv", "")
    if not conv.strip():
        return
    # STT fiable de respaldo (C): transcribe el audio del último turno en español; corrige la
    # burbuja del chat y se lo pasa al extractor como fuente prioritaria.
    audio_turno = shared.pop("_turno_audio", None)
    stt_fiable = await canva4g.transcribir_audio(audio_turno) if audio_turno else ""
    if stt_fiable:
        logger.info(f"[4g] STT fiable: «{stt_fiable}»")
        try:
            await ws.send_text(json.dumps({"type": "user_fix", "text": stt_fiable}))
        except Exception:
            pass
    datos = await canva4g.extraer_seccion(seccion["key"], conv, shared["fecha_str"], stt_fiable)
    if not datos:
        return
    key = seccion["key"]
    prev = shared["canva"].get(key) or {}
    shared["canva"][key] = canva4g.merge_seccion(seccion, prev, datos)
    logger.info(f"[4g] extracción '{key}' -> {datos}")
    try:
        await ws.send_text(json.dumps({"type": "canva", "canva": shared["canva"]}))
    except Exception:
        return
    try:
        await canva4g.guardar_canva(shared["user_id"], shared["canva"], shared["subject_id"])
    except Exception:
        logger.exception("[4g] no pude guardar canva (incremental)")
    if shared.get("_done_sec") or shared.get("sec_idx") != idx:
        return   # ya confirmada/avanzando, o la sección cambió mientras se extraía (tarea obsoleta)
    completa = canva4g.seccion_completa(seccion, shared["canva"].get(key))

    # ESTADO 2 — esperando que el usuario confirme/corrija tras la recapitulación.
    if shared.get("_await_confirm"):
        respuesta = conv[shared.get("_conv_confirm", 0):]
        if "Persona:" not in respuesta:
            return   # aún no ha respondido el usuario a la confirmación (solo está el recap de Faro)
        intent = await canva4g.clasificar_intencion(respuesta)
        logger.info(f"[4g] confirmación '{key}': intención={intent}")
        if intent == "confirma" and completa:
            shared["_done_sec"] = True
            shared["_await_confirm"] = False
            if key == "bloque":
                await _agendar_bloque(ws, shared)
            try:
                await ws.send_text(json.dumps({"type": "section_done", "idx": idx, "key": key}))
            except Exception:
                pass
            shared["_advance"] = _siguiente_pendiente(shared["canva"], idx)
            logger.info(f"[4g] '{key}' CONFIRMADA por el usuario → siguiente={shared['_advance']}")
            ev = shared.get("stop_event")
            if ev is not None and not ev.is_set():
                ev.set()
        elif intent == "corrige" and completa:
            await _pedir_confirmacion(ws, shared, idx)     # re-recapitula con el dato ya corregido
        elif intent == "corrige":
            shared["_await_confirm"] = False               # falta algún dato: Faro lo vuelve a pedir
        # rechaza | ambiguo → seguimos esperando; Faro mantiene la conversación
        return

    # ESTADO 1 — datos completos → invitar a seguir, pero SOLO tras una intervención del usuario en
    # esta sección (si no, una sección reabierta ya completa dispararía la invitación en el saludo).
    if completa and "Persona:" in conv:
        await _pedir_confirmacion(ws, shared, idx)


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
    """Audio + transcripción de Gemini → navegador, acumulando la conversación de ESTA sección.
    Al cierre de cada turno dispara la extracción (en background) fijando el idx ACTUAL, para que
    no contamine a otra sección si el usuario cambia mientras tanto."""
    try:
        while True:
            async for response in session.receive():
                sc = response.server_content
                if not sc:
                    continue
                if sc.interrupted:
                    shared["bot_speaking"] = False
                    logger.info("[4g] INTERRUPTED (barge-in)")
                    await ws.send_text(json.dumps({"type": "interrupted"}))
                if getattr(sc, "generation_complete", None) or getattr(sc, "turn_complete", None):
                    shared["bot_speaking"] = False
                if getattr(sc, "turn_complete", None):
                    cur_idx = shared["sec_idx"]
                    asyncio.create_task(_extraer_y_push(ws, shared, cur_idx))
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
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("[4g] gemini->browser ERROR")


async def _watchdog_confirmacion(session, shared: dict) -> None:
    """Red de seguridad de la fase de confirmación: si el usuario no responde al recap, Faro
    REPREGUNTA en vez de quedarse callado (lo que dejaría a la sesión native-audio sin input y
    Vertex la cerraría por inactividad). Repreguntar cuenta como input → además resetea ese timeout.
    Reintenta un par de veces; con el VAD ya sensible al sí/no (need=1) esto rara vez hará falta."""
    intentos = 0
    try:
        while shared.get("session") is session:
            await asyncio.sleep(7)
            if shared.get("session") is not session:
                return
            vo = shared.get("vad_obj")
            esperando = (shared.get("_await_confirm") and not shared.get("bot_speaking")
                         and not (vo is not None and vo.in_speech))
            if not esperando:
                intentos = 0                # confirmó, corrige o está hablando → reinicia la cuenta
                continue
            if intentos >= 2:
                continue                    # ya insistí; no repreguntar en bucle infinito
            intentos += 1
            logger.info(f"[4g] watchdog: sin confirmación; Faro repregunta (intento {intentos})")
            shared["bot_speaking"] = True
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text=(
                    "El usuario no ha respondido. Vuelve a invitarle MUY brevemente a continuar: "
                    "que diga «sí» para seguir o «no» para quedarse en este apartado."))])],
                turn_complete=True,
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("[4g] watchdog confirmación ERROR")


# --------------------------------------------------------------------------- #
# Ciclo de vida de una sección: cada una es su propia sesión Gemini.
# --------------------------------------------------------------------------- #
async def _run_section(ws: WebSocket, shared: dict, vad: dict, idx: int):
    """Abre una sesión Gemini para la sección `idx` con su conducción en el system_instruction, le
    da el turno inicial y la mantiene hasta que se pide parar (`stop_event`) o el navegador se va.
    Ventana pequeña: conversación reseteada."""
    seccion = canva4g.SECCIONES[idx]
    shared["sec_idx"] = idx   # también para el camino de auto-avance (que no pasa por _iniciar_seccion)
    datos = shared["canva"].get(seccion["key"]) or {}
    arranque = not shared.get("presentado")
    reanuda = shared.get("reanuda", False)
    # La conducción de la sección (preguntas/saludo) va al SYSTEM_INSTRUCTION (no se vocaliza).
    cfg = _preparar_prompt(shared["cfg_base"], shared["fecha_str"], shared["canva"])
    bloque = _instruccion_seccion(seccion, arranque, reanuda, datos)
    # B (forzar es-ES en la transcripción de native-audio) DESACTIVADO: desestabilizaba/cerraba la
    # sesión (native-audio no admite bien `language_codes`). El STT fiable (C) ya cubre la precisión.
    cfg = {**cfg, "system_instruction": cfg["system_instruction"] + "\n\n" + bloque}
    model, live_config = _build_config(cfg)
    try:
        async with _client.aio.live.connect(model=model, config=live_config) as session:
            shared["session"] = session
            shared["vad_obj"] = _Vad(vad)
            shared["conv"] = ""
            shared["_last"] = None
            shared["bot_speaking"] = False
            shared["_await_confirm"] = False
            shared["_conv_confirm"] = 0
            # Arranca SIEMPRE como no-completada (aunque la sección ya tuviera datos, p.ej. al
            # reabrir/reanudar): si no, el flag cortaría la confirmación/avance. La invitación se
            # dispara solo tras la primera intervención del usuario en la sección (guard en _extraer_y_push).
            shared["_done_sec"] = False
            shared["presentado"] = True
            await ws.send_text(json.dumps({
                "type": "section_started", "idx": idx, "key": seccion["key"]}))
            down = asyncio.create_task(_gemini_to_browser_4g(ws, session, shared))
            await _disparar(session, shared)   # turno inicial mínimo y entre paréntesis
            waiter = asyncio.create_task(shared["stop_event"].wait())
            wd = asyncio.create_task(_watchdog_confirmacion(session, shared))  # repregunta si no confirmas
            _, pending = await asyncio.wait({down, waiter}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            wd.cancel()   # el watchdog no termina la sección; se cancela al cerrarla
    except Exception:
        logger.exception(f"[4g] _run_section idx={idx} error")
    finally:
        shared["session"] = None
        shared["vad_obj"] = None
        try:
            await ws.send_text(json.dumps({
                "type": "section_stopped", "idx": idx, "key": seccion["key"]}))
        except Exception:
            pass
        try:
            await canva4g.guardar_canva(shared["user_id"], shared["canva"], shared["subject_id"])
        except Exception:
            logger.exception("[4g] no pude guardar canva al cerrar sección")
        # Auto-avance: si esta sección se cerró por COMPLETARSE (no por acción del usuario), abrir
        # la siguiente pendiente. Guardas: no pisar un cierre manual (`_detaining`) ni una tarea ya
        # reemplazada por un inicio manual (`section_task is current_task`).
        nxt = shared.pop("_advance", None)
        if (nxt is not None and not shared.get("_detaining")
                and shared.get("section_task") is asyncio.current_task()):
            shared["stop_event"] = asyncio.Event()
            shared["section_task"] = asyncio.create_task(_run_section(ws, shared, vad, nxt))
            logger.info(f"[4g] auto-avance → sección idx={nxt}")


async def _detener_seccion(shared: dict):
    """Cierra la sección activa (si la hay) y espera a que su tarea limpie. Marca `_detaining` para
    que la tarea que se cierra NO dispare el auto-avance (es un cierre MANUAL, no por completarse)."""
    ev = shared.get("stop_event")
    task = shared.get("section_task")
    shared["_detaining"] = True
    if ev is not None and not ev.is_set():
        ev.set()
    if task is not None:
        try:
            await task
        except Exception:
            pass
    shared["section_task"] = None
    shared["stop_event"] = None
    shared["_detaining"] = False


async def _iniciar_seccion(ws: WebSocket, shared: dict, vad: dict, idx):
    """Abre la sección `idx` cerrando antes la anterior (auto-close). idx None → la activa."""
    await _detener_seccion(shared)
    if idx is None:
        idx = shared.get("sec_idx", 0)
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        idx = shared.get("sec_idx", 0)
    idx = max(0, min(idx, len(canva4g.SECCIONES) - 1))
    shared["sec_idx"] = idx
    shared["stop_event"] = asyncio.Event()
    shared["section_task"] = asyncio.create_task(_run_section(ws, shared, vad, idx))
    logger.info(f"[4g] iniciar sección idx={idx} key={canva4g.SECCIONES[idx]['key']}")


def _aplicar_vad(shared: dict, vad: dict, data: dict):
    """Ajuste de VAD en vivo desde el panel: actualiza el dict base y el _Vad activo si lo hay."""
    if data.get("threshold") is not None:
        nv = _vad_from_open(_clamp_open(data.get("threshold")))
        vad["open_peak"], vad["keep_peak"] = nv["open_peak"], nv["keep_peak"]
    if data.get("end_silence") is not None:
        vad["end_silence"] = _clamp_silence(data.get("end_silence"))
    if data.get("barge_frames") is not None:
        vad["barge_frames"] = _clamp_barge(data.get("barge_frames"))
    vo = shared.get("vad_obj")
    if vo is not None:
        vo.open_peak, vo.keep_peak = vad["open_peak"], vad["keep_peak"]
        vo.end_silence = vad["end_silence"]
        vo.barge_frames = vad["barge_frames"]


@router.websocket("/ws/4g")
async def ws_4g(ws: WebSocket):
    """Onboarding 4G por voz, sesión-por-sección. El navegador manda primero {type:'config',
    user_id}; luego abre/cierra secciones con start_section/stop_section y envía audio PCM16 16k.
    El control loop despacha el audio a la sesión activa y procesa los mensajes de control."""
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

    cfg_base, subject_id = await _cargar_cfg_4g()
    fecha_str = _fecha_ctx()
    canva_prev = await canva4g.obtener_canva(user_id)
    vad = _vad_params(cfg_base)
    shared = {
        "user_id": user_id, "subject_id": subject_id, "cfg_base": cfg_base,
        "fecha_str": fecha_str, "canva": canva_prev or {},
        "sec_idx": canva4g.primera_incompleta(canva_prev),
        "conv": "", "_last": None, "no_barge": True, "bot_speaking": False,
        "session": None, "vad_obj": None, "section_task": None, "stop_event": None,
        "reanuda": bool(canva4g.resumen_canva(canva_prev)), "presentado": False, "_booked": False,
    }
    logger.info(f"[4g] sesión user={user_id} subject={subject_id} activa={shared['sec_idx']}")
    _SESIONES_4G[user_id] = shared
    try:
        await ws.send_text(json.dumps({
            "type": "ready",
            "secciones": _secciones_publicas_con_prompt(),
            "activa": shared["sec_idx"],
            "canva": shared["canva"],
            "completas": canva4g.completas(shared["canva"]),
        }))
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            txt = msg.get("text")
            if txt:
                try:
                    data = json.loads(txt)
                except Exception:
                    continue
                t = data.get("type")
                if t == "start_section":
                    await _iniciar_seccion(ws, shared, vad, data.get("idx"))
                elif t == "stop_section":
                    await _detener_seccion(shared)
                elif t == "vad":
                    _aplicar_vad(shared, vad, data)
                continue
            audio = msg.get("bytes")
            if not audio:
                continue
            vo = shared.get("vad_obj")
            ses = shared.get("session")
            shared["_frames"] = shared.get("_frames", 0) + 1
            if shared["_frames"] % 50 == 0:   # TEMP diagnóstico (~4s de audio)
                logger.info(
                    f"[4g dbg] frames={shared['_frames']} vad={'sí' if vo else 'NO'} "
                    f"ses={'sí' if ses else 'NO'} bot={shared.get('bot_speaking')} "
                    f"in_speech={getattr(vo, 'in_speech', None)}")
            if vo is not None and ses is not None:
                try:
                    await vo.feed(ses, audio, shared)
                except Exception:
                    logger.exception("[4g] vad.feed ERROR")  # antes se tragaba en silencio
    except WebSocketDisconnect:
        logger.info("[4g] navegador desconectado")
    except Exception:
        logger.exception("[4g] error en /ws/4g")
        try:
            await ws.send_text(json.dumps({"type": "error", "detail": "error interno"}))
        except Exception:
            pass
    finally:
        await _detener_seccion(shared)
        if _SESIONES_4G.get(user_id) is shared:   # no pisar una reconexión más nueva del mismo user
            _SESIONES_4G.pop(user_id, None)
        try:
            await canva4g.guardar_canva(user_id, shared["canva"], subject_id)
        except Exception:
            logger.exception("[4g] no pude guardar el canva final")
        try:
            await ws.close()
        except Exception:
            pass


def _secciones_publicas_con_prompt() -> list[dict]:
    """Secciones públicas + el PROMPT inyectado a Faro en cada una (vista de pruebas para afinar):
    `prompt_seccion` (la conducción/preguntas que va al system_instruction) y `prompt_confirmacion`
    (la invitación a seguir). Versión preview con valores neutros."""
    secs = canva4g.SECCIONES
    out = []
    for i, pub in enumerate(canva4g.secciones_publicas()):
        s = secs[i]
        recap = _valores_seccion(s, {}) or "(lo que el usuario haya dicho)"
        sig = secs[i + 1]["titulo"] if i + 1 < len(secs) else None
        minutos = 20 if s["key"] == "presentacion" else None
        out.append({
            **pub,
            "prompt_seccion": _instruccion_seccion(s, arranque=False, reanuda=False, datos={}),
            "prompt_confirmacion": _guion_confirmacion(s, recap, sig, minutos),
        })
    return out


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
    # Limpia también el Canva EN MEMORIA de la sesión WS viva (si la hay), para que al cerrar no
    # re-guarde el viejo y deshaga el reset.
    sh = _SESIONES_4G.get(user_id)
    if sh is not None:
        sh["canva"] = {}
        sh["_await_confirm"] = False
        sh["_done_sec"] = False
        sh["_booked"] = False
        sh["sec_idx"] = 0
        logger.info(f"[4g] reset: limpiada la sesión WS activa de user={user_id} (Canva en memoria)")
    await canva4g.borrar_canva(user_id)
    logger.info(f"[4g] reset user={user_id}: Canva borrado, {borrados} evento(s) de Calendar")
    return {"ok": True, "eventos_borrados": borrados}


@router.get("/api/4g/canva")
async def get_canva(user_id: str):
    """Canva guardado + sección activa + keys completas (para pintar el estado real al entrar)."""
    canva = await canva4g.obtener_canva(user_id)
    return {"canva": canva, "secciones": _secciones_publicas_con_prompt(),
            "activa": canva4g.primera_incompleta(canva), "completas": canva4g.completas(canva)}
