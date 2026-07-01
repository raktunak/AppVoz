# Plan MVP Comercial — **Faro** (Agenda 4G por voz)

> Estado: vivo / en desarrollo · Creado 2026-06-30
> **Progreso (2026-07-01):** Fase 0 **COMPLETA y desplegada a producción** (Cloud Run rev. 00020, app publicada; RAG con el libro = 309 chunks; login Google + Calendar por usuario). **Probador** construido y validado → se promociona a **Asistente Faro permanente** (§12). Fase 1 a medias (faltan objetivos T.A.R.G.E.T. + Cuadro de prioridades).
> Norte: **NO es una demo para enseñar a Fabián**. Es una **MVP comercial** lista para **probar ya con sus alumnos** (newsletter, asistentes a sus talleres, mentorías IPP). Real product, real users.
> Fuentes: reunión con Fabián 2026-06-30 (`reuniones/fabian/2026-06-30 16-31`), [[Plantilla-Notion-Fabian-Estructura-y-Replica-MVP]], [[Formacion-Guiada-4G-Programa]], [[Libro-Agenda-4G-Sintesis-Completa]], mapa de código (abajo, Anexo A). Mirror Obsidian: `Proyectos/app 4 generación/`.

---

## 0. Qué es Faro y qué valida esta MVP

**Faro (Faro Vision)** = el copiloto por voz que convierte el método de la *Agenda de Cuarta Generación* de Fabián en **acompañamiento diario**. No da más contenido (de eso sobra): da **alguien al lado que asegura que llegues** — guía socrático, recuerda lo importante y celebra cada paso. Tutor personal que *sabe de ti, aprende de ti y te conoce*.

**Qué valida la MVP con alumnos reales:** que la tecnología (voz + RAG del libro + agenda en Calendar + acompañamiento) **lima la resistencia** que hoy hace que la gente abandone el método 4G (la curva de aprendizaje de Notion/Excel, romper la inercia del caos, las temporadas de saturación). Métrica madre: **¿la usan y siguen el método más que con el Notion/Excel actual?** (que "sencillamente no entraban", dixit la reunión).

---

## 1. Posicionamiento y usuario (decidido en la reunión)

- **Para quién SÍ:** personas que **ya están dentro del 4G** — conocen el concepto, han visto el método (alumnos de Fabián, asistentes a su taller de 4h, su lista de newsletter). Analogía de Fabián: *"como una app de contar calorías: para alguien que ya entrena y cambia hábitos"*. La herramienta es el **proceso de continuidad**, no la captación en frío.
- **Para quién NO (v1):** desconocidos sin contexto 4G; perfiles con rechazo a la IA o que prefieren papel/Excel. No los perseguimos en la MVP.
- **El dolor que atacamos:** (a) **romper la inercia** del caos hacia una agenda con bloques/roles/objetivos; (b) **no abandonar en temporadas altas** de trabajo. Antídoto: **pequeñas victorias, rachas, y recordatorios "intrusivos" que el propio usuario pre-autoriza** conociendo sus resistencias.
- **Modelo de negocio destino** (post-validación): membresía/comunidad (3-6-12 meses) con mentoría + comunidad + copiloto IA, estilo IPP. La MVP es la **herramienta de apoyo** dentro de ese conjunto. Coste voz de referencia: **~0,03–0,04 €/min**.

---

## 2. Alcance comercial del MVP (qué entra en v1)

La MVP **recorre el método completo del Notion** y cierra el **bucle diario**. Dos modos que conviven:

**Modo A — Construcción guiada (el "Canva" / PEP).** Por voz, el alumno construye su Plataforma Estratégica Personal siguiendo los pasos del Notion:
1. **Brújula:** Visión (ser/hacer/tener) → Misión → Valores.
2. **Áreas/Pilares (4)** y **Roles (8)** con su descripción.
3. **Objetivos T.A.R.G.E.T.** por rol (anual → mensual).
4. **Cuadro de prioridades (Eisenhower):** clasificar tareas en C1–C4 con su acción (Hazlo ya / Agéndalo / Delégalo / Elimínalo); foco en el **Cuadrante II coronado** (ver [[Plantilla-Notion-Fabian-Estructura-y-Replica-MVP]] §2.3).

