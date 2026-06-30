# Plan — Vista 4G 2.0 (Sesión 0 · Diagnóstico)

> Estado: vivo / en desarrollo · Creado 2026-06-28
> Base de contenido: `Guion-Asistente-Faro-4G.md` (Obsidian, *app 4 generación*) — Sesión 0, 9 beats.
> No toca la `/4g` actual. Ruta nueva: **`/4g2`**.

## Contexto (por qué)

La `/4g` actual funciona bien como **motor** (agentes por bloque sobre una sola sesión de voz,
extracción determinista a BD, persistencia incremental), pero su **vista** muestra los 7 bloques
del Canva todos a la vez compartiendo pantalla. Para la experiencia de **diagnóstico** (Sesión 0
del guion de Faro) queremos lo contrario: **una sola escena enfocada cada vez, con menos
distracciones**, y un **escenario que cambia según el beat** (chat, gráfico de semanas de vida,
deslizadores, calculadora, vídeo, tarjeta de Calendar…). La info se sigue llenando con **agentes
separados** que capturan a la BD y se **anclan al libro vía RAG** (`subject_id = libro-4g`) — algo
que la `/4g` aún no hace (hoy solo usa persona + preguntas literales).

Resultado buscado: la misma filosofía de motor, pero con una interfaz de **un paso a la vez** + un
**menú del recorrido a la izquierda** para navegar atrás/adelante (ver lo que falta **sin marcarlo**),
y un **centro adaptativo** que monta el componente que cada beat necesita.

## Qué se reutiliza vs. qué es nuevo

**Reutilizar (importar, no copiar):**
- Transporte de voz: `live_relay._client`, `_build_config`, `_vad_params`, `_browser_to_gemini`.
- STT fiable y patrón de extracción: `canva4g.transcribir_audio`, `canva4g.extraer_seccion` (mismo molde).
- Config/persona del servicio: `persistence.resolver_servicio` (reutilizamos el servicio `4g` o uno nuevo `4g2`).
- Agendado: `agenda.crear_evento` (Beat 8) — idéntico a `_agendar_bloque` de la /4g.
- Plomería de audio del cliente (`playChunk`, `downsample`, `toPCM16`, captura mic, manejo WS) — se copia
  de `static/4g/app.js` y se adapta.
- **NUEVO cableado:** `rag.retrieve(subject_id, query, k)` para anclar las frases de cada agente al libro.

**Nuevo:**
- `backend/app/sesion0_4g.py` — espejo de `onboarding_4g.py`+`canva4g.py` pero con **BEATS** (no secciones de Canva),
  inyección de agente por beat con RAG, extracción por beat, WS `/ws/4g2`, persistencia `sesion0_4g`.
- `backend/static/4g2/{index.html, app.js}` — vista nueva (menú-recorrido + escenario adaptativo).
- Montaje `/4g2` en `main.py` + registro del router.

## Arquitectura

- **Ruta/estáticos:** `app.mount("/4g2", _NoCacheStatic(directory="static/4g2", html=True))` (igual que `/4g`).
- **WS:** `/ws/4g2`, mismo handshake `{type:"config", user_id}`; audio PCM16 16k ↔ PCM 24k.
- **Datos (BD):** tabla `sesion0_4g` (una fila JSONB por usuario), DDL idempotente como `canva_4g`.
  Documento por usuario, una clave por beat. Campos clave a capturar:
  | beat | clave datos | tipo |
  |------|-------------|------|
  | 2 | `edad` | número (→ rejilla de semanas) |
  | 1 | `lo_importante` | texto libre |
  | 3 | `pendientes` | lista |
  | 4 | `productividad`,`estres`,`felicidad` | 1-10 (deslizadores) |
  | 5 | `facturacion_anual` | número (→ €/h, €/min) |
  | 8 | `accion`,`fecha_hora_iso` | texto + ISO (→ Calendar) |
- **RAG (2ª pasada, no de entrada):** cada agente podrá recuperar 1-2 fragmentos del libro (`libro-4g`) con la
  consulta propia del beat (p.ej. Beat 2 → "el tiempo es vida, finitud, semanas") e inyectarlos como material de
  apoyo en el relevo de rol. Misma invariante: **siempre filtrado por `subject_id`**.
  ⚠️ **Estado real:** la tabla `chunks` solo tiene 1 fragmento (`demo_voz`); **`libro-4g` tiene 0 chunks**. Hasta
  ingerir el libro, `rag.retrieve("libro-4g", …)` no devolvería nada. Decisión tomada: **cablear el flujo primero
  (Beats 1-2 funcionan sin RAG, con persona + guion literal) y añadir el anclaje RAG después**, una vez ingerido
  el **libro completo** (`Libro-La-Agenda-4G.md`, Obsidian) con `subject_id=libro-4g` vía `/ingest`.
- **Agentes por beat:** mismo patrón que `_inyectar_agente`: relevo de rol en la MISMA sesión de voz
  (sin reconectar → la voz no se corta), con memoria de lo ya capturado + guion del beat + material RAG.

## Los 9 beats → escenario central

