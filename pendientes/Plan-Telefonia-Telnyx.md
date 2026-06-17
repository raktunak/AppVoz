# Plan — Telefonía (PSTN) sobre Gemini Live vía Telnyx

> Objetivo: hacer y recibir llamadas telefónicas reales atendidas por nuestro
> "modelo de voz" (Gemini Live *native audio*), reutilizando el patrón
> **"backend en medio"** que ya tenemos en [`live_relay.py`](../backend/app/live_relay.py).
> Estado: PLAN (sin código todavía). Decisión de operador: **Telnyx** (ver §0).

## 0. Por qué Telnyx (resumen de la valoración)

Nuestro modelo de voz hace **STT + LLM + TTS + VAD en un único endpoint** (Gemini Live
native audio, 16 kHz PCM in / 24 kHz PCM out). Por tanto:

- **El operador es la ÚNICA pieza de terceros que falta.** No metemos STT/TTS/LLM
  externos: añadirlos sumaría 200–600 ms y mataría la expresividad del audio nativo.
- Telnyx soporta **streaming bidireccional por WebSocket con códec L16 a 16 kHz**
  (lista oficial: `L16 (16 kHz), PCMU, PCMA, G722, OPUS 8/16 kHz, AMR-WB 8/16 kHz`),
  y permite **códec del stream ≠ códec de la llamada SIP**. → la entrada a Gemini
  llega ya a 16 kHz **sin resamplear**; solo queda bajar la salida 24k→16k.
- Números españoles ~1 $/mes, backbone privado (latencia EU baja), precio bajo.
- **Plan B = Twilio** (más documentado, ejemplos Gemini Live públicos) pero Media
  Streams es μ-law 8 kHz → transcodificación en ambos sentidos y banda estrecha.
  *Nota:* Twilio **ConversationRelay NO sirve** aquí (hace su propio STT/TTS → anula
  el audio nativo de Gemini).
- **Pipecat descartado para esta vía de momento:** su `TelnyxFrameSerializer` solo
  hace PCMU/PCMA 8 kHz hoy (L16 16 kHz es un PR sin mergear). Para aprovechar L16
  ahora → **endpoint propio**, clon de los relays actuales.

## 1. Arquitectura objetivo

```
 Llamante (PSTN)
      │
      ▼  RTP/SIP
 ┌──────────────────────────────┐
 │ Telnyx (PoP EU)              │  Voice API / TeXML:
 │  - contesta la llamada       │   answer + streaming_start (bidireccional, L16 16k)
 │  - abre Media Stream WS      │
 └──────────────┬───────────────┘
                │  WSS  (frames JSON: start / media base64 / stop / clear / dtmf)
                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ Cloud Run  ── FastAPI  /ws/telnyx  (telnyx_relay.py)           │
 │   _telnyx_to_gemini:  decodifica frame → [si L16 16k: directo] │
 │                        → session.send_realtime_input(16k)      │
 │   _gemini_to_telnyx:  audio 24k → resample 16k → base64        │
 │                        → frame media de vuelta a Telnyx        │
 │   (reutiliza _build_config, VAD, _AcumuladorTurnos, persistence)│
 └──────────────┬───────────────────────────────────────────────┘
                │
                ▼
        Gemini Live (Vertex AI)   ← OJO: hoy en us-central1 (ver §7 R1)
```

El backend sigue EN MEDIO de los dos sentidos (clave para RAG/logging futuros), igual
que la vía navegador. Cambia **el transporte** (protocolo Telnyx en vez de PCM crudo del
navegador) y aparece **la transcodificación de sample rate**.

## 2. Fases

### Fase 0 — Cuenta y número (pre-código, requiere acción humana)
- [ ] Crear cuenta Telnyx; cargar saldo de prueba.
- [ ] Comprar **número español (DID)** (requisitos de documentación para ES, ver doc Telnyx).
- [ ] Crear una **Voice API application** (Call Control) o un **TeXML application**.
- [ ] **Confirmar precios** inbound + media-streaming a España (lo único que quedó sin fijar).
- [ ] Decidir alcance v1: **inbound** primero (recibir), outbound después.