**Modo B — Acompañamiento diario (el "Reloj" + hábitos).** Lo que hace que vuelvan:
5. **Planificación → Google Calendar por voz:** "ponme un bloque de 2h mañana a las 9 para el proyecto X" → evento real sincronizado. *Si no está en la agenda, no existe.*
6. **Registro de hábitos** con **rachas y pequeñas victorias** (set up matutino, roca del día, bloques cumplidos).
7. **Check-ins y recordatorios** (pre-autorizados): monitoreo, recordatorio de la roca, balanceo semanal.

**Transversal:**
- **RAG anclado al libro** (`subject_id = libro-4g`): cada bloque coachea con las palabras de Fabián; nunca inventa ("eso no está en el material"). Sostiene la fidelidad del método.
- **"Carpeta de vida" persistida** y recordada entre sesiones (lee tu misión, recuerda tu €/min, retoma tu cronófago).
- **Multiusuario real** (cuentas + aislamiento de datos) — es comercial, no un single-user.

### En v1 (decidido)
- **Llamada proactiva por teléfono (Telnyx):** Faro te llama cuando vas saturado y te agenda por voz sin entrar a la app. Killer feature pedida por Fabián. Reutiliza `telnyx_relay` (Anexo A). → Fase 3.

### Fuera de v1 (vNext, explícito para no colar alcance en silencio)
- El **programa formativo completo de 9 módulos** (la visión Agenda 5G de [[Formacion-Guiada-4G-Programa]]): conciencia/cronófagos/sistema/enfoques + Cronos micro completo. La MVP cubre el **núcleo agenda**, no el curso entero.
- Canal **WhatsApp** — para vNext.
- Comunidad/retos entre usuarios, mentorías, billing automático.

---

## 3. Experiencia de producto (el bucle que retiene)

```
   PRIMER USO (1-2 sesiones)            USO RECURRENTE (diario/semanal)
  ┌───────────────────────┐           ┌──────────────────────────────┐
  │  Construcción guiada   │           │   Acompañamiento (Faro)       │
  │  Brújula → Roles →     │  ──────►  │  • Set up matutino (racha)    │
  │  Objetivos → Cuadro    │           │  • Roca del día ("el sapo")   │
  │  (PEP completa)        │           │  • Planifica por voz → Calendar│
  └───────────────────────┘           │  • Hábitos + pequeñas victorias│
            │                          │  • Balanceo semanal (1h dom)  │
            ▼                          │  • Recordatorios pre-autoriz. │
     Carpeta de vida  ◄────────────────┤  (lee misión, €/min, cronófago)│
     (persistida, RAG)                 └──────────────────────────────┘
```

Reglas de orquestación (de [[Formacion-Guiada-4G-Programa]] §7, ya validadas con el libro):
- **La voz guía; la pantalla fija.** Visual adaptativo por bloque (a Fabián le encantó el gráfico de "semanas de vida"): calculadora €/min, rueda de pilares, parrilla de roles, matriz Eisenhower con C2 resaltado, tarjeta de evento Calendar.
- **Gating de acción:** ante una intención aplazada, **no se cambia de tema hasta fijar día y hora**. "Menos habladores, más hacedores."
- **Nunca elabora la agenda por el alumno** (principio intransferible): orquesta, pregunta y registra; el contenido lo pone él.

---

## 4. Arquitectura técnica (reutilizar al máximo)

**Tesis:** el motor ya existe. La MVP es **extender el motor `/4g` a calidad comercial + cerrar 3 gaps**: (1) conectar RAG, (2) cuentas + Calendar por usuario, (3) el bucle diario (hábitos/recordatorios). Detalle de ficheros/líneas en **Anexo A**.

