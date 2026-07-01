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

from . import agenda, auth, canva4g, persistence
from .config import settings
from .live_relay import _browser_to_gemini, _build_config, _client, _vad_params
from .rag import retrieve

router = APIRouter()

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Herramientas (function-calling) del ASISTENTE «Habla con Faro»: consultar el libro (RAG) y gestionar
# el Google Calendar del usuario. Es el cimiento de la "acción por voz" (Fase 2).
TOOLS_ASISTENTE = [types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="buscar_en_libro",
        description="Busca en el libro 'La Agenda de Cuarta Generación' de Fabián González para "
                    "responder anclado a su contenido. Úsala SIEMPRE que pregunten por el libro o el método.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={"consulta": types.Schema(type=types.Type.STRING,
                        description="La pregunta o tema a buscar en el libro.")},
            required=["consulta"],
        ),
    ),
    types.FunctionDeclaration(
        name="crear_evento",
        description="Crea un evento/bloque en el Google Calendar del usuario.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "titulo": types.Schema(type=types.Type.STRING, description="Título del evento."),
                "fecha_hora_iso": types.Schema(type=types.Type.STRING,
                    description="Inicio en ISO 8601 con offset, p.ej. 2026-07-02T10:00:00+02:00."),
                "duracion_min": types.Schema(type=types.Type.INTEGER,
                    description="Duración en minutos (por defecto 60)."),
            },
            required=["titulo", "fecha_hora_iso"],
        ),
    ),
    types.FunctionDeclaration(
        name="listar_eventos",
        description="Lista los próximos eventos del Google Calendar del usuario (para verlos o para "
                    "obtener el event_id antes de borrar uno).",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="borrar_evento",
        description="Borra un evento del Google Calendar del usuario por su event_id "
                    "(obtenlo antes con listar_eventos).",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={"event_id": types.Schema(type=types.Type.STRING,
                        description="ID del evento a borrar.")},
            required=["event_id"],
        ),
    ),
])]


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


def _guion_agente(seccion: dict) -> str:
    """Las preguntas LITERALES de un bloque, para inyectar el guion del 'agente' de esa fase."""
    if seccion.get("tipo") == "lista":
        return f"«{seccion.get('pregunta', '')}»"
    return "  ".join(f"«{a['pregunta']}»" for a in seccion.get("apartados", []) if a.get("pregunta"))


