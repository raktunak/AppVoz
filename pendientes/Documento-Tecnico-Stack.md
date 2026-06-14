---
titulo: "Motor de Tutor por Voz — stack, fortalezas y reutilización"
tags: [proyecto, voz, rag, ia, gcp, arquitectura]
fecha: 2026-06-14
fase: "MVP próximo a lanzar"
origen: motor_tutor_voz_reutilizacion.docx
---

# Motor de Tutor por Voz

**Stack propuesto, fortalezas y reutilización · IA conversacional + RAG sobre Google Cloud.**
Documento técnico para validar la reutilización del esqueleto en otros verticales voz+RAG. Fase: MVP próximo a lanzar (junio 2026).

> Versión markdown del documento original [[motor_tutor_voz_reutilizacion.docx]] (en esta misma carpeta).

## 1. La idea en una frase
Un **tutor por voz en tiempo real** que enseña desde el material que aporta el dueño del producto, no desde conocimiento genérico de internet. El alumno habla, el sistema recupera el fragmento correcto del temario (**RAG**), genera la respuesta con un **LLM** y la devuelve **hablada** — todo con latencia de conversación natural.

Esto lo convierte en un **motor reutilizable**: el conocimiento es un dato de entrada (un corpus indexado por materia), no algo cableado en el código. Cambiar el corpus y la persona del tutor basta para servir otra materia, otro público u otro vertical **sin tocar la arquitectura**.

**Tesis del documento:** el producto actual (un tutor) es en realidad un **esqueleto genérico voz+RAG con memoria**. Si las decisiones críticas se toman bien una vez, el mismo motor sirve para N verticales cambiando solo datos y configuración.

Dos cualificadores marcan todo el diseño: la **fase** (MVP próximo a lanzar → hay que blindar la capa de datos antes de meter usuarios) y la **fuente de conocimiento** (la aporta el usuario → el RAG es el núcleo del producto, no un añadido).

## 2. El stack propuesto
Seis decisiones, cada una con pros/contras explícitos. Resumen de qué se eligió y por qué:

| Capa | Elección | Razón principal |
|---|---|---|
| **LLM** | Gemini Flash (Vertex AI) primario; Pro bajo reglas; OpenAI fallback vía LiteLLM | Mejor TTFT de su clase (~200–400 ms), lo que manda en voz; coste por turno casi nulo; misma red/IAM/factura |
| **RAG / Vector store** | pgvector sobre Postgres (sustituye a ChromaDB) | Consolida un sistema entero; aislamiento por materia con `WHERE subject_id`; HNSW <50 ms co-localizado; backups/HA gratis |
| **Infraestructura** | Cloud SQL (Postgres+pgvector) + Memorystore (Redis) | La VM única es punto único de fallo sin failover; **es la decisión crítica antes de lanzar** |
| **Pipeline de voz** | Cascada STT → LLM → TTS orquestada con **Pipecat** sobre FastAPI | Control determinista del turno: retrieval antes de generar, respuesta forzada desde el material; 3–6× más barato que speech-to-speech nativo |
| **Memoria del alumno** | Postgres (mismo Cloud SQL) con resúmenes asíncronos post-sesión | Relacional puro, consistente con el resto; nada exótico necesario |
| **Stack Python** | FastAPI + Pipecat en el mismo proceso; SQLAlchemy async + asyncpg + pgvector | WebSockets nativos, asyncio real, ecosistema documentado |

**Lo que reordena prioridades:** en voz, el LLM es la parte barata. En una sesión de 15 min, STT+TTS dominan el coste (~$0,30–0,50/sesión en cascada con Google frente a ~$0,05 del LLM con Flash). Las APIs speech-to-speech nativas multiplican eso ×3–6. Por eso la cascada no es solo más controlable: es mucho más barata.