### 4.1 Lo que se reutiliza tal cual
- **Motor de voz con sesión única + relevo de agente por bloque:** `onboarding_4g.py` (`/ws/4g`), `_inyectar_agente()` — una sola sesión Gemini Live, se cambia el "rol" por bloque **sin reconectar** (la voz no se corta). Arquitectura correcta (commit 4f59b17).
- **Definición de bloques:** `canva4g.SECCIONES` (presentacion, vision, mision, valores, pilares, roles, bloque) — con tipos `fijo`/`lista` y `obligatorios`. **Se amplía** (ver 4.3).
- **Extracción determinista a BD:** `canva4g.transcribir_audio` / `extraer_seccion`; Canva persistido como JSONB (`canva_4g`) vía `persistence`.
- **Config por servicio:** `persistence.resolver_servicio("4g")` → persona/voz + `subject_id` (ya por defecto `libro-4g`).
- **Agendar por voz:** `agenda.crear_evento` (ya funciona en el bloque final → evento real en Calendar).
- **Plomería de audio + UI responsive** de `static/4g/` (stepper + canva + transcripción), ya con diseño móvil.

### 4.2 GAP 1 — Conectar el RAG del libro al motor 4G **(el más importante)**
Hoy `/ws/4g` es **Gemini Live puro, sin retrieval** (Anexo A §4). El RAG está montado pero desconectado. Gemini Live **no tiene tool-use nativo**; el contexto entra por `system_instruction` o `send_client_content`. Plan:
- Añadir a cada entrada de `SECCIONES` un `rag_query` (la consulta del bloque, p.ej. roles → "los 8 roles, parrilla por pilares, T.A.R.G.E.T.").
- En `_inyectar_agente()`: antes de inyectar el rol, llamar `await rag.retrieve("libro-4g", seccion.rag_query, k=2-3)` e **incrustar los fragmentos como "MATERIAL DEL LIBRO"** en el prompt de relevo, con la consigna estricta: *cita el material; si algo no está, dilo*. Así cada bloque coachea con las palabras de Fabián (mitiga el "gurú alucinado").
- **Requiere paso 0:** ingerir el libro (la tabla `chunks` hoy tiene 0 chunks de `libro-4g`). Ver §5.

### 4.3 GAP 2 — Completar el método (bloques que faltan en el motor)
`SECCIONES` cubre Brújula + roles + un primer bloque. Faltan, para igualar el Notion:
- **Objetivos T.A.R.G.E.T. por rol** (sub-flujo dentro de `roles` o sección nueva `objetivos`): checklist Tangible/Realista/Ganancia/Evidencia/Tiempo + afirmativo; anual→mensual.
- **Cuadro de prioridades (Eisenhower):** sección nueva `prioridades` (tipo `lista`): el alumno dicta tareas, el agente devuelve cuadrante + acción; UI = matriz 2×2 con C2 coronado.
- **Reloj / planificación semanal:** sección/modo que baja roles+objetivos+rocas a bloques de Calendar por voz (extiende lo que ya hace `agenda.crear_evento`).

### 4.4 GAP 3 — El bucle diario (retención) y lo comercial
- **Hábitos normalizados:** modelo `Habito` + `RegistroHabito(fecha)` (NO la "columna por hábito" de Notion; ver [[Plantilla-Notion-Fabian-Estructura-y-Replica-MVP]] §4.1). Rachas y % por query. UI de uso diario.
- **Cuentas + Google OAuth:** hoy el `user_id` viaja en el `config` del WS (sin auth real). Comercial ⇒ **login con Google**, que mata dos pájaros: identidad **y** OAuth de **Google Calendar por usuario** (cada alumno conecta SU calendario; hoy el agendado no es multiusuario). Aislamiento de datos por `user_id` en todas las tablas.
- **Recordatorios:** web push / notificaciones **+ llamada proactiva (v1)** reutilizando `telnyx_relay` (la "app que te llama: ¿cómo llevas el día? dímelo en 4 frases y te lo agendo" — idea de Fabián). La llamada también debe agendar en SU Calendar por voz (reutiliza `agenda.crear_evento`).
- **Costes/uso:** contador de minutos/tokens por usuario (ya hay contadores en el panel `/call`) para el modelo de precio.

---

## 5. Paso 0 — Ingesta del libro (corpus RAG)