### Fase 1 — Endpoint `/ws/telnyx` (núcleo, espejo de `live_relay.py`)
- [ ] Nuevo módulo `backend/app/telnyx_relay.py` con `router` (APIRouter).
- [ ] `@router.websocket("/ws/telnyx")`: acepta el WS de Telnyx.
- [ ] Parsear el protocolo de **Media Streaming**: eventos JSON
      `connected` / `start` (trae `stream_id`, formato, `call_control_id`, `client_state`)
      / `media` (`{"event":"media","media":{"payload":"<base64>"}}`) / `stop` / `dtmf`.
      ⚠️ Confirmar nombres exactos de campos contra la doc (no de memoria).
- [ ] Abrir la sesión Gemini Live con `_build_config(cfg)` (reutilizado tal cual; el `cfg`
      sale del `client_state`/headers que mandemos en el `streaming_start`).
- [ ] Dos corrutinas espejo de las del navegador:
      - `_telnyx_to_gemini(ws, session, ...)`
      - `_gemini_to_telnyx(ws, session, acc, shared)`
- [ ] Reutilizar `_AcumuladorTurnos` + `persistence` con `via="telnyx"`.

### Fase 2 — Transcodificación de audio (`backend/app/audio_codec.py`)
Helpers reutilizables y con **estado de filtro** entre frames (no resamplear frame a frame sin estado):
- [ ] **Entrada → Gemini:**
      - Si negociamos **L16 16 kHz** con Telnyx → **passthrough** directo a `Blob(rate=16000)`.
      - Fallback μ-law 8 kHz: `audioop.ulaw2lin` → `audioop.ratecv(8k→16k)`.
- [ ] **Salida ← Gemini (24 kHz PCM):**
      - `audioop.ratecv(24k→16k)` → base64 → frame `media` de vuelta (L16 16k).
      - Fallback: 24k→8k + `audioop.lin2ulaw`.
- [ ] **Framing:** Telnyx espera chunks de ~20 ms; trocear/acumular al tamaño correcto
      (mantener buffer; no asumir que el frame de Gemini = frame de Telnyx).

### Fase 3 — Señalización inbound
- [ ] Webhook HTTP (`POST /telnyx/voice`) que recibe el evento `call.initiated`.
- [ ] Responder iniciando streaming bidireccional hacia `wss://<cloud-run>/ws/telnyx`:
      - **TeXML:** verbo `<Stream url="wss://…" bidirectionalMode="rtp" codec="L16" … />`, o
      - **Call Control:** comando `streaming_start` con `stream_url`,
        `stream_bidirectional_mode="rtp"`, `stream_bidirectional_codec="L16"`,
        `stream_track`. ⚠️ Confirmar parámetros exactos.
- [ ] Pasar config de sesión (subject_id, voz, modelo, system_instruction) por
      `client_state` (base64) o custom headers → llega al `start` del WS.

### Fase 3b — Señalización outbound (si entra en alcance)
- [ ] Endpoint REST propio (`POST /telnyx/dial`) que origina la llamada con la
      Call Control API (`/calls`), y al `call.answered` lanza `streaming_start`.

### Fase 4 — Turno / barge-in en banda telefónica
- [ ] **Re-tunear el VAD por energía**: los umbrales actuales (`OPEN_PEAK=1300`, etc.)
      están calibrados para micro a 16 kHz con cancelación de eco del navegador; en la
      señal del operador la escala cambia. Empezar conservador y ajustar con llamadas reales.
- [ ] **Alternativa a evaluar:** reactivar el **VAD nativo de Gemini** (hoy desactivado en
      `_build_config`) sobre la señal limpia del operador — puede ir mejor que el nuestro y
      evita doble-VAD. Decisión empírica.
- [ ] **Barge-in:** al detectar que el usuario interrumpe, enviar el evento `clear` de
      Telnyx para vaciar el buffer de audio en curso (equivalente al `interrupted` del
      navegador). Mantener `shared["bot_speaking"]` igual que ahora.

### Fase 5 — Seguridad y robustez
- [ ] **Verificar la firma del webhook Telnyx** (Ed25519, cabeceras `telnyx-signature-ed25519`).
- [ ] **Autenticar el WS**: token corto en la URL (`/ws/telnyx?t=…`) o en `client_state`.
- [ ] **Timeouts Cloud Run**: subir el request timeout (las llamadas duran minutos; Cloud
      Run admite WS hasta 60 min) y revisar `--concurrency`.
- [ ] **Concurrencia / límites**: cada llamada = 1 WS + 1 sesión Live. Vigilar el límite de
      **sesiones Live concurrentes** de Vertex y dimensionar instancias.