async def _inyectar_agente(session, shared: dict, idx: int, repasar: bool = False) -> None:
    """RELEVO DE ROL en la MISMA sesión (sin reconectar → la voz NO se toca): convierte a Faro en el
    'agente' del bloque `idx`, pasándole la memoria de lo ya capturado (resumen) y SOLO las preguntas
    de esa fase. Es 'un agente nuevo coge el testigo', pero dentro de una sola línea de audio.
    `repasar=True` (botón «Repasar» sobre un bloque YA completo): no conduce el guion ni relee los
    datos (la persona los ve en pantalla); solo pregunta si quiere cambiar o añadir algo de ese bloque."""
    if session is None or not (0 <= idx < len(canva4g.SECCIONES)):
        return
    seccion = canva4g.SECCIONES[idx]
    # Guion EDITABLE desde el desplegable del navegador (para afinar el prompt de cada agente en vivo);
    # si no se ha tocado, el guion por defecto = las preguntas literales del bloque.
    guion = (shared.get("_guion_custom", {}).get(idx) or "").strip() or _guion_agente(seccion)
    resumen = canva4g.resumen_canva(shared.get("canva"))
    # Si se RETOMA un apartado a medias (pausado), decimos QUÉ ya tiene para que pregunte solo lo que falta.
    datos = shared.get("canva", {}).get(seccion["key"]) or {}
    if seccion.get("tipo") == "lista":
        _arr = datos.get(seccion["lista"]) or []
        capturado = "; ".join((x.get("valor") or x.get("nombre") or "") for x in _arr if isinstance(x, dict))
    else:
        capturado = "; ".join(f"{a['etiqueta']}: {datos[a['campo']]}"
                              for a in seccion.get("apartados", []) if datos.get(a["campo"]))
    if not shared.get("presentado"):
        apertura = "Es el COMIENZO: preséntate en UNA sola frase como Faro, la guía."
        shared["presentado"] = True
    else:
        apertura = "Enlaza con naturalidad, SIN volver a presentarte ni saludar de nuevo."
    partes = [f"(Ahora céntrate SOLO en la fase «{seccion['titulo']}». {apertura}"]
    if resumen:
        partes.append(f"Para dar continuidad (NO lo repreguntes), la persona YA te ha contado: {resumen}.")
    if repasar:
        # MODO REPASO: el bloque YA está completo y la persona lo VE en pantalla. No conducir el guion
        # ni releérselo; solo ofrecerle modificarlo. `capturado` va como contexto silencioso para que
        # entienda correcciones del tipo "cambia el tiempo a 30".
        if capturado:
            partes.append(f"(Contexto, NO lo leas en voz alta) lo que tienes anotado de este apartado: {capturado}.")
        partes.append(
            "La persona ya completó este apartado y lo está viendo en pantalla, así que NO se lo releas. "
            f"Pregúntale en UNA sola frase cálida si quiere cambiar o añadir algo de «{seccion['titulo']}». "
            "Si dice que no o que está bien, agradece en UNA frase y PARA. Si pide un cambio, recoge SOLO "
            "eso, confírmaselo y PARA. NO hagas las preguntas de cero ni pases a otra fase.)")
    else:
        # ANCLAJE AL LIBRO (RAG): ideas de Fabián que sostienen el coaching de este bloque. Se
        # recuperan del corpus del servicio (subject_id) y se inyectan como MATERIAL de apoyo.
        rag_query = canva4g.RAG_QUERIES.get(seccion["key"])
        if rag_query and shared.get("subject_id"):
            try:
                frags = await retrieve(shared["subject_id"], rag_query, k=3)
            except Exception:
                logger.exception("[4g] RAG retrieve falló; sigo sin material")
                frags = []
            material = " /// ".join((f.get("content") or "").strip() for f in frags)
            if material:
                partes.append(
                    "Apóyate en estas IDEAS del libro de Fabián para guiar y matizar este bloque "
                    "(NO las leas literal; úsalas con tus palabras y cita una frase corta solo si "
                    "encaja; si algo no está aquí, no lo inventes): " + material)
        partes.append(
            f"Haz estas preguntas, una a una y TAL CUAL (palabra por palabra), esperando respuesta a cada "
            f"una antes de la siguiente: {guion}")
        if capturado:
            partes.append(f"De ESTE apartado la persona YA te dio: {capturado}. NO lo repreguntes; "
                          f"continúa pidiendo SOLO lo que falte.")
        partes.append("Cuando tengas TODAS esas respuestas, NO preguntes más ni pases a otra fase: "
                      "agradece en UNA frase y PARA (yo me encargo de invitar a continuar).)")
    shared["bot_speaking"] = True
    try:
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text=" ".join(partes))])],
            turn_complete=True,
        )
        logger.info(f"[4g] agente «{seccion['titulo']}» (idx={idx}) en marcha")
    except Exception:
        logger.exception("[4g] no pude inyectar el agente de sección")


async def _invitar_siguiente(session, shared: dict, idx: int) -> None:
    """El bloque `idx` está completo: Faro invita a la persona a pulsar el siguiente apartado cuando
    quiera. NO auto-avanza (la transición la inicia el USUARIO con el botón del bloque)."""
    if session is None:
        return
    seccion = canva4g.SECCIONES[idx]
    nxt = idx + 1
    siguiente = canva4g.SECCIONES[nxt]["titulo"] if nxt < len(canva4g.SECCIONES) else None
    if siguiente:
        txt = (f"(Ya tienes todo lo de «{seccion['titulo']}». Dile a la persona, en UNA frase breve y "
               f"cálida, que cuando quiera puede pulsar «{siguiente}» para seguir. NO empieces tú esa "
               f"fase ni hagas más preguntas: solo invítale y espera.)")
    else:
        txt = ("(Habéis completado TODO el Canva. Felicítale en una frase y dile que su Plataforma "
               "Estratégica Personal ya está lista. No hagas más preguntas.)")
    shared["bot_speaking"] = True
    try:
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text=txt)])],
            turn_complete=True,
        )
        logger.info(f"[4g] '{seccion['key']}' completo → invito a seguir (siguiente={siguiente})")
    except Exception:
        logger.exception("[4g] no pude invitar a seguir")