- **Fuente real:** la transcripción OCR completa del libro: `C:\Obsidian\libros\Transcripciones\La Agenda de Cuarta Generación - Fabián González.md` (**270 KB / 3.276 líneas**). *(Ojo: `Libro-La-Agenda-4G.md` es solo una nota de biblioteca, NO el libro.)*
- **Cómo:** `POST /ingest` con `{subject_id: "libro-4g", content: <texto>}` → trocea (~1000 chars / 150 solape) → embeddings `gemini-embedding-001` 768-dim → `chunks`. Estimado **~320 chunks**. Invariante: **siempre filtrado por `subject_id`**.
- **Verificación:** `curl /health/db` (nº de chunks) y un `rag.retrieve("libro-4g", "matriz de Eisenhower cuadrante II", 3)` debe devolver fragmentos reales del libro.
- **Decisión ya tomada:** ingerir el **libro completo**, no la síntesis (fidelidad de cifras/citas).

---

## 6. Lo que ya existe vs. lo que falta (resumen)

| Pieza | Estado | Acción MVP |
|---|---|---|
| Motor voz sesión-única + relevo por bloque (`/ws/4g`) | ✅ existe | Reutilizar |
| Bloques Brújula+roles (`canva4g.SECCIONES`) | ✅ existe | Ampliar (objetivos, prioridades, reloj) |
| Extracción a BD + Canva JSONB | ✅ existe | Reutilizar / extender esquema |
| Agendar por voz (`agenda.crear_evento`) | ✅ existe (1 bloque) | Generalizar a planificación + multiusuario |
| Infra RAG (`/ingest`, `rag.retrieve`, pgvector HNSW) | ✅ existe | **Conectar al 4G** (GAP 1) |
| Libro ingerido (`libro-4g`) | ❌ 0 chunks | **Paso 0: ingestar** |
| Cuadro de prioridades / objetivos T.A.R.G.E.T. | ❌ no en motor | **Construir** (GAP 2) |
| Hábitos + rachas + bucle diario | ❌ no existe | **Construir** (GAP 3) |
| Cuentas + Google OAuth + Calendar por usuario | ❌ no existe | **Construir** (comercial) |
| Telefonía proactiva (`telnyx_relay`) | ✅ infra, sin RAG | **v1 (Fase 3):** llamada que rescata + agenda por voz |
| Despliegue Cloud Run + UIs responsive | ✅ existe | Reutilizar |

---

## 7. Plan por fases (cada fase = probable con alumnos)

> Filosofía: cada fase deja algo **usable de punta a punta** por un alumno real, no media pantalla a medias.

**Fase 0 — Cimientos comerciales** *(habilitador, sin lo cual nada es "comercial")*
- Ingerir el libro (`libro-4g`) — Paso 0.
- Login con Google + OAuth de Calendar por usuario; aislamiento de datos por `user_id`.
- Despliegue verificado multiusuario en Cloud Run.
- *Hito:* dos alumnos distintos entran con su cuenta, cada uno ve su espacio, y el RAG responde con el libro.

**Fase 1 — Construcción guiada a calidad comercial (la PEP completa)**
- Conectar RAG por bloque (GAP 1).
- Ampliar `SECCIONES`: objetivos T.A.R.G.E.T. + Cuadro de prioridades (GAP 2).
- Pulir UX (visual adaptativo por bloque, gating de acción, "carpeta de vida" recordada).
- *Hito:* un alumno construye su Brújula→Roles→Objetivos→Cuadro por voz y la recupera al volver. **Probable con alumnos.**

**Fase 2 — El Reloj (planificación → Calendar por voz)**
- Planificación semanal: bajar roles+objetivos+rocas a bloques; crear/editar eventos por voz en SU Calendar; recordatorios/alarmas por voz.
- *Hito:* "ponme la roca de mañana 9-11 y avísame 3h antes" → evento real + recordatorio. **Probable con alumnos.**

**Fase 3 — Acompañamiento diario (retención, el corazón de "Faro")**
- Hábitos + rachas + pequeñas victorias; check-ins (set up matutino, roca del día, balanceo dominical); recordatorios pre-autorizados.
- **Llamada proactiva (Telnyx) — en v1:** el usuario pre-autoriza horarios/condiciones; Faro le llama, conversa y agenda por voz en su Calendar sin que entre a la app.
- *Hito:* un alumno mantiene una racha una semana, recibe el recordatorio de su roca y/o una llamada de Faro que le agenda algo. **El uso recurrente que valida el producto.**

