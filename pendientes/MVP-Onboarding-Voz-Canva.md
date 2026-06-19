# MVP — Onboarding por voz que rellena el Canva 4G (+ primer bloque en Calendar)

> Decisión 2026-06-19. Versión **enfocada ("un solo wow")** del MVP "muestra de fuerza"
> ([[MVP-Demo-Muestra-de-Fuerza]]). Objetivo: enseñar el potencial en UNA escena de punta
> a punta. Vertical sobre el core de AppVoz (voz Gemini Live + persistencia + Google Calendar
> ya validado en `agenda.py`). Rama: `agenda4G`.

## El "wow" en una frase
**"Háblame de ti" → tu vida en un Canva → tu primer bloque en el calendario.**

## Las tres bazas que demuestra
1. **Voz natural** en tiempo real (lo más caro, ya resuelto).
2. **Diferencial:** planificar desde el **propósito/roles**, no voz→calendario (commodity).
3. **Artefacto tangible:** algo aparece **de verdad** en su Google Calendar.

## Alcance
**Dentro:**
- **Gancho de apertura** (1 pregunta de la Parte 1): la existencial — «¿qué harías diferente
  hoy si supieras que mañana es el día de tu muerte?».
- **Núcleo = Parte 2 (Brújula / Kairós — el Canva):** Visión → Misión → Valores → Pilares → Roles.
- **Cierre = trocito de Parte 3 (Cronos):** agendar **UN** primer bloque real en Google Calendar.

**Fuera / mock (no entra en el MVP):**
- Parte 1 completa: diagnóstico, test de autodiagnóstico, **TDAT**, **auditoría del tiempo**
  (esta además necesita una semana real → flujo aparte de varios días).
- **Espejo de equilibrio** (Fase 3): fuera o mockeado.
- Ritual semanal completo, revisión trimestral, objetivos T.A.R.G.E.T. detallados.

## UX — flujo híbrido (la voz conduce, el menú-Canva refleja)
- **Una sola conversación guiada por voz** — NO páginas independientes desconectadas, NI
  monólogo de 30 min sin estructura visible.
- **Menú / stepper a la izquierda** con las secciones del Canva:
  **Visión · Misión · Valores · Pilares · Roles · Primer bloque**.
- Cada sección **se ilumina y se completa** según habla el usuario → **confirmación visual**
  del Canva (no fiarse de la memoria) + wow en sí mismo.
- **Checkpoints:** se confirma cada sección al cerrarse; se puede **pausar/retomar** y
  **saltar a una sección** para revisar/editar.
- Arranca por la **Visión** (núcleo emocional), justo tras el gancho existencial.

## Qué se captura por sección (checklist DETERMINISTA)
La compuerta "sección completa" la decide el **código** (todos los campos obligatorios no
vacíos), **no** el criterio del LLM. Las preguntas literales salen de [[Entrevista-4G-Preguntas-Literales]].
- **Visión:** lo que quieres ser, hacer y tener (en ese orden).
- **Misión:** acciones para lograr la visión, ligadas a tus dones.
- **Valores:** máx. 5, cada uno con breve explicación.
- **Pilares:** los 4 fijos (espiritual, mental-emocional, físico, social) — *(opcional: score 1-10)*.
- **Roles:** máx. 8, cada uno asignado a un pilar.
- **Primer bloque:** rol/objetivo + día y hora → evento en Calendar (etiquetado con `rol_id`).

## Técnico
- **Escritura a Calendar DETERMINISTA:** la charla produce el dato estructurado y el **backend**
  lo agenda (no se depende del tool-calling nativo de Gemini → **esquiva el riesgo R1**).
  Reutiliza `agenda.py` (ya **validado**: crear/buscar/borrar contra Calendar real).
- **Reutiliza:** relay de voz (`live_relay.py`), persistencia (`persistence.py`).
- **Auth Calendar:** SA + calendario compartido para la demo (monousuario); **OAuth por usuario**
  = más adelante (Fase 5).
- **Modelo de datos mínimo:** `pep` (vision, mision, valores[]), `pilares`, `roles`,
  `bloques`. (Subconjunto del modelo 4G completo; objetivos T.A.R.G.E.T. = opcional en MVP.)

## Decisiones (2026-06-19)
- **RAG fuera del MVP:** la entrevistadora conduce desde su persona/guion (preguntas
  literales), captura determinista; el RAG del libro (`subject_id="libro-4g"`) es mejora
  posterior. El servicio ya lleva ese `subject_id` para tenerlo preparado.
- **BD:** una sola Postgres + pgvector **compartidas**, aislamiento **lógico por `subject_id`**
  (no BD física por servicio). Separación física / **Row-Level Security** = mejora cuando se
  productice el multi-tenant.
- **Prompt:** se itera de continuo y es editable por servicio (`cfg.system_instruction`);
  probablemente troceado por sección. El éxito NO cuelga del prompt (captura determinista).
- **Servicio "4g" creado** (id=9): persona entrevistadora v1, voz Aoede, `subject_id="libro-4g"`.

## Próximos pasos
1. Derivar el **esquema de campos exacto por sección** (a partir de la entrevista literal).
2. **Frontend:** pantalla Canva + stepper que se rellena en vivo.
3. **Persona/guion** del entrevistador (system prompt) por sección + **extracción estructurada
   determinista** de cada respuesta.
4. **Cierre:** agendar el primer bloque con `agenda.py`.

## Mejoras de UX pendientes (anotado 2026-06-19 — NO ejecutado)
- **Botón "⚙ Configuración" en `/4g`** → deep-link a **`/call?svc=4g`** que auto-abra el editor
  del servicio "4g". Permite tunear modelo / voz / persona-prompt / VAD del onboarding **sin salir**
  de la pantalla del Canva. Implementación: leer el parámetro `svc` en el `app.js` del panel
  (abrir ese servicio al cargar) + añadir el botón en la cabecera de `/4g`. (Alternativa
  descartada: incrustar los ajustes dentro de `/4g` — duplica el panel.)
- **Fix menor del stepper:** al cargar, `/4g` marca una sección como completa por la **existencia
  de la clave** en el Canva (una visión vacía sale con ✓), no por `seccion_completa` real. Usar la
  lógica de completitud real al pintar el stepper inicial.

Fuentes: [[MVP-Demo-Muestra-de-Fuerza]], [[Entrevista-4G-Preguntas-Literales]],
repo `c:\AppVoz` (`agenda.py`, `live_relay.py`, `persistence.py`).