async def _ejecutar_funcion(nombre: str, args: dict, shared: dict, ws: WebSocket) -> dict:
    """Ejecuta una herramienta del asistente Faro y devuelve el dict de respuesta para Gemini."""
    try:
        if nombre == "buscar_en_libro":
            chunks = await retrieve(shared.get("subject_id") or "libro-4g", args.get("consulta", ""), k=3)
            return {"fragmentos": [c["content"] for c in chunks] or ["(sin resultados en el libro)"]}
        # Las funciones de calendario requieren la sesión Google del usuario.
        creds = await auth.credenciales_calendar(shared["user_id"]) if shared.get("autenticado") else None
        if not creds:
            return {"error": "El usuario no ha iniciado sesión con Google; no puedo usar su calendario."}
        if nombre == "crear_evento":
            inicio = datetime.fromisoformat(args["fecha_hora_iso"])
            ev = await agenda.crear_evento_con_creds(
                creds, inicio, calendar_id="primary",
                duracion_min=int(args.get("duracion_min") or 60), resumen=args.get("titulo") or "Bloque")
            await ws.send_text(json.dumps({"type": "booked", "ok": True, "event": ev}))
            return {"ok": True, "evento": ev}
        if nombre == "listar_eventos":
            return {"eventos": await agenda.listar_eventos_con_creds(creds)}
        if nombre == "borrar_evento":
            return {"ok": await agenda.borrar_evento_con_creds(creds, args["event_id"])}
        return {"error": f"función desconocida: {nombre}"}
    except Exception as e:
        logger.exception(f"[4g] error ejecutando función {nombre}")
        return {"error": str(e)}


async def _manejar_tool_call(tool_call, session, shared: dict, ws: WebSocket) -> None:
    """Ejecuta las funciones que pide el modelo (asistente Faro) y devuelve los resultados a Gemini."""
    respuestas = []
    for fc in (getattr(tool_call, "function_calls", None) or []):
        args = dict(fc.args or {})
        logger.info(f"[4g] tool_call {fc.name}({args})")
        resultado = await _ejecutar_funcion(fc.name, args, shared, ws)
        respuestas.append(types.FunctionResponse(id=fc.id, name=fc.name, response=resultado))
    if respuestas:
        await session.send_tool_response(function_responses=respuestas)


def _texto_memoria(mem: dict | None) -> str:
    """Aplana la memoria acumulada (resumen + temas + dudas) a una frase para inyectar en el prompt."""
    if not mem:
        return ""
    partes = []
    if mem.get("resumen"):
        partes.append(mem["resumen"].strip())
    if mem.get("temas"):
        partes.append("Temas ya tratados: " + ", ".join(mem["temas"]) + ".")
    if mem.get("dudas"):
        partes.append("Dudas o temas pendientes: " + ", ".join(mem["dudas"]) + ".")
    return " ".join(partes)