### 2.1 Cómo fluye un turno de conversación
1. **Mic** del navegador (AEC, Opus/PCM 16 kHz) → WebSocket al backend.
2. **STT streaming** (Google Speech v2, resultados parciales; rota el stream cada ~4 min de forma transparente).
3. **Detección de fin de turno:** endpointing del STT + umbral de silencio afinado (~500–700 ms) — el mayor sumando de latencia.
4. **Retrieval pgvector** sobre el transcript (lanzado especulativamente sobre el parcial estable).
5. **LLM streaming → TTS incremental:** se corta el stream del LLM por frases y se alimenta al TTS streaming.
6. **Audio de vuelta** por el mismo WS → reproducción con buffer de jitter pequeño. **Barge-in:** si el usuario habla, se cancela LLM+TTS y se trunca el historial a lo realmente reproducido.

**Presupuesto realista voz-a-voz: ~900–1300 ms.** El cuello de botella no es el LLM ni el retrieval (<50 ms co-localizado), sino la espera de silencio del endpointing.

### 2.2 Decisión de TTS (verificada junio 2026)
Sobre un ranking de 30 modelos TTS, la decisión es **Google STT v2 → Gemini Flash → Gemini 3.5 Flash TTS**, todo en GCP, con **Chirp 3 HD** como fallback configurable.

| Componente | Coste | Nota |
|---|---|---|
| STT Google Speech v2 | $0.016/min | Mic abierto todo el minuto |
| LLM Gemini Flash | ~$0.004/min | ~2 turnos/min con contexto RAG |
| TTS Gemini 3.5 Flash | ~$0.005/min | El más barato de GCP, calidad tier-2 mundial |
| **TOTAL** | **~$0.025/min** | Sesión de 15 min ≈ **$0.37** |

**Riesgo aceptado y mitigado:** Gemini 3.5 Flash TTS es más nuevo en streaming productivo. La decisión es reversible — el TTS vive detrás de una interfaz en Pipecat; si en Fase 2 el TTFA p99 > 500 ms o hay cortes audibles, se cambia a Chirp 3 HD ($0.032/min) por configuración.

## 3. La fuerza que nos da este stack
Propiedades del esqueleto que importan para decidir si reutilizarlo (cada una es una palanca concreta):

| Fortaleza | Qué significa en la práctica |
|---|---|
| Conocimiento como dato, no como código | El corpus se ingiere e indexa por materia (`subject_id`). Un vertical nuevo es un corpus nuevo + una persona de tutor nueva. La arquitectura no cambia. |
| Aislamiento limpio por materia/tenant | El filtro `WHERE subject_id` sobre un índice es a prueba de fugas entre materias. Misma primitiva que necesitas para multi-tenant/multi-vertical. |
| Todo en una nube, una factura, un IAM | LLM, STT, TTS, embeddings, datos y memoria viven en GCP. Sin saltos de red entre proveedores, latencia y coste predecibles. |
| Piezas intercambiables tras interfaces | LLM, STT y TTS detrás de Pipecat/LiteLLM. Cambiar de modelo/proveedor es configuración, no reescritura. |
| Coste por sesión conocido y bajo | ~$0.025/min en cascada (~$0.37 / sesión de 15 min). Modelo de costes lineal y auditable con trazas por etapa. |
| Determinismo pedagógico | La cascada inyecta retrieval en cada turno: el tutor responde DESDE el material, con logging completo. |
| Memoria de usuario genérica | El esquema (perfil, conceptos, mastery, sesiones) es de "usuario que progresa en un dominio". Sirve para onboarding, coaching, soporte, etc. |
| Observabilidad desde el día uno | structlog + OpenTelemetry → Cloud Trace mide latencia por etapa (TTFA, cortes, errores). |

### 3.1 Qué es crítico y qué es cambiable luego
Las decisiones caras se toman una vez; el resto se ajusta por vertical sin coste.

| Crítico (caro de cambiar después) | Cambiable sin coste (va detrás de interfaces) |
|---|---|
| Migración de la capa de datos (con usuarios reales, 10× peor) | Qué LLM concreto; proveedor de STT/TTS |
| Diseño de reconexión/resume del WebSocket | Política de enrutado de modelos; prompts |
| Cascada vs speech-to-speech (pivotar = reescribir la voz) | Algoritmo de mastery; EOT semántico |
| Par embeddings + esquema de chunking (barato hoy, caro con volumen) | WebRTC; migración futura a Vertex AI Search / AlloyDB |