**Fase 4 — Pulido comercial + medición**
- Onboarding de alta para nuevos alumnos (alta desde un enlace que Fabián comparte en newsletter/taller); manejo de errores; métricas y costes por usuario.
- *Hito:* Fabián comparte un enlace a su lista y N alumnos se dan de alta y completan su PEP sin asistencia.

---

## 8. Verificación — criterios de "listo para probar con alumnos"

- **Funcional por fase:** abrir la web, login Google, hablar, ver el visual correcto, dato persistido por usuario (`select ... where user_id=...`), evento real en SU Calendar, `docker compose logs` sin errores. (La pila corre con `--reload`; cambios `.py`/estáticos en caliente.)
- **RAG fiel:** ante una pregunta del método, Faro cita el libro; ante algo ajeno, dice "eso no está en el material".
- **Multiusuario:** dos cuentas no ven los datos de la otra; cada una agenda en su propio Calendar.
- **Robustez mínima comercial:** la sesión de voz aguanta una sesión completa sin caerse; reconexión limpia; coste por sesión medido.

---

## 9. Riesgos (de la reunión) y mitigaciones

- **Curva de aprendizaje (lo que mató al Notion/Excel):** *"necesitabas aprender la herramienta antes de usar la herramienta"*. → Mitigar con **voz como interfaz** (cero que aprender) y **un paso a la vez**; el alumno nunca configura, conversa.
- **Abandono en temporadas altas:** → pequeñas victorias, rachas, recordatorios pre-autorizados, "permiso de mover bloques sin culpa", balanceo dominical que re-engancha.
- **"Gurú alucinado" (IA inventa el método):** → **RAG estricto + citas literales**; respetar matices del autor; no convertir publicidad del libro en formación.
- **Que el constructor (nosotros) no domine el método** (la mayor preocupación de Fabián): → **terminar el libro** y validar con él que el flujo respeta la secuencia A→B del método antes de abrir a alumnos. *Acción concreta: cerrar lectura del libro + check con Fabián del guion por bloque.*
- **Rechazo a la IA / preferencia por papel:** fuera del público objetivo v1; no se fuerza.

---

## 10. Métricas de validación (qué medimos con los alumnos)

- **Activación:** % que completa su PEP (Brújula+Roles+Objetivos+Cuadro).
- **Retención:** días de racha de hábitos; nº de planificaciones semanales hechas; sesiones/semana.
- **Acción real:** eventos creados en Calendar por voz (el bucle "si no está en la agenda, no existe").
- **Cualitativo:** ¿sienten el acompañamiento? ¿la usan más que el Notion/Excel que abandonaron?
- **Coste:** €/usuario activo/mes (minutos de voz) → base del precio de membresía.

---

## 11. Decisiones (estado a 2026-06-30)

1. **Auth → ✅ DECIDIDO: Google sign-in.** Resuelve identidad **y** OAuth de Google Calendar de una vez (cada alumno conecta su propio calendario).
2. **✅ DECIDIDO: la llamada proactiva (Telnyx) ENTRA en v1.** Faro puede llamarte al móvil cuando vas saturado ("¿cómo llevas el día? dime en 4 frases y te lo agendo yo") — una llamada que te rescata sin entrar a la app. Es gancho diferencial y se valida desde el día 1. Implica subir la telefonía (`telnyx_relay`) de "v2 opcional" a **alcance v1** (Fase 3).
3. **✅ DECIDIDO: misma personalidad.** Faro reutiliza el servicio `4g` (su persona/system prompt/voz). No se crea un servicio nuevo; si en pruebas el tono "acompañante" pide divergir, se separa entonces.
4. **⏸️ APLAZADA (a valorar más adelante) — Profundidad del método en v1.** ¿v1 se queda en el núcleo agenda (Brújula→Roles→Objetivos→Cuadro→Reloj→Hábitos) o empieza a meter los módulos de conciencia/cronófagos/sistema del libro? Recomendación de partida: cerrar primero el núcleo agenda + bucle diario. *Decisión pendiente.*

---

## 12. Asistente Faro (copiloto permanente) — spec detallada

