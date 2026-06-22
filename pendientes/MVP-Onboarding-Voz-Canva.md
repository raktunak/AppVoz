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

## Principios de diseño del onboarding (2026-06-19)
- **Reproducir el método FIELMENTE** (mismo orden y criterios del libro); quitar solo la fricción
  **MECÁNICA** (folio en blanco, escribir a mano, recordar, disciplina), **NO la reflexiva**. Los
  20-40 min de reflexión (montar el Canva/Kairós) son **la sustancia**: se hacen *fluir*, no se comprimen.
- **Paciencia con el silencio:** en secciones reflexivas (sobre todo Visión) tolerar e **invitar**
  pausas largas (aflojar el fin-de-turno), sin rellenar el silencio; el agente *pregunta bien y espera bien*.
- **Multimodal — Canva editable:** cada apartado se puede **hablar o escribir/retocar** → conserva la
  afordancia del papel para quien reflexiona escribiendo (la voz quita el folio en blanco, no la escritura).
- **Ritmo asíncrono:** pausar, pensarlo offline y **retomar** (resume ya soportado); ofrecer saltar una
  pregunta difícil y volver.
- **Avisos para insistir en completarlo (IDEA futura):** recordatorios (vía Google Calendar /
  notificación) para retomar el onboarding si quedó a medias — encaja con el método ("reserva día y
  hora"); nudge suave, no acoso. Recordar al USUARIO necesita el camino OAuth/notificación (futuro).

## Rediseño a SESIÓN-POR-SECCIÓN (decidido 2026-06-19 — **IMPLEMENTADO 2026-06-20**)

> **Estado (2026-06-20):** implementado en `onboarding_4g.py` (backend) + `static/4g/` (frontend).
> Cada sección es una **sesión Gemini independiente** que el usuario abre/cierra con su botón
> «🎙 Hablar» (auto-cierra la anterior). UN solo WebSocket + un solo micro; por debajo se cicla
> la sesión. El **control loop** del WS es el único que lee del socket y despacha el audio (VAD
> por-frame, `_Vad`) a la sesión activa; cada sección corre en su tarea (`_run_section`).
> Continuidad por inyección del **resumen del Canva** en el prompt de cada sección (no ventana
> gigante). Guion **literal** por sección, con modo **revisión** (corregir/ampliar) al reabrir una
> ya completa. Sin micro-pausas: la transición coincide con la acción del usuario. Pendiente:
> prueba en vivo + ajuste del guion si native-audio reformula; vía 100% fiel (lectura
> determinista) como escalada. Protocolo WS nuevo documentado en el docstring de `onboarding_4g.py`.

**Motivo (2 fallos concretos en pruebas):** (1) la persona monolítica (un prompt con los 6
pasos) hizo que native-audio **recitara toda la Presentación de un tirón** (se presentó, pidió
nombre, dio enhorabuena, explicó las 5 secciones y preguntó el tiempo en UN turno) en vez de
pedir solo el nombre y esperar; (2) el prompt gigante **gasta ventana**.

**Decisión:** pasar de **una** sesión Live continua a **una sesión Gemini por sección**, cosida
por el backend detrás de **un único WebSocket con el navegador** (el audio del navegador NO se
corta; solo cicla la sesión Gemini por debajo). *Reemplaza, para el onboarding, la decisión
previa de "sesión única continua".*
- **Prompt pequeño y enfocado por sección** ("estás en mitad de una conversación, NO saludes,
  pide SOLO X, una pregunta, y espera la respuesta; nunca encadenes preguntas") → comportamiento
  fiable + ventana mínima. El modelo no puede recitar lo que no conoce.
- **Transiciones por el gating determinista:** sección completa (`seccion_completa`) → cerrar
  esa sesión y abrir la de la siguiente.
- **Memoria al cambiar de sección (ACOTADA):** inyectar en el prompt pequeño (a) el **resumen del
  Canva** (memoria larga, `resumen_canva`) + (b) las **últimas 2-4 frases** del transcript
  (memoria corta) → continuidad sin re-saludar, sin reventar la ventana.
- **Transición visual en el centro:** al cerrar una sección, marcarla **completada (verde + ✓)**,
  resaltar/expandir la siguiente y mostrar un breve *"preparando la siguiente parte…"* que
  **enmascara la micro-pausa (~1-2 s)** de reconexión y da sensación de avance.
- **No bloquea RAG:** el retrieval se inyecta por turno dentro de la sesión de cada sección.
- **Trade-offs:** micro-pausa por sección (mitigada por la transición visual); cuidar el "no
  saludar de nuevo".

## Granularidad FINA: inyección FRASE A FRASE (pregunta a pregunta) — anotado 2026-06-19

Extensión del rediseño "por sección" a **por pregunta/apartado**. **Motivo:** las preguntas son
las del **MÉTODO** (literales, del libro); si Faro las **reformula** puede acabar preguntando *otra
cosa distinta* → rompe la fidelidad. **Faro NO debe cambiar las preguntas.**
- El backend inyecta, una a una, la **pregunta EXACTA** que toca (las que ya están en `canva4g`
  por apartado / en [[Entrevista-4G-Preguntas-Literales]]) y ordena: *"haz ESTA pregunta
  literalmente, sin reformular ni inventar otra; solo gestiona la respuesta"*.
- Avanza a la siguiente pregunta cuando el apartado se **captura y confirma** (gating ya existente,
  ahora a nivel **apartado**, no solo sección).
- Encaja con que la **pantalla ya muestra la pregunta literal** (hecho) → lo que se ve y lo que se
  oye **coinciden**.
- **Reto honesto:** native-audio **genera** habla, tiende a reformular aunque le des el literal; si
  no lo respeta, la vía **100% fiel** es **sacar la pregunta del LLM** (mostrarla/leerla con una voz
  determinista y que el modelo solo recoja la respuesta) → cambio mayor a valorar.
- Tensión a resolver: **fidelidad literal** vs. **naturalidad/flexibilidad** (que Faro se adapte si
  el usuario se desvía). Probable equilibrio: pregunta literal fija + libertad solo en los apoyos
  ("tómate tu tiempo", reformular la *respuesta*, no la pregunta).

## Mejoras de UX pendientes (anotado 2026-06-19 — NO ejecutado)
- **Botón "⚙ Configuración" en `/4g`** → deep-link a **`/call?svc=4g`** que auto-abra el editor
  del servicio "4g". Permite tunear modelo / voz / persona-prompt / VAD del onboarding **sin salir**
  de la pantalla del Canva. Implementación: leer el parámetro `svc` en el `app.js` del panel
  (abrir ese servicio al cargar) + añadir el botón en la cabecera de `/4g`. (Alternativa
  descartada: incrustar los ajustes dentro de `/4g` — duplica el panel.)
- **Fix menor del stepper:** al cargar, `/4g` marca una sección como completa por la **existencia
  de la clave** en el Canva (una visión vacía sale con ✓), no por `seccion_completa` real. Usar la
  lógica de completitud real al pintar el stepper inicial.

## Decisión de arquitectura de DATOS (2026-06-19) — qué va a RAG y qué no

Cierra un debate recurrente. **Tres capas de datos, cada una en su sitio:**

1. **Conocimiento del método → RAG (semántica).** Las 3 colecciones de
   [[Colecciones-Semanticas-4G]] (`metodo-4g`, `formacion-4g`, `qa-4g`): texto grande,
   canónico y compartido. Es lo único que justifica vectores. Aporta valor **después** del
   MVP, en la fase de **formación/coaching** (enseñar y resolver dudas anclado al libro), no
   en la captura del onboarding.
2. **Estado + perfil del usuario → ESTRUCTURADO (relacional), leído e inyectado. NO a RAG.**
   - **El Canva** (`canva_4g`: PEP, pilares, roles, bloques) **no se vectoriza**: es
     estructurado, quieres el **estado ACTUAL exacto**, es mutable y de volumen mínimo (cabe
     entero en el prompt). Vectorizarlo introduciría **contradicción/staleness** (versión vieja
     y nueva ambas recuperables) y obligaría a **re-embeber en cada corrección**.
   - **El perfil del usuario** (tono, forma de pensar, **temperamento**) tampoco va a RAG,
     **por las mismas razones**. Es además **parte del método**: el libro pide diagnosticar el
     perfil temperamental (Guerrero/Planificador/Director/Zen → Ambivertido) para **adaptar
     coaching y recordatorios**. Se guarda como **campo estructurado** (perfil) + **texto corto
     destilado** (estilo/registro/qué le motiva) en la memoria del usuario, y se **inyecta** en
     el system prompt.
   - **Cómo se *aprende* el perfil:** extender [resumir_sesion](../backend/app/persistence.py)
     para que, además de `{resumen, temas, dudas}`, destile una **dimensión de
     estilo/temperamento** desde los `turnos` crudos (que **ya** se guardan, relacionales). El
     log crudo es la materia prima; **no necesita vectores**.
   - Esto **resuelve el hueco "la memoria no entra al prompt"** sin construir un pipeline de
     vectores: basta **leer el estado estructurado e inyectarlo**.
3. **Narrativa larga del usuario → vectores, pero MÁS ADELANTE.** Solo si el agente debe
   **recordar/citar momentos concretos** de un historial demasiado grande para inyectar entero
   ("la última vez dijiste…") — y aun así con **episodios curados + fecha + supersedencia**, no
   turnos crudos. Fuera del alcance actual.

**Botón "hablar" por sección = forma UI de la sesión-por-sección.** Pulsar "hablar" en un
apartado abre una sesión Gemini **acotada a esa sección** con su **valor actual inyectado**
(*"ya tienes «…», ¿quieres corregirlo o ampliarlo?"*); la extracción determinista + el gating
re-evalúan la completitud. Unifica **onboarding y edición/ampliación** en el mismo mecanismo.

**El prompt por sección se COMPONE de 3 capas** (no se "genera"): (a) **esqueleto estático**
(persona + regla: *"no saludes, haz ESTA pregunta literalmente sin reformular, una sola, y
espera"*); (b) **la(s) pregunta(s) literal(es)** ya escritas (`canva4g` / [[Entrevista-4G-Preguntas-Literales]]);
(c) **estado dinámico**: valor ya capturado en la sección + resumen del Canva + últimas 2-4 frases.

Fuentes: [[MVP-Demo-Muestra-de-Fuerza]], [[Entrevista-4G-Preguntas-Literales]],
[[Colecciones-Semanticas-4G]],
repo `c:\AppVoz` (`agenda.py`, `live_relay.py`, `persistence.py`).
