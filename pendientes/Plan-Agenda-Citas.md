# Plan — Agenda de citas por voz (Google Calendar + aviso)

> Objetivo: que la "secretaria" de voz **reserve, lea de vuelta y cancele citas de
> verdad** durante la llamada, escribiéndolas en un Google Calendar y avisando al
> negocio (y/o al cliente). Reutiliza el relay de Telnyx + Gemini Live y el patrón
> de extracción estructurada que ya tenemos.
> Estado: PLAN (sin código todavía). Fecha: 2026-06-18. Rama: `secretaria`.

## 0. Punto de partida (lo que ya juega a favor)

- La llamada de teléfono funciona de punta a punta: [telnyx_relay.py](../backend/app/telnyx_relay.py)
  → Gemini Live (Vertex), audio bidireccional L16 16k, VAD, barge-in, persistencia.
- El **teléfono del llamante ya lo tenemos** sin pedirlo: `from` del `start`, guardado en
  `shared["from"]` ([telnyx_relay.py:322](../backend/app/telnyx_relay.py#L322)).
- Ya **extraemos datos estructurados** de una transcripción con Flash (JSON validado):
  `resumir_sesion` ([persistence.py:460](../backend/app/persistence.py#L460)) — mismo patrón
  reutilizable para sacar la cita.
- La persona ya conduce hacia la cita pero **no reserva nada**: `SALON_PERSONA` dice
  *"la reserva en sistema se añadirá más adelante"* ([persona.py:25](../backend/app/persona.py#L25)).
- Capa de servicios multi-vertical ya enruta persona/voz por número marcado.
- Stack Google-first (GCP `brainrot-walloop`, SA `appvoz-voice`, Vertex) → Calendar y email
  caen en el mismo ecosistema y credenciales.

## 1. Alcance v1

**Dentro:** inbound; un servicio "secretaria"; **reservar** cita (nombre + teléfono +
fecha/hora) con **lectura de vuelta** y confirmación en la llamada; **cancelar** cita;
notificación de la cita; persistir cada cita con su `event_id`.

**Fuera (por ahora):** reprogramación compleja, comprobación de disponibilidad /
colisiones de horario, pagos, recordatorios automáticos, registro de usuarios + login
(va en Fase 5), multi-calendario por empleado.

## 2. Arquitectura objetivo

```
 Llamada (Telnyx ⇄ /ws/telnyx ⇄ Gemini Live native-audio)
        │
        │  el modelo decide y emite tool_call(agendar_cita | cancelar_cita)
        ▼
 ┌──────────────────────────────────────────────┐
 │ relay (live_relay.py / telnyx_relay.py)       │
 │   receive(): además de audio/transcripción,   │
 │   atiende `tool_call` → llama a agenda.py →    │
 │   responde con session.send_tool_response(...) │
 └───────────────┬───────────────────────────────┘
                 ▼
 ┌──────────────────────────────────────────────┐
 │ agenda.py (NUEVO)                             │
 │   crear_evento()  → Calendar API events.insert │
 │   buscar_eventos()→ events.list (por teléfono) │
 │   borrar_evento() → events.delete              │
 │   enviar_aviso()  → email (SMTP) / SMS (Telnyx)│
 └───────────────┬───────────────────────────────┘
                 ▼
        Google Calendar  +  tabla `citas` (event_id, datos)
```

El modelo confirma en la propia llamada ("te he reservado el martes a las 17:00").
La cita queda en Calendar y en nuestra tabla (para poder cancelar buscando por teléfono).

## 3. Decisiones de diseño (recomendadas)

| Decisión | Recomendación v1 | Alternativa / nota |
|---|---|---|
| **Captura de datos** | **Function-calling** dentro de Live (tools `agendar_cita`/`cancelar_cita`), marcadas **`NON_BLOCKING`** para que no haya silencio mientras Calendar responde | Extracción post-llamada (clon de `resumir_sesion`): más simple pero sin confirmación en vivo |
| **Auth Calendar** | **SA `appvoz-voice` + calendario dedicado compartido** con la SA (permiso "hacer cambios en eventos") | OAuth por dueño → Fase 5 (onboarding self-service) |
| **Notificación** | *(ABIERTA — ver §7)* por defecto **email al dueño**; SMS al cliente vía Telnyx como extra | Email al cliente exige capturar su email por voz (frágil) |
| **Modelo Live** | Validar tool-calling en **native-audio** | Fallback `gemini-live-2.5-flash` (half-cascade) si native-audio da problemas |
| **Zona horaria** | `Europe/Madrid` fija en el evento | Configurable por servicio más adelante |

## 4. Piezas nuevas

1. **`backend/app/agenda.py`** — `crear_evento(cal_id, inicio, dur, resumen, descripcion)`,
   `buscar_eventos(cal_id, telefono, desde)`, `borrar_evento(cal_id, event_id)`,
   `enviar_aviso(...)`. Devuelven datos serializables; errores controlados (no rompen la llamada).
2. **Definición de tools** (`types.FunctionDeclaration`): `agendar_cita(nombre, telefono,
   fecha_hora_iso, notas)` y `cancelar_cita(telefono, fecha_hora_iso?)`. Se añaden a
   `_build_config` ([live_relay.py:218](../backend/app/live_relay.py#L218)).
3. **Cableado `tool_call` → ejecución → `tool_response`** en los bucles `receive()` de
   `_gemini_to_browser` / `_gemini_to_telnyx`.
4. **Persona "secretaria"** en [persona.py](../backend/app/persona.py): conduce el flujo
   (nombre → confirmar teléfono → proponer/confirmar fecha → leer de vuelta → reservar) y
   sabe cuándo invocar cada tool.
5. **Inyección de fecha/hora actual + TZ** en el system prompt al abrir la sesión (el modelo
   no sabe "qué día es hoy"; sin esto no resuelve "mañana a las 5").
6. **Tabla `citas`** (DDL en [persistence.py](../backend/app/persistence.py)): `id`,
   `servicio_id`/`subject_id`, `telefono`, `nombre`, `inicio`, `event_id`, `estado`
   (reservada/cancelada), `creado`. Permite cancelar buscando por teléfono sin adivinar.
7. **Config/secretos** ([config.py](../backend/app/config.py)): `calendar_id`,
   `aviso_email`/credenciales SMTP, (opcional) flag SMS. Secretos → Cloud Run, no en
   `cloudbuild.yaml`. Nueva dependencia: `google-api-python-client` en requirements.

## 5. Fases (orden de ejecución y validación)

- **Fase 0 — Setup GCP/Telnyx (acción humana).** Habilitar **Google Calendar API** en el
  proyecto; crear un **calendario dedicado** y compartirlo con el email de la SA con permiso
  de escritura; fijar secretos (calendar_id, email/SMTP). (SMS: confirmar Telnyx Messaging.)
- **Fase 1 — `agenda.py` aislado.** `crear_evento`/`buscar`/`borrar`/`enviar_aviso` probados
  con un **script suelto** (estilo `_dur_test.py`), **sin teléfono**. Objetivo: que escribir y
  borrar en Calendar y mandar el aviso funcione solo.
- **Fase 2 — Tool-calling en la web `/call`.** Declarar las tools, persona secretaria,
  inyección de fecha; cablear `tool_call`/`tool_response`. Se itera en segundos (mejor que el
  teléfono). **Validar aquí el comportamiento de native-audio + NON_BLOCKING.**
- **Fase 3 — Llevarlo a `/ws/telnyx`.** Misma lógica de tools en el relay telefónico; primera
  **llamada real** que reserva una cita y la confirma de viva voz.
- **Fase 4 — Cancelar cita.** `cancelar_cita`: `buscar_eventos` por teléfono → leer de vuelta
  la cita encontrada → confirmar → `borrar_evento`; actualizar estado en tabla `citas`.
- **Fase 5 — (futuro) Onboarding multi-tenant.** Registro + **"Entrar con Google" (OAuth)**:
  cada dueño concede acceso a *su* calendario (refresh token por usuario) y configura su
  servicio en el panel. Más adelante: disponibilidad/colisiones, recordatorios.

## 6. Archivos a tocar

| Archivo | Acción |
|---|---|
| `backend/app/agenda.py` | **nuevo** — Calendar + aviso (helpers aislados) |
| `backend/app/persona.py` | persona "secretaria" + flujo de captura |
| `backend/app/live_relay.py` | tools en `_build_config` + manejo `tool_call` en `receive()` |
| `backend/app/telnyx_relay.py` | mismo manejo de `tool_call` en el relay telefónico |
| `backend/app/persistence.py` | DDL + CRUD de tabla `citas` |
| `backend/app/config.py` | settings: `calendar_id`, email/SMTP, flag SMS |
| `backend/requirements.txt` | `google-api-python-client` |
| `.env.example` | nuevas variables (sin secretos) |

## 7. Riesgos y decisiones abiertas

- **D1 · Destinatario del aviso** *(la única decisión de producto pendiente)*: email al dueño
  (fijo, sólido) / SMS al cliente (usa el `from` que ya tenemos, natural para quien llama por
  teléfono) / email al cliente (exige capturar email por voz, frágil). Por defecto: **email al
  dueño**, SMS al cliente como extra.
- **R1 · Tool-calling sobre native-audio.** Es preview y se combina con nuestro VAD manual
  (activity_start/end) y barge-in → **validar empíricamente** en Fase 2 antes de fiarse.
- **R2 · Silencio mientras la API responde.** Calendar puede tardar; usar funciones
  `NON_BLOCKING` para que el modelo siga hablando ("dame un segundo y te confirmo").
- **R3 · "Hoy" y zona horaria.** Inyectar fecha/hora actual + `Europe/Madrid`; normalizar el
  lenguaje natural ("el martes por la tarde") a `datetime` concreto.
- **R4 · Identificar la cita a cancelar.** No borrar a ciegas: buscar por teléfono, leer de
  vuelta y confirmar antes de `delete`. Persistir `event_id` lo hace fiable.
- **R5 · Número anónimo.** `from` puede venir oculto/retenido → pedir el teléfono por voz como
  fallback.
- **R6 · Disponibilidad.** v1 reserva sin comprobar colisiones; el doble-booking se aborda
  después (Fase 5+).
- **R7 · Coste OAuth (Fase 5).** Scope de Calendar es "sensible" → verificación de la app de
  Google para producción (en modo prueba van hasta 100 usuarios). Guardar refresh tokens de
  forma segura.

## 8. Lo que se REUTILIZA tal cual

- Relay Telnyx/Live, VAD, barge-in, `_AcumuladorTurnos`, persistencia (sesiones/turnos/memoria).
- Patrón de extracción estructurada con Flash (`resumir_sesion`) si se opta por el camino B.
- Capa de servicios multi-vertical (cada servicio → su calendario y su aviso).
- `_build_config` (solo se le añade `tools`).