> Origen: el «🧪 Probador» (tarjeta de charla libre con tool-calling) **se validó y funciona** → se promociona a apartado **PERMANENTE** del producto. Deja de ser "prueba" y pasa a ser **el copiloto de voz de Faro**. Decidido 2026-07-01, nivel **"recomendado"** (con contexto del usuario + memoria).

### 12.1 Qué es
Un asistente por voz **siempre disponible** que:
- **Consulta el método** (RAG del libro `libro-4g`): "¿qué dice Fabián del cuadrante 2?".
- **Gestiona el calendario** por voz: crear / listar / borrar eventos en el Calendar del usuario.
- **Conoce al usuario** (su Canva/PEP + memoria): responde sobre SU vida, no solo el libro — "¿en qué me enfoco esta semana según mis roles?".
- **Recuerda** conversaciones pasadas (persistencia).

Es la materialización de "un copiloto por voz que está contigo cada día" — corazón de **Fase 2** (acción) + **Fase 3** (memoria/acompañamiento).

### 12.2 UX / ubicación
- **Renombrar** «Probador» → **«🎙️ Habla con Faro»**. Fuera el tono de "prueba".
- **Ubicación:** botón **«🎙️ Habla con Faro» SIEMPRE VISIBLE en la cabecera**, disponible desde cualquier pantalla (alinea con "siempre contigo"). Mantiene el patrón actual: misma sesión `/ws/4g`, control `{type:'asistente'}`.
- Botón que **alterna** ▶ Empezar / ⏹ Parar (ya hecho).

### 12.3 Backend — qué cambia (sobre lo ya construido)
Base ya existente (Probador): herramientas `buscar_en_libro`, `crear_evento`, `listar_eventos`, `borrar_evento` + manejo de `tool_call` en `/ws/4g`. Encima:
1. **Renombrar** `_inyectar_probador` → `_inyectar_asistente`; control `{type:'probador'}` → `{type:'asistente'}` (con alias temporal para no romper).
2. **Contexto del usuario en el prompt (que sepa de ti):** al iniciar, inyectar:
   - **Resumen del Canva** del usuario (`canva4g.resumen_canva(shared["canva"])`) — misión, visión, valores, pilares, roles, objetivos ya capturados.
   - **Memoria acumulada** (tabla `memoria_usuario` por `user_id`+`subject_id`: resumen, temas, dudas) si existe.
   → responde anclado a SU vida + el libro.
3. *(Opcional)* herramienta `consultar_mi_canva()` para leer la PEP a demanda (o basta con inyectarla en el prompt, que es pequeña).
4. **Herramientas de ESCRITURA del Canva** (decidido: el asistente puede modificarlo): p.ej. `actualizar_canva(seccion, datos)` / `anadir_rol` / `anadir_objetivo` → modifican `shared["canva"]`, **persisten** (`canva4g.guardar_canva`) y **empujan** `{type:'canva'}` al navegador para verlo en vivo. **Confirmación por voz** antes de sobrescribir/borrar (no pisar datos sin querer).

### 12.4 Persistencia de la conversación (conectar la fontanería ya existente)
Las tablas `sesiones` / `turnos` / `memoria_usuario` **ya existen** (`persistence.py`) pero `/ws/4g` NO escribe en ellas. Conectarlo:
- Al abrir el asistente: fila en `sesiones` (via=`asistente`, user_id, subject_id).
- Por intercambio: fila en `turnos` (user_text, bot_text; latencias opcionales).
- **Guardar TODO el detalle** (decidido): cada intercambio va a `turnos` siempre (no solo un resumen).
- **Resumen a demanda:** `memoria_usuario` se (re)genera con Gemini Flash cuando se necesita (al abrir la siguiente sesión o periódicamente), a partir de los turnos crudos — no obligatoriamente al cerrar.
- **Acumular, no sobrescribir:** el resumen debe FUNDIR la sesión nueva en la memoria previa (hoy `resumir_sesion` la PISA). Diseño y mejoras del bucle → **§12.7**.
- Esto **resuelve el pendiente histórico "la memoria no entra al prompt"**: aquí SÍ entra (§12.3.2) y SÍ se actualiza.