def _prompt_asistente(shared: dict) -> str:
    """Construye el prompt del asistente: consignas de herramientas + CONTEXTO del usuario (su
    Canva/PEP + memoria acumulada), para que Faro responda sobre SU vida y no solo sobre el libro
    ("¿en qué me enfoco esta semana según mis roles?"). Puro (sin efectos) para poder testearlo."""
    partes = [
        "(CHARLA LIBRE CON FARO. Olvida el guion de fases del Canva. Eres Faro, cálido y breve. "
        "Tienes herramientas: buscar_en_libro (consulta el libro de Fabián y responde anclado a él; "
        "si algo no está, dilo), y para el Google Calendar del usuario: crear_evento, listar_eventos y "
        "borrar_evento. Cuando pregunten por el libro o el método, USA buscar_en_libro. Cuando pidan "
        "agendar, ver o borrar citas, USA la herramienta y CONFIRMA por voz lo que hiciste (para borrar, "
        "lista primero para localizar el id)."
    ]
    # CONTEXTO del usuario: que Faro sepa de él (su Plataforma Estratégica Personal + lo que recuerda).
    resumen = canva4g.resumen_canva(shared.get("canva"))
    if resumen:
        partes.append(
            "LO QUE YA SABES DE ESTA PERSONA (su Plataforma Estratégica Personal): " + resumen +
            " Úsalo para responder sobre SU vida (sus roles, objetivos y prioridades), no solo el libro.")
    memoria = shared.get("memoria")
    if memoria:
        partes.append("RECUERDAS de conversaciones anteriores con ella: " + memoria)
    saludo = "Saluda en UNA frase"
    if resumen or memoria:
        saludo += " y, como ya la conoces, personaliza el saludo con algo suyo"
    partes.append(saludo + ". Invita a preguntar por el libro, pedirte una cita, o algo de su plan.)")
    return " ".join(partes)


async def _inyectar_asistente(session, shared: dict) -> None:
    """Asistente «Habla con Faro»: conversación libre con herramientas (RAG del libro + Calendar del
    usuario). Copiloto siempre disponible; no recorre el guion de fases del Canva. Le inyecta el
    CONTEXTO del usuario (su Canva/PEP + memoria) vía `_prompt_asistente`."""
    if session is None:
        return
    shared["sec_idx"] = 10_000   # fuera del rango de SECCIONES → no se extrae nada del Canva
    shared["presentado"] = True
    txt = _prompt_asistente(shared)
    shared["bot_speaking"] = True
    try:
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text=txt)])], turn_complete=True)
        logger.info("[4g] asistente «Habla con Faro» en marcha")
    except Exception:
        logger.exception("[4g] no pude iniciar el asistente")


