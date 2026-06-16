---
titulo: "Plan — Persistencia de sesiones + memoria que aprende del usuario"
tags: [proyecto, plan, persistencia, memoria, rag, postgres, voz]
fecha: 2026-06-16
estado: Fase 1 aprobada (en pruebas). D2–D7 se implementan con las recomendaciones por defecto y se REVISAN tras probar esta primera implementación. Fases 2A/2B aplazadas.
---

# Plan — Persistencia de sesiones + memoria del usuario

Plan derivado de un análisis (workflow multi-agente, 2026-06-16) sobre cómo persistir
conversaciones y construir una "memoria que aprende del usuario" en AppVoz. Ver visión
en [[Arquitectura-Core-vs-Vertical]] y [[MVP-Plan]] (esto aterriza las Listas 2 y 3:
memoria entre sesiones, progreso/mastery, quizzes).

> **Decisión tomada (2026-06-16):** vamos con la **Fase 1 (solo persistir)**. Estamos en
> pruebas, así que NADA de meter memoria en el prompt todavía. Redis **aplazado** (no se
> usa hoy; sólo aparece en docs como infra futura del core).

---

## 1. Estado actual confirmado (mapa del código)

Hechos verificados sobre los que se construye el plan:

- **Tablas `conversaciones` y `mensajes` existen pero NADIE escribe en ellas.** Se crean en
  el `startup` de [main.py:23-33](../backend/app/main.py#L23-L33) (DDL idempotente, no en el
  init SQL). Cero `INSERT` en todo el código. Son esqueletos vacíos.
