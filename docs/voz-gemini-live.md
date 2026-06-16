# Voz en AppVoz — Llamada con Gemini Live (resolución y diseño)

Doc de respaldo del trabajo de la **llamada de voz** (vertical de prueba: "Lucía", comercial
de peluquería). Resume la arquitectura final, el bug que costó cerrar y cómo se resolvió.

## Objetivo
Una llamada de voz **inmersiva** (que no se note que es IA): voz nativa, baja latencia,
barge-in. Caso de prueba sin RAG para **validar la calidad del modelo de voz**.

## Arquitectura final (la que funciona)
**Relay directo a Gemini Live, sin Pipecat ni WebRTC.**
```
Navegador  ──WebSocket /ws/call (PCM16 16kHz)──►  FastAPI  ──►  Gemini Live API
           ◄──WebSocket (PCM16 24kHz)───────────           ◄──  (audio + transcripción)
```
- Frontend: `backend/static/live/` (HTML/JS plano, estilo WhatsApp con scroll propio).
  Captura mic a 16kHz, reproduce el audio 24kHz de Gemini, barge-in (flush al recibir
  `interrupted`).
- Backend: `backend/app/live_relay.py` — `client.aio.live.connect(model=...)`,
  `send_realtime_input(audio=Blob("audio/pcm;rate=16000"))`, recibe audio + transcripción.
- Modelo: `gemini-2.5-flash-native-audio-preview-12-2025` (único Live disponible con la
  API key del Developer API; los `gemini-2.0-flash-live-001` / `gemini-live-2.5-flash-preview`
  dan "not found"). Voz "Aoede". Persona en `app/persona.py`.

### Por qué relay (y no navegador↔Gemini directo)
El backend queda **en medio de los dos sentidos**, que es lo que habilita el **RAG por
inyección, guardar conversación y lógica de negocio** del futuro tutor — sin perder
inmersión (latencia despreciable). El directo (token efímero + SDK JS) deja el backend
fuera del bucle → RAG/logging/tools solo por function-calling o cliente. Es el patrón de
producción (media-server en medio, como LiveKit/Daily).

## El bug que costó (y la solución)
**Síntoma:** Gemini recibía la voz del usuario ALTA y clara (sonda: pico ~48% de escala)
pero **no transcribía ni respondía**; intermitente.

**Diagnóstico (con bancos sintéticos, sin micro):**
1. El audio que llega a Gemini es perfecto → el **STT batch de Gemini lo transcribe** OK
   ("Hola, ¿se me escucha?"). Descartado audio/formato/navegador.
2. El MISMO audio por `send_realtime_input` en streaming → **Gemini Live NO reacciona**.
   Reproducido en backend puro (sin navegador). → No es el relay ni el navegador.
3. Causa raíz: **el VAD automático (automatic activity detection) de Gemini Live NO
   dispara fiablemente** por la vía `send_realtime_input` (3/3 sin respuesta, incluso con
   silencio final).
4. Con **señalización manual de turno** (`activity_start` + audio + `activity_end`, y
   `automatic_activity_detection.disabled=True`) → **transcribe y responde al 100%**.

**Solución (en `live_relay.py`):** VAD por **energía** en el relay que detecta inicio/fin
de habla y le señaliza el turno a Gemini.
- `SPEECH_PEAK = 1000` (pico de amplitud; silencio ~200-350, voz ~8000-15000).
- `END_SILENCE = 12` frames (~1s) de silencio para cerrar el turno.
La detección de turno propia es **invisible para el usuario** y es lo normal en producción.

### Otros hallazgos / gotchas
- El corte de llamada a **~60s NO era de Gemini** (probado: aguanta 90s con audio
  continuo). Era el **ping-timeout de uvicorn** bajo audio continuo → en docker-compose el
  comando lanza uvicorn con `--ws-ping-timeout 300`.
- `session.receive()` **entrega un turno y se cierra** → hay que envolverlo en `while True`.
- Pipecat se probó y se **descartó** (SmallWebRTC, choques de versión 0.0.57↔1.3.0, dos VAD
  peleándose, endpoint /start, libs de sistema). Más capas = más fallos.

## Cómo probar
`docker compose up -d` → http://localhost:8080/call/ → "Iniciar llamada" → hablar en
español con pausa de ~1s al acabar cada frase. Banco cascada v1 (push-to-talk, Chirp 3 HD)
sigue en `/ui`.

## Pendiente / siguiente
- Afinar umbrales VAD (`SPEECH_PEAK`, `END_SILENCE`) a la voz real.
- Guardar conversación en Postgres (tablas `conversaciones`/`mensajes` ya creadas al arrancar).
- Para el TUTOR: inyectar RAG (pgvector) por turno en el relay; persona/skills por vertical.
- Cloud: WebRTC no, pero este relay es WebSocket → desplegable; revisar coste audio nativo.