async def _control_4g(data: dict, session, shared: dict) -> None:
    """Mensajes de control del navegador propios del 4g. {type:'goto', idx, repasar}: el USUARIO inicia
    el apartado `idx` → relevamos al agente de ese bloque en la misma sesión (inicio manual). `repasar`
    (botón «Repasar» sobre un bloque ya completo) hace que el agente solo ofrezca cambios, no reentreviste.
    {type:'asistente'} (alias 'probador'): conversación libre con herramientas (RAG + Calendar)."""
    if data.get("type") in ("asistente", "probador"):   # 'probador' = alias temporal (compat)
        shared["_hablo_en_bloque"] = False
        await _inyectar_asistente(session, shared)
        return
    if data.get("type") != "goto":
        return
    try:
        idx = int(data.get("idx"))
    except (TypeError, ValueError):
        return
    if not (0 <= idx < len(canva4g.SECCIONES)):
        return
    guion = (data.get("guion") or "").strip()   # prompt editado en el desplegable del navegador
    if guion:
        shared.setdefault("_guion_custom", {})[idx] = guion
    repasar = bool(data.get("repasar"))   # «Repasar»: el bloque YA está completo → solo ofrecer cambios
    shared["sec_idx"] = idx
    shared["_hablo_en_bloque"] = False   # al (re)abrir el bloque, aún no ha hablado el usuario en él
    shared.get("_invitado", set()).discard(canva4g.SECCIONES[idx]["key"])   # permite re-cerrar al recompletar
    await _inyectar_agente(session, shared, idx, repasar=repasar)


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
    # STT fiable de respaldo: re-transcribe el audio del último turno en ESPAÑOL (corrige los nombres
    # que native-audio destroza, p.ej. 'José'→'Suchen') y se lo damos al extractor como fuente prioritaria.
    audio_turno = shared.pop("_turno_audio", None)
    stt_fiable = await canva4g.transcribir_audio(audio_turno) if audio_turno else ""
    if stt_fiable:
        logger.info(f"[4g] STT fiable: «{stt_fiable}»")
    datos = await canva4g.extraer_seccion(seccion["key"], conv, shared["fecha_str"], stt_fiable)
    if not datos:
        return
    if shared.get("sec_idx") != idx:
        return   # TAREA OBSOLETA: el usuario cambió de bloque mientras corrían el STT/extracción (lentos).
                 # Sin esto, una extracción del bloque anterior podría invitar/cerrar el bloque NUEVO.
    # Merge no destructivo (no pisa datos ya capturados con vacíos).
    prev = shared["canva"].get(seccion["key"]) or {}
    shared["canva"][seccion["key"]] = canva4g.merge_seccion(seccion, prev, datos)
    logger.info(f"[4g] extracción '{seccion['key']}' -> {datos}")
    try:
        await ws.send_text(json.dumps({"type": "canva", "canva": shared["canva"],
                                       "completas": canva4g.completas(shared["canva"])}))
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
    invitados = shared.setdefault("_invitado", set())
    # Cerrar el bloque EN CUANTO está completo Y el usuario ha intervenido desde que se abrió (flag
    # `_hablo_en_bloque`, reseteado al abrir en _control_4g). Antes exigíamos una 2ª extracción
    # "estable", lo que retrasaba el cierre y dejaba a Faro hablando tras tener ya los datos.
    if (canva4g.seccion_completa(seccion, cur)
            and shared.get("_hablo_en_bloque")
            and key not in invitados):
        invitados.add(key)                                # SIN auto-avance: invitar UNA vez y CERRAR.
        if key == "bloque":
            await _agendar_bloque(ws, shared)
        logger.info(f"[4g] sección '{key}' COMPLETA → invito a seguir y cierro el bloque")
        await _invitar_siguiente(shared.get("session"), shared, idx)
        try:   # el navegador deja de escuchar este bloque (se cierra solo); el usuario abre el siguiente
            await ws.send_text(json.dumps({"type": "cerrado", "key": key, "idx": idx}))
        except Exception:
            pass
    elif not canva4g.seccion_completa(seccion, cur):
        invitados.discard(key)                            # dejó de estar completa → podrá re-cerrar luego