- **`/voice/ws` procesa UN turno y cierra el WebSocket** ([voice.py:181](../backend/app/voice.py#L181)
  hace un único `receive()`, luego `close()` en [223](../backend/app/voice.py#L223)). **No hay
  bucle de turnos.** ⚠️ Esto invalida "sesión = conexión WS": hoy sería "sesión = turno".
- **Los datos ricos ya se calculan en runtime y se tiran:** transcript, answer, chunks+scores,
  y 7 métricas (`stt_ms`, `retrieval_ms`, `llm_ttft_ms`, `llm_total_ms`, `tts_first_ms`,
  `ttfa_ms`, `total_ms`). Se envían al cliente, no se guardan.
- **`retrieve()` devuelve `{content, score}` SIN id** ([rag.py:22](../backend/app/rag.py#L22)).
  El `metadata` JSONB de `chunks` está inerte.
- **Vía 2 (Gemini Live, `live_relay.py`)** captura `input/output_transcription` pero **no tiene
  `subject_id`, ni `user_id`, ni RAG, ni métricas**. Persistiría turnos "pobres".
- **Capa de datos:** SQLAlchemy 2.0 async + asyncpg, SQL crudo vía `text()`, acceso por
  `engine.connect()`/`engine.begin()` ([db.py](../backend/app/db.py)). **Sin framework de
  migraciones** (Alembic); el DDL corre en cada arranque (idempotente). `SessionLocal` es
  código muerto. No hay tests ni linter.

---

## 2. Fase 1 — Persistir historial + métricas (APROBADA)

**Objetivo:** capturar lo que el pipeline ya produce, sin tocar embeddings/chunking/`retrieve()`
ni el invariante `subject_id`, y **sin** que la memoria entre al prompt. Da ~80% del valor con
solo `INSERT`s y riesgo casi nulo. La `memoria_usuario` es de solo-lectura/observabilidad y
semilla para la Fase 2.

### 2.1 Esquema (reemplaza las tablas vacías `conversaciones`/`mensajes`)

DDL idempotente en el `startup` de `main.py` (mismo patrón actual, `CREATE TABLE IF NOT EXISTS`).
Como las tablas viejas están vacías, no hay datos que migrar (riesgo cero); borrar su DDL para
no dejar tablas muertas.

```sql
-- sesiones: una por "sesión lógica" (ver decisión abierta D2)
CREATE TABLE IF NOT EXISTS sesiones (
  id          BIGSERIAL PRIMARY KEY,
  subject_id  TEXT        NOT NULL,                 -- materia / tenant
  user_id     TEXT        NOT NULL DEFAULT 'anonimo', -- id blando hoy; auth mañana
  via         TEXT        NOT NULL,                 -- 'cascada_rag' | 'gemini_live'
  etiqueta    TEXT,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at    TIMESTAMPTZ,
  n_turnos    INT         NOT NULL DEFAULT 0
);

-- turnos: una fila por turno (usuario + bot)
CREATE TABLE IF NOT EXISTS turnos (
  id           BIGSERIAL PRIMARY KEY,
  session_id   BIGINT  NOT NULL REFERENCES sesiones(id) ON DELETE CASCADE,
  idx          INT     NOT NULL,                    -- orden dentro de la sesión
  user_text    TEXT,
  bot_text     TEXT,
  grounded     BOOLEAN,                             -- false si "Eso no está en el material"
  chunks       JSONB   NOT NULL DEFAULT '[]',       -- [{chunk_id, score}] (ver D5)
  stt_ms       INT, retrieval_ms INT, llm_ttft_ms INT, llm_total_ms INT,
  tts_first_ms INT, ttfa_ms      INT, total_ms     INT,
  error        TEXT,                                -- fallo de Gemini/retrieval en el turno
  ts           TIMESTAMPTZ NOT NULL DEFAULT now()
  -- columnas de métricas y chunks quedan NULL/[] para via='gemini_live'
);

-- memoria_usuario: resumen post-sesión, NO vectorizado en Fase 1
CREATE TABLE IF NOT EXISTS memoria_usuario (
  id                BIGSERIAL PRIMARY KEY,
  user_id           TEXT NOT NULL,
  subject_id        TEXT NOT NULL,
  resumen           TEXT,
  temas             JSONB NOT NULL DEFAULT '[]',
  dudas             JSONB NOT NULL DEFAULT '[]',
  n_sesiones        INT  NOT NULL DEFAULT 0,
  ultima_session_id BIGINT REFERENCES sesiones(id),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, subject_id)                      -- clave del UPSERT
);

CREATE INDEX IF NOT EXISTS idx_sesiones_user_subject ON sesiones (user_id, subject_id);
CREATE INDEX IF NOT EXISTS idx_sesiones_subject      ON sesiones (subject_id);
CREATE INDEX IF NOT EXISTS idx_turnos_session        ON turnos (session_id);
CREATE INDEX IF NOT EXISTS idx_turnos_ts             ON turnos (ts);
-- La tabla chunks y sus índices HNSW/B-tree NO se tocan.
```

### 2.2 Camino de escritura — dos relojes

- **Camino de producto = Gemini Live (`/ws/call`).** Acumular `input/output_transcription` en
  memoria durante la llamada y volcar sesión + turnos en el bloque `finally` de `ws_call`
  ([live_relay.py:134-138](../backend/app/live_relay.py#L134-L138)). Hoy sin `subject_id`/chunks/
  métricas (columnas NULL); **esos datos entran cuando se inyecte RAG en Live**, porque el backend
  ejecuta el retrieval (function-calling) y tendrá los chunks+scores a mano.
- **Cascada RAG (`/voice/ws`) — solo banco de pruebas.** Si se quisiera comparar, el punto de
  escritura es justo antes del mensaje `metrics` (~[voice.py:221](../backend/app/voice.py#L221))
  con un helper `_persistir_turno(...)` (1 `INSERT` + `UPDATE n_turnos`). Aquí sí hay chunks+scores+
  métricas, pero la cascada **quedó descartada como producto** — no es prioridad.
- **Asíncrono post-sesión (best-effort).** Al cerrar la sesión (`ended_at`), `asyncio.create_task(
  _resumir_sesion(session_id))`: lee los turnos, pide a Gemini Flash un resumen + temas + dudas,
  y hace `UPSERT` en `memoria_usuario`. Si falla, los turnos persistidos son la fuente de verdad
  y se recomputa luego. NO bloquea la respuesta.

### 2.3 Cambios de código (mínimos)

1. `main.py` startup: reemplazar el DDL de `conversaciones`/`mensajes` por el de §2.1.
2. `rag.py`: añadir `chunks.id` al `SELECT` de `retrieve()` para guardar `chunk_id` (ver D5).
   Cambio de una línea; no toca `WHERE subject_id` ni el orden por distancia coseno.
3. `live_relay.py` (`finally`): volcar sesión + turnos de la llamada Live — **camino principal**.
4. `voice.py` (~221) — opcional, solo si se quiere persistir la cascada (banco de pruebas).
5. `_resumir_sesion()`: tarea async que reusa el cliente Gemini Flash ya instanciado.
6. Front: enviar `session_id` + `user_id` (ver D2/D3) y, si se decide, señal de fin de sesión.

---

## 3. Decisiones abiertas (pendientes de debatir una a una)

Sólo está cerrado el **alcance** (Fase 1). **Decisión (2026-06-16):** D2–D7 NO se debaten ahora;
la primera implementación usa las **recomendaciones como defaults** y se revisan tras las pruebas.

| # | Decisión | Opciones | Recomendación (pendiente de confirmar) |
|---|----------|----------|----------------------------------------|
| D2 | ¿Qué es una "sesión" si `/voice/ws` es un turno por conexión? | (A) refactor WS multi-turno · (B) `session_id` desde el front (UUID localStorage) reenviado · (C) por `(user_id,subject_id)`+ventana de inactividad | **B** a corto plazo, **A** como objetivo a medio plazo |
| D3 | Identidad sin auth | (A) `user_id` blando: recoger sí / inyectar no · (B) solo sesión, sin `user_id` · (C) meter auth ligera ya | **A** (recoger ya, NO personalizar respuestas con id suplantable) |
| D4 | ¿Qué vía persistir? | (1) cascada RAG · (2) Gemini Live · (3) ambas | **CERRADA → Live.** La cascada queda descartada como producto (solo banco de pruebas). Historial por Live ya; chunks/métricas llegan cuando se inyecte RAG en Live (el backend ejecuta el retrieval). |
| D5 | Trazar chunks usados | (A) añadir `id` al `SELECT` y guardar `chunk_id`+score · (B) guardar `content` tal cual | **A** (barato, trazable, no duplica corpus) |
| D6 | Migraciones | (A) Alembic ya · (B) seguir DDL idempotente en startup · (C) híbrido | **C** (startup para Fase 1; Alembic cuando la Fase 2 toque `chunks` con `ALTER`+backfill) |
| D7 | Escritura del turno | (A) síncrono · (B) fire-and-forget · (C) turno síncrono + resumen asíncrono | **C** (ya reflejado en §2.2) |

---

## 4. Fase 2 — Memoria que influye en las respuestas (APLAZADA)

No empezar hasta validar con datos de Fase 1 que la memoria mejora la tutoría **y** hasta tener
identidad estable (no inyectar memoria con `user_id` suplantable). Dos sabores (pueden combinarse):

- **2A — Memoria-como-corpus (doble retrieval).** Post-sesión se destilan "hechos del alumno",
  se vectorizan con el MISMO pipeline congelado y se guardan como chunks en un namespace de
  memoria por `user_id`. En el turno: doble retrieval — material por `subject_id` (fuente de
  verdad) + memoria por `user_id` (solo personaliza, bloque de prompt separado). Requiere
  `ALTER chunks ADD namespace, owner_id` (+ backfill) → **exige Alembic**. Esfuerzo medio.
- **2B — Modelo del aprendiz (mastery + repaso espaciado).** Etiquetar conceptos del propio
  corpus (en `/ingest`, a `chunks.metadata` + tabla `conceptos`), inferir acierto/fallo por turno
  (heurística dura primero, "juez" Flash después), `mastery` por `(learner_id, subject_id, concepto)`
  con SM-2 ligero; el tutor adapta dificultad y prioriza repaso. Esfuerzo medio-alto. Habilita
  quizzes/ejercicios (Lista 3 del MVP).

Ambos respetan el invariante: `retrieve()` mantiene `WHERE subject_id` obligatorio; la memoria
filtra siempre por `user_id`; nunca hay retrieval sin filtro.

---

## 5. Riesgos a tener presentes

- **PII / contexto educativo (posibles menores):** transcripciones + "qué le cuesta a cada alumno"
  es dato personal sensible. **Falta definir política de retención, borrado a petición y base
  legal.** No persistir transcripciones indefinidamente sin política. (Riesgo legal, no técnico.)
- **Contaminar el grounding (Fase 2):** un "hecho" mal destilado puede colarse como verdad si la
  memoria entra al prompt. Por eso en Fase 1 NO entra.
- **Identidad suplantable:** sin auth, `user_id` lo declara el cliente; si esa memoria influyera
  en respuestas o se mostrara, sería fuga entre usuarios. (Motivo de D3 = A.)
- **Cloud Run multi-instancia:** `asyncio.create_task` tras cerrar el WS puede perderse si la
  instancia se recicla; para durabilidad real haría falta cola/job (fuera de alcance Fase 1).
  Y el DDL en startup tiene ventana de carrera (tolerable con `IF NOT EXISTS`).
- **Sin threshold de score en retrieval (gap preexistente):** hoy se devuelven `k` chunks aunque
  el score sea bajo → "grounding falso". Persistir `score` en `turnos.chunks` permite detectarlo;
  corregirlo es trabajo aparte.
- **Sin tests:** introducir persistencia (upserts, resúmenes) sin pruebas es deuda asumida en pruebas.

---

## 6. Aplazado explícitamente

- **Redis:** no aporta a la persistencia (eso es Postgres). Tendría sentido futuro para caché de
  embeddings de queries repetidas, estado de sesión entre instancias o rate-limiting. No ahora.
- **Alembic:** se introduce cuando la Fase 2 toque `chunks` con `ALTER`+backfill (D6 = C).
- **Auth real:** D3 = A por ahora (id blando, no personalizar). Revisar antes de Fase 2.

---

## 7. Ideas / candidatos de corpus RAG (futuro)

Más allá del material del curso (corpus actual) y la memoria del alumno (Fase 2A), otras cosas
que **tendría sentido vectorizar**, siempre **aisladas por `subject_id`** (o `user_id` la del alumno):

- **Glosario de conceptos** del temario (definiciones canónicas) → refuerza el modelo de mastery
  y da respuestas consistentes. Liga con la tabla `conceptos` de la Fase 2B.
- **Errores / malentendidos frecuentes** por materia → el tutor los anticipa y corrige al detectarlos.
- **Banco de Q&A / "preguntas doradas" y ejercicios** → reutilizar respuestas buenas, generar
  quizzes y medir la calidad del retrieval (las "preguntas doradas" ya están en la Lista 2 del MVP).
- **Material multimodal convertido a texto**: transcripciones de vídeo/audio del curso y OCR de
  diagramas/PDF → amplía el corpus sin tocar el pipeline (embeddings/chunking congelados).
- **Memoria del alumno** (hechos/preferencias destilados) → Fase 2A, filtrada por `user_id`.

**NO meter en RAG** (va a tablas relacionales, no a pgvector): transcripciones en crudo, métricas
de latencia/consumo, config/persona y logs de error.