### Fase 6 — Observabilidad y pruebas
- [ ] Métricas de latencia telefónica (ttfa: voz→primer audio) por log, como en la vía cascada.
- [ ] Logs de framing/transcode detrás de un flag de debug (y quitar luego, como los `# TEMP`).
- [ ] Persistencia ya funciona → solo nuevo `via="telnyx"`.
- [ ] **Smoke test echo** (ver §6) antes de enchufar Gemini.

## 3. Archivos a tocar

| Archivo | Acción |
|---|---|
| `backend/app/telnyx_relay.py` | **nuevo** — router WS `/ws/telnyx` + webhook + (outbound) |
| `backend/app/audio_codec.py` | **nuevo** — helpers de transcodificación con estado |
| `backend/app/main.py` | incluir `telnyx_router` (junto a voice/live) |
| `backend/app/config.py` | settings: `telnyx_api_key`, `telnyx_public_ws_url`, `telnyx_number`, `telnyx_webhook_public_key` |
| `.env.example` | nuevas variables (sin secretos) |
| `pendientes/Plan-Telefonia-Telnyx.md` | este doc |

Secretos (`TELNYX_API_KEY`, clave pública del webhook) → en el servicio Cloud Run, **no**
en `cloudbuild.yaml` (mismo criterio que `DATABASE_URL`/`GOOGLE_API_KEY`).

## 4. Lo que se REUTILIZA tal cual (no reescribir)

- `_build_config()` — construcción del `LiveConnectConfig` por sesión.
- VAD por energía + helpers `_clamp_*` / `_vad_from_open` (solo re-tunear constantes).
- `_AcumuladorTurnos` + `persistence` (sesiones/turnos/memoria) con `via="telnyx"`.
- Patrón de dos corrutinas `up`/`down` con `asyncio.wait(FIRST_COMPLETED)`.

## 5. Decisión: ¿endpoint propio o Pipecat?
**Propio** (recomendado ahora): controlamos L16 16 kHz ya, mínima transcodificación, mismo
estilo que el resto del repo. Pipecat tendría serializer "de fábrica" pero su Telnyx aún no
hace L16 16 kHz (PR abierto) → perderíamos la ventaja de calidad/latencia.

## 6. Primer paso accionable (cuando se apruebe construir)
1. Cuenta Telnyx + número ES + app Call Control/TeXML (Fase 0).
2. **Smoke test sin Gemini**: `/ws/telnyx` que haga **eco** del audio (lo que entra se
   devuelve) para validar protocolo + framing + bidireccionalidad + L16. Telnyx documenta
   justo este patrón de eco con L16 16 kHz.
3. Sustituir el eco por la sesión Gemini Live (Fase 1).
4. Señalización inbound (Fase 3) → primera llamada real de prueba a un número español.
5. Iterar VAD/barge-in con llamadas reales (Fase 4).

## 7. Riesgos y decisiones abiertas

- **R1 · Latencia geográfica.** Live está hoy en **us-central1** ([`config.py`](../backend/app/config.py)).
  Ruta: llamante EU → Telnyx EU → Cloud Run EU → Vertex **US**. El salto transatlántico
  añade ~100–150 ms RTT. Ya existe en la vía navegador, pero en teléfono pesa más.
  **Decisión:** ¿hay región **EU** disponible para Live native-audio? Si la hay, mover allí
  para llamadas; si no, asumir el coste de latencia. (La nota del código sugiere que EU no
  estaba disponible cuando se configuró.)
- **R2 · Esquema exacto del protocolo Telnyx.** Nombres de eventos/campos y parámetros de
  `streaming_start` hay que confirmarlos contra la doc viva, no de memoria.
- **R3 · Precio inbound a ES.** Sin fijar; confirmar antes de comprometer (Fase 0).
- **R4 · Doble VAD.** Coordinar nuestro VAD con el del operador/Gemini para no competir.
- **R5 · Coste del audio Live.** Caro ($3/$12 por 1M tokens audio in/out). Una llamada
  larga no es barata; medir coste por minuto en pruebas.
- **R6 · RAG ausente en esta vía.** Igual que `/call` hoy: usa `SALON_PERSONA`, sin RAG.
  La telefonía es ortogonal, pero "tutor por teléfono de verdad" necesitará inyectar el
  material aquí (pendiente aparte).

## 8. Fuera de alcance (por ahora)
- Transferencias a humano, IVR/DTMF complejos, grabación/compliance, multi-número,
  colas/horarios. Se abordan cuando inbound básico funcione.