async def _agendar_bloque(ws: WebSocket, shared: dict):
    """Agenda en Google Calendar el primer bloque (rol + fecha_hora_iso). Idempotente."""
    if shared.get("_booked"):
        return
    bloque = shared["canva"].get("bloque") or {}
    iso, rol = bloque.get("fecha_hora_iso"), bloque.get("rol")
    if not iso or not rol:
        return
    try:
        inicio = datetime.fromisoformat(iso)
    except Exception:
        logger.warning(f"[4g] fecha_hora_iso no parseable: {iso}")
        await ws.send_text(json.dumps({"type": "booked", "ok": False, "error": "fecha no válida"}))
        return
    # Calendar DEL USUARIO (OAuth propio) si está logueado; si no, la SA + calendario compartido.
    creds = await auth.credenciales_calendar(shared["user_id"]) if shared.get("autenticado") else None
    try:
        if creds:
            ev = await agenda.crear_evento_con_creds(
                creds, inicio, calendar_id="primary", duracion_min=120, resumen=f"{rol} (4G)",
                descripcion="Primer bloque creado en el onboarding 4G.",
                datos={"rol": rol, "origen": "4g"},
            )
        else:
            cal = settings.calendar_id
            if not cal:
                await ws.send_text(json.dumps({"type": "booked", "ok": False,
                    "error": "Inicia sesión con Google (o falta CALENDAR_ID)"}))
                return
            ev = await agenda.crear_evento(
                cal, inicio, duracion_min=120, resumen=f"{rol} (4G)",
                descripcion="Primer bloque creado en el onboarding 4G.",
                telefono=shared["user_id"], datos={"rol": rol, "origen": "4g"},
            )
        shared["_booked"] = True
        await ws.send_text(json.dumps({"type": "booked", "ok": True, "event": ev}))
        logger.info(f"[4g] bloque agendado rol='{rol}' inicio={iso} event={ev.get('event_id')} "
                    f"calendar={'usuario' if creds else 'SA'}")
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
                tc = getattr(response, "tool_call", None)
                if tc:   # el modelo (asistente Faro) pide ejecutar una herramienta
                    await _manejar_tool_call(tc, session, shared, ws)
                    continue
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
                    shared["_hablo_en_bloque"] = True   # el usuario ha intervenido en el bloque activo
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
    autenticado = False
    # Identidad por la cookie de sesión (login Google). Si hay sesión, PREVALECE sobre el
    # user_id que mande el cliente (multiusuario real: cada alumno es su email).
    try:
        u = await auth.usuario_por_sid(ws.cookies.get(auth.COOKIE))
        if u:
            user_id, autenticado = u["email"], True
    except Exception:
        logger.exception("[4g] no pude resolver la sesión por cookie")
    try:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        txt = msg.get("text")
        if txt and not autenticado:   # sin login: acepto el user_id del cliente (dev/local)
            data = json.loads(txt)
            user_id = (data.get("user_id") or "anonimo").strip() or "anonimo"
    except Exception:
        logger.exception("[4g] handshake de config falló; sigo con user_id actual")

    cfg, subject_id = await _cargar_cfg_4g()
    fecha_str = _fecha_ctx()
    canva_prev = await canva4g.obtener_canva(user_id)
    try:   # memoria acumulada del usuario (la inyecta el asistente para "recordarte"). Best-effort.
        memoria = await persistence.obtener_memoria(user_id, subject_id)
    except Exception:
        logger.exception("[4g] no pude leer la memoria del usuario")
        memoria = None
    cfg = _preparar_prompt(cfg, fecha_str, canva_prev)
    model, live_config = _build_config(cfg, tools=TOOLS_ASISTENTE)   # herramientas del asistente Faro
    vad = _vad_params(cfg)

    shared = {
        "bot_speaking": False, "user_id": user_id, "autenticado": autenticado,
        "subject_id": subject_id,
        "canva": canva_prev or {}, "sec_idx": canva4g.primera_incompleta(canva_prev),
        "memoria": _texto_memoria(memoria),   # contexto del usuario para el asistente (paso 3)
        "fecha_str": fecha_str, "conv": "", "_last": None,
        "no_barge": True,   # anti-eco: el micro se ignora mientras Faro habla
        "_captura_turno": True,   # guarda el audio de cada turno para el STT fiable de respaldo
    }
    logger.info(f"[4g] sesión user={user_id} model={model} voz={cfg.get('voice')} "
                f"sec_idx={shared['sec_idx']}")
    try:
        async with _client.aio.live.connect(model=model, config=live_config) as session:
            shared["session"] = session   # para el relevo de rol por bloque (inyección en vivo)
            await ws.send_text(json.dumps({
                "type": "ready", "model": model,
                "secciones": canva4g.secciones_publicas(),
                "activa": shared["sec_idx"], "canva": shared["canva"],
                "completas": canva4g.completas(shared["canva"]),
            }))
            up = asyncio.create_task(
                _browser_to_gemini(ws, session, vad, shared, on_control=_control_4g))
            down = asyncio.create_task(_gemini_to_browser_4g(ws, session, shared))
            # SIN auto-arranque: Faro NO conduce solo. Cada apartado lo inicia el USUARIO con su botón
            # ({type:"goto", idx} → _control_4g → _inyectar_agente), de modo que son 'agentes' por
            # bloque (cada uno con la memoria de lo anterior) sobre UNA sola sesión → la voz no se toca.
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
            "activa": canva4g.primera_incompleta(canva),
            "completas": canva4g.completas(canva)}