### 12.5 Pasos incrementales
1. **Renombrar** Probador→Asistente (UI + control + `_inyectar_asistente`) + botón permanente en cabecera. *(rápido)*
2. **Contexto del Canva** del usuario en el prompt. *Hito: "¿en qué me enfoco?" usa mis roles.*
3. **Persistir** sesión + turnos del asistente. *Hito: filas en `sesiones`/`turnos`.*
4. **Cerrar el bucle de memoria:** resumen al cerrar → `memoria_usuario` → inyectar en la siguiente sesión. *Hito: en una 2ª sesión, Faro recuerda algo de la 1ª.* **Refinamiento: acumular en vez de sobrescribir + mejoras → §12.7.**

### 12.6 Decisiones (tomadas 2026-07-01)
- **Ubicación → botón «🎙️ Habla con Faro» SIEMPRE VISIBLE en la cabecera** (accesible desde cualquier pantalla).
- **Nombre → «🎙️ Habla con Faro».**
- **Capacidades → consultar + agendar + MODIFICAR el Canva** (añadir/editar roles, objetivos, valores… por voz). Implica herramientas de **escritura** sobre el Canva (§12.3.4) + **confirmación por voz** antes de cambios destructivos.
- **Memoria → guardar TODO el detalle** (cada intercambio en `turnos`) y **resumir a demanda** (no solo al cerrar). Más rico; asumimos coste/almacenamiento.

### 12.7 Bucle de memoria (paso 5) — diseño y mejoras
> **Estado (2026-07-01):** el paso 4 ya persiste turnos y dispara `resumir_sesion` al cerrar, así que el bucle está **parcialmente cerrado** — pero `resumir_sesion` hoy **SOBRESCRIBE** la memoria (cada sesión pisa el resumen anterior; solo incrementa `n_sesiones`). El paso 5 es un **refinamiento de cómo se resume**, no fontanería nueva (~1 función + prompt, sin tabla nueva).

**Dos ejes de decisión:**
- **Eje A — cómo acumular:** (1) *resumen rodante* **[recomendado]** = memoria actual + turnos de la sesión nueva → memoria fusionada (contexto acotado, barato, estable); (2) *re-resumir desde todos los turnos* (máxima fidelidad, pero crece sin límite → capar a últimas N sesiones); (3) *híbrido* (rodante + lista de hechos con dedup).
- **Eje B — cuándo:** al **cerrar** (actual, simple, ya funciona) vs **a demanda** (regenerar al abrir la siguiente sesión / periódicamente; más fresco, pero añade algo de latencia al arranque).

**Mejoras (a incorporar en el paso 5):**
1. **Memoria estructurada, no prosa:** separar *perfil* durable (misión, cronófago, €/min, preferencias) de *estado* volátil (dudas y compromisos abiertos). El perfil casi no cambia; el estado rota.
2. **Rastrear compromisos:** extraer lo que el usuario dijo que HARÍA y llevar `pendiente → hecho` entre sesiones (espíritu 4G "hacedores, no habladores").
3. **Marca temporal:** items de memoria con fecha ("hace 2 semanas dijiste…") para que Faro pueda usar el tiempo (encaja con el gráfico "semanas de vida" que enamoró a Fabián).
4. **No duplicar el Canva:** resumir sobre todo la **charla libre**; lo del onboarding guiado ya vive estructurado en `canva_4g`. Que el prompt de resumen priorice lo conversacional.
5. **Protección ante fallo:** si el resumen de Gemini sale mal (JSON inválido / vacío), **NO pisar** la memoria buena existente (hoy sobrescribe a ciegas → riesgo de perderla).
6. **Memoria visible/editable por el usuario:** que pueda ver "lo que Faro recuerda de ti" y corregirlo (confianza + control), y que esa edición retroalimente la memoria.

**Detalles finos:** capar el crecimiento de `temas`/`dudas` (p.ej. top-10); recordar la FK `memoria_usuario.ultima_session_id → sesiones` (borrar la memoria ANTES que su sesión); el resumen sigue siendo best-effort (nunca rompe el cierre de la sesión).