## 4. Reutilización para otros verticales voz+RAG
Para otros tutores/verticales con el mismo motor voz+RAG, la respuesta corta es **sí**, y casi todo el trabajo es de **datos y configuración**, no de arquitectura.

### 4.1 Qué cambia y qué se reutiliza al añadir un vertical
| Componente | ¿Se reutiliza? | Qué hay que tocar por vertical |
|---|---|---|
| Pipeline de voz (Pipecat, WS, barge-in) | Reutilizable tal cual | Nada estructural; quizá afinar umbral de silencio por público (los niños pausan más) |
| Motor RAG (chunking, embeddings, retriever) | Reutilizable tal cual | Ingerir el corpus nuevo bajo un `subject_id` nuevo |
| LLM + enrutado | Reutilizable tal cual | Ajustar prompts / persona del tutor |
| Memoria de usuario | Reutilizable tal cual | Definir los "conceptos" del nuevo dominio (se extraen del corpus en la ingesta) |
| Infra (Cloud SQL, Memorystore, Cloud Run) | Compartida | Añadir DB o `subject_id`; dimensionar instancia si el volumen sube |
| Frontend | Reutilizable | Branding y, si aplica, flujos específicos del vertical |

**La unidad de reutilización:** añadir un vertical ≈ un corpus indexado + una persona de tutor + (opcional) ajustes de UI. El código del motor —voz, RAG, memoria, infra— se comparte. Esto convierte "un producto" en "una plataforma".

### 4.2 Condiciones para que la reutilización se sostenga
- **Multi-tenancy explícito desde el inicio:** nunca una query de retrieval sin filtro de materia/tenant. El aislamiento es una invariante, no una opción.
- **Embeddings y chunking fijados antes de escalar:** cambiarlos obliga a reingestar todo. La decisión reversible-hoy / cara-mañana más importante.
- **Todo lo específico de vertical en datos/config, no en código:** prompts, personas, conceptos y umbrales son parámetros, no ramas de código.
- **Calidad de retrieval medida por vertical:** 20–30 preguntas doradas por materia antes de tocar la voz. Si el retrieval falla, la voz solo hace que falle más rápido.
- **Capa de datos blindada primero:** la integridad del dato precede al onboarding.

### 4.3 Hasta dónde llega el esqueleto (límites honestos)
| Disparador | Evolución natural |
|---|---|
| Decenas de millones de chunks o >1k QPS | Reevaluar pgvector → Vertex AI Search / AlloyDB con ScaNN |
| Público en redes móviles malas | WebRTC (LiveKit/Daily) en lugar de WebSocket para jitter/pérdida |
| Vertical que NO enseña desde un corpus fijo (ej. requiere búsqueda web en vivo) | Rompe la premisa "enseña desde tu material"; cascada+RAG deja de ser el encaje natural |
| Latencia speech-to-speech extrema sin control pedagógico | Las APIs nativas (Gemini Live / OpenAI Realtime) ganan, a costa de determinismo y coste |

## 5. Veredicto de reutilización
**El esqueleto SÍ se reutiliza** para otros tutores/verticales voz+RAG. El motor (voz, RAG, memoria, infra) es genérico; lo específico de cada vertical es **corpus + persona + config**. Las decisiones caras (capa de datos, cascada, embeddings/chunking, reconexión WS) se toman una sola vez y se heredan.

**Condición previa innegociable:** cerrar la capa de datos (migrar la VM única a Cloud SQL + Memorystore, o como mínimo la consolidación lógica gratis: todo en un Postgres con pgvector, retirar ChromaDB y el pooler). Reutilizar un esqueleto cuyo cimiento es un punto único de fallo es multiplicar ese riesgo por cada vertical.

### Próximos pasos sugeridos para validar
1. Elegir un **segundo vertical candidato** y describir su corpus y su público (eso fija umbrales y volumen).
2. Confirmar que su caso encaja en "enseña desde un corpus fijo" (si necesita web en vivo, replantear).
3. Estimar volumen de chunks y QPS esperado para confirmar que sigue dentro del rango de pgvector.
4. **Cerrar la capa de datos del primer producto antes de duplicar nada.**
