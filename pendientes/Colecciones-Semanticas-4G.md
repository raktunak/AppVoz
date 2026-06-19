# Colecciones semánticas (RAG) para la FORMACIÓN 4G

> Decisión 2026-06-19. Objetivo: una **formación por voz** sobre el motor AppVoz que **pueda
> sustituir al libro** *La Agenda de Cuarta Generación* (enseñar + coachear el método, no solo
> leerlo). Reemplaza la idea previa de "capas RAG" que incluía la biblioteca de 16 resúmenes
> (**descartada** para este vertical). **El RAG NO entra en el MVP actual** (mejora posterior);
> esto es el **diseño objetivo** del corpus.

## Las preguntas que deciden las colecciones
1. **¿Qué tiene que saber para enseñar el método?** → conocimiento **canónico** (el qué).
2. **¿Qué le falta al libro para ser una formación de verdad** (no solo lectura)? → ejemplos,
   ejercicios, técnica continua, casos, la voz del formador → el "cómo" que **solo aporta el autor**.
3. **¿Qué dudas, objeciones y resistencias** tendrá el alumno al aplicarlo, y cómo se responden
   bien? → el **coaching reactivo**.
4. **¿Qué necesita saber DEL alumno** para personalizar? → su **propio recorrido**.
5. **¿Qué NO va a RAG** (va a tablas relacionales)? → el estado estructurado.

## Las colecciones

**3 colecciones de CONOCIMIENTO (compartidas, aisladas por `subject_id`):**
1. **`metodo-4g` — el libro:** la fuente **canónica** (Kairós/Cronos, pilares, roles, T.A.R.G.E.T.,
   Eisenhower, cronófagos). El agente enseña/cita **anclado aquí**. *(Ya lo tenemos: la transcripción.)*
2. **`formacion-4g` — material ampliado de FABIÁN (la que él tiene que aportar):** transcripciones
   de sus clases/charlas, ejercicios, casos reales, su forma de explicar. Es lo que **convierte el
   libro en formación** y cubre su "punto flojo" (el libro no da técnica continua más allá del set-up
   matutino). **Sin esto, "sustituir el libro" se queda corto.** → **Pedir a Fabián este material.**
3. **`qa-4g` — preguntas, dudas y resistencias:** banco de Q&A / objeciones frecuentes con su
   respuesta canónica (derivable de las sesiones de Fabián o curado). Deja al coach **resolver
   atascos** con consistencia (las "preguntas doradas" del plan de persistencia).

**1 capa PERSONAL (aislada por `user_id`, no compartida):**
4. **Memoria/PEP del alumno:** su Canva, decisiones, patrones, qué le cuesta → personaliza el
   coaching (*"llevas 3 semanas aplazando 'salud'"*). No es corpus de materia, es su historial.

**Fuera de RAG → a Postgres (estado estructurado):** PEP, pilares, roles, objetivos T.A.R.G.E.T.,
bloques, progreso y métricas. *Principio: el LLM no calcula; la BD calcula, el LLM interpreta y redacta.*

## Notas / invariantes
- **La que aporta Fabián es la (2) `formacion-4g`** — encaja con "una nos la tenía que dar él".
- **Aislamiento:** compartidas por `subject_id`, la personal por `user_id`; nunca retrieval sin filtro.
- **Embeddings/chunking congelados** (cambiarlos = reingestar todo).
- **Biblioteca de 16 resúmenes: descartada** para este vertical (era de un planteamiento anterior).
- Relacionado: `Soluciones-IA-y-Google.md` §2, `Plan-Persistencia-y-Memoria.md` §7, `MVP-Onboarding-Voz-Canva.md` (RAG fuera del MVP).