`tipo` decide qué monta el centro y si el micro está activo.

| # | Beat | `tipo` escenario | Mic | Componente central |
|---|------|------------------|-----|--------------------|
| 1 | La pregunta que duele | `voz` | sí | solo chat / onda |
| 2 | Que lo sienta (finitud) | `voz+semanas` | sí | **rejilla de ~4.400 semanas**; se rellena con `edad` real |
| 3 | Descarga del "millón de cosas" | `voz+lista` | sí | lista en vivo de pendientes |
| 4 | La foto rápida | `formulario` | no | 3 deslizadores 1-10 |
| 5 | Lo que cuesta tu tiempo | `voz+calc` | sí | calculadora €/h, €/min |
| 6 | Recurso de contenido | `video` | no | microclip + subtítulo |
| 7 | El espejo | `voz` | sí | chat; el agente sintetiza la contradicción desde los datos |
| 8 | La primera acción (gating) | `voz+calendar` | sí | tarjeta de evento Calendar |
| 9 | Veredicto + puente | `voz+brecha` | sí | esquema de la brecha + CTA |

## La vista nueva (menos distracciones)

- **Izquierda — menú del recorrido:** los 9 beats en vertical. El actual se resalta; los anteriores son
  navegables (clic = volver a ese beat para modificar); los siguientes se ven en gris **sin marca de "hecho"**
  (mostrar lo que falta, sin gating visual). Sin checkmarks de compleción duros.
- **Centro — escenario único activo:** ocupa el foco; monta el componente del beat actual (chat + el visual
  que toque). Un beat a la vez, nada de tarjetas apiladas.
- **Header minimalista:** título + estado + reset. Configuración enlaza al panel `/call` como en la /4g.
- El **chat/transcripción** convive con el visual dentro del escenario (no en una tercera columna fija salvo
  en desktop ancho, donde puede ir a la derecha; en móvil se apila).

## Plan incremental (paso a paso)

**Fase 0 — Andamiaje** (una vez, antes de los beats):
1. `sesion0_4g.py`: lista `BEATS` (las 9, con `key/titulo/tipo/guion/rag_query/datos`), DDL+persistencia,
   WS `/ws/4g2` reutilizando los helpers de `live_relay`, extracción por beat, cableado `rag.retrieve`.
2. `static/4g2/index.html` + `app.js`: shell con menú-recorrido + contenedor de escenario + plomería de audio.
3. `main.py`: registrar router y `mount("/4g2", …)`.
4. Renderer de escenario que conmuta por `tipo` (de momento solo `voz` = chat).

**Beat 1 — La pregunta que duele** (`voz`): agente con rol del beat 1 anclado a RAG; captura `lo_importante`;
el menú-recorrido navega; el chat aparece. *Hito: hablar y ver la respuesta + dato en BD.*

**Beat 2 — Finitud** (`voz+semanas`): captura `edad`; componente **rejilla de semanas** (SVG/canvas) que se
rellena con la edad real (apaga ~edad·52 puntos sobre ~4.400). El agente pregunta la edad y dispara el render.

**Beats 3 → 9:** cada uno añade su componente de escenario (lista, deslizadores, calculadora, vídeo, tarjeta
Calendar reutilizando `agenda.crear_evento`, esquema de brecha) siguiendo el mismo molde de agente+extracción.

## Verificación (por paso)

- La pila ya corre con `--reload` y `./backend` montado: los `.py` y estáticos nuevos se recogen en caliente,
  **sin rebuild**. Si se añade un módulo nuevo, basta con que uvicorn recargue.
- Por beat: abrir `http://localhost:8080/4g2`, pulsar el beat en el menú, hablar (o usar el componente),
  y comprobar (a) el escenario correcto, (b) la transcripción, (c) la fila en `sesion0_4g`
  (`docker compose exec db psql -U appvoz -d appvoz -c "select datos from sesion0_4g;"`),
  (d) `docker compose logs -f api` sin errores.
- Beat 8: comprobar el evento real en Google Calendar (mismo camino que la /4g).

## Archivos

- **Nuevos:** `backend/app/sesion0_4g.py`, `backend/static/4g2/index.html`, `backend/static/4g2/app.js`.
- **Modificados:** `backend/app/main.py` (router + mount).
- **Sin tocar:** todo lo de `/4g` (`onboarding_4g.py`, `canva4g.py`, `static/4g/*`).

## Decisiones tomadas

- **RAG:** flujo primero, RAG después. Beats 1-2 sin RAG (persona + guion literal). El anclaje RAG entra como 2ª
  pasada, tras ingerir el libro. ✅ decidido (2026-06-28).
- **Fuente del libro para ingerir:** **libro completo** (`Libro-La-Agenda-4G.md`), no la síntesis. ✅ decidido.

## Decisiones abiertas

- ¿Servicio de voz: reutilizar `4g` o crear `4g2` (persona "Faro diagnóstico")? → propuesto: reutilizar `4g` al
  principio; separar si la persona diverge.
- ¿Beat 6 (vídeo) con clip real o placeholder al principio? → placeholder en el primer pase.