### 12.8 Reiniciar (reset) — soft-delete y visibilidad de conversaciones
> **Decidido 2026-07-01. PRIORIDAD P0** — se implementa en la PRIMERA tanda, junto al núcleo del paso 5 (§12.7 P0: acumular + protección ante fallo).
> Al pulsar «↺ Reiniciar»: el usuario ve borrón y cuenta nueva, pero **nada se pierde por detrás** y **NO se toca el Calendar/agenda**.

**Requisitos:**
- **NO afectar al Calendar/agenda:** reiniciar deja TODAS las citas intactas (las cree Faro o el usuario).
- **Nosotros vemos las conversaciones ÍNTEGRAS** (lo que dice el usuario y lo que dice Faro), aunque el usuario haya reiniciado.

**Lo que YA está (no hay que construir):**
- Los turnos se guardan enteros: `user_text` + `bot_text` (paso 4). El reset **nunca** borra `sesiones`/`turnos` → sobreviven solos.
- Endpoints de lectura ya existentes: `GET /api/live/sessions?user_id=<email>` (lista) y `GET /api/live/sessions/{id}` (sesión con todos sus turnos). Son genéricos → valen para las conversaciones con `via="4g"`.

**Cambios en `/api/4g/reset` (`backend/app/onboarding_4g.py`):**
1. **Quitar el borrado de Calendar.** *(Hoy busca por `telefono=user_id` en el calendario COMPARTIDO; el asistente crea en el `primary` del usuario SIN ese tag → ya casi no encuentra nada, pero se elimina el bloque para que sea rotundo.)*
2. **Soft-delete del Canva:** en vez de `borrar_canva` (hard-delete), archivar un snapshot en una tabla nueva **`resets`** (`user_id`, `reset_at`, `snapshot` JSONB del Canva/memoria) y luego limpiar la fila viva. Así **sabemos que hubo reinicio** y **conservamos el estado previo**.

**Decisión:** el **Canva SÍ se vacía** de cara al usuario (fresh start del PEP) pero **archivado**; el **Calendar NO se toca**; las **conversaciones se conservan y son visibles** por los endpoints. Es el patrón *soft-delete* ya validado (usuario ve limpio, nosotros retenemos todo y sabemos que hubo reset).

---

## Anexo A — Mapa de código (verificado 2026-06-30)

**Motor 4G:** `backend/app/onboarding_4g.py` — `/ws/4g` (`ws_4g`, l.336); sesión Live única (l.372-386); relevo de rol `_inyectar_agente()` (l.91-148) vía `session.send_client_content(...)` sin reconectar; carga config `_cargar_cfg_4g()` (l.49) desde `persistence.resolver_servicio("4g")` → `subject_id` por defecto `libro-4g`; prompt con fecha + memoria `_preparar_prompt()` (l.67-81).
**Bloques:** `backend/app/canva4g.py` — `SECCIONES` (l.34-97): presentacion, vision(ser/hacer/tener), mision, valores, pilares, roles, bloque; tipos `fijo`/`lista` + `obligatorios`. Extracción `transcribir_audio`/`extraer_seccion`; `resumen_canva` (memoria entre bloques).
**Front:** `backend/static/4g/{index.html,app.js}` — stepper + canva en vivo + transcripción; WS `/ws/4g`; eventos `ready/user/bot/canva/booked`.
**RAG (montado, listo):** `rag.retrieve(subject_id, query, k)` (`rag.py` l.7-22, filtra `WHERE subject_id`); `embed_texts(..., task_type)` `gemini-embedding-001` 768-dim (`embeddings.py`); `chunk_text(size=1000, overlap=150)` (`chunking.py`); `POST /ingest` (`main.py` l.72-98); tabla `chunks(subject_id, content, embedding vector(768), metadata)` + HNSW coseno (`db/init/01_init.sql`).
**Agenda:** `agenda.crear_evento` (usado en bloque final → evento real Calendar).
**GAP confirmado:** `/ws/4g`, `/ws/call` (`live_relay.py`) y `/ws/telnyx` (`telnyx_relay.py`) son **Gemini Live puro SIN retrieval**. Solo la cascada `voice.py` (`/voice/ws`) usa RAG. Para 4G, enganchar `rag.retrieve()` en `_inyectar_agente()` (material por bloque) o `_preparar_prompt()` (contexto general).
