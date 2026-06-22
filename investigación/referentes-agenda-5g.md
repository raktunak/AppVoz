# Referentes de mercado — Agenda 5ª Generación

> Búsqueda: 2026-06-22. Objetivo: identificar qué productos/servicios existen ya en el espacio de "copiloto conversacional por voz para productividad/coaching", compararlos con la tesis AppVoz y detectar el hueco de mercado.

## Tesis AppVoz (recordatorio)

La **Agenda 5G** se define por la intersección de **cuatro** capacidades que deben darse juntas:

1. **Conversación por voz** — no chat, no scheduler mudo. Voz full-duplex como interfaz principal.
2. **RAG anclado** — responde desde un método/libro concreto (grounding), no desde conocimiento genérico del LLM.
3. **Acción real** — ejecuta (crea bloques en Calendar, refleja la agenda). No solo aconseja.
4. **Memoria del alumno** — recuerda entre sesiones (PEP, Canva, rachas, perfil, cronófago dominante).

**Foso**: Conversación + Conocimiento + Acción. Quita una y se cae.



## 1. Reclaim.ai (Dropbox)

**URL:** <https://reclaim.ai>
**Tipo:** AI calendar assistant / scheduler inteligente
**Tracción:** +600.000 usuarios, 70.000 empresas. Clientes: Grafana, Zapier, Indeed, Miro, 1Password, Zendesk, Instacart

### Qué hace
- **AI Focus Time:** defiende bloques de deep work automáticamente según un objetivo semanal
- **AI Habits:** rutinas recurrentes flexibles que se auto-ubican en el calendario
- **AI Tasks:** sincroniza tareas desde Asana, ClickUp, Todoist, Jira, Linear, Google Tasks y las agenda por prioridad
- **AI Smart Meetings:** busca el mejor slot entre asistentes; optimiza reuniones internas
- **AI Scheduling Links:** alternativa a Calendly (524% más disponibilidad, meetings 15.3% antes)
- **AI Buffer Time:** breaks, preparación y seguimiento automáticos
- **AI Calendar Sync:** bloquea disponibilidad entre múltiples calendarios (Google + Outlook)
- **AI Planner:** plan diario automatizado
- **AI Assistant (chat):** planificar, priorizar y optimizar por chat
- **Time Tracking + People Analytics + Workforce Analytics:** dashboards de uso del tiempo por equipo
- **Slack Status Sync:** sincroniza estado con el calendario
- **Pomodoro Timer** integrado
- **Enterprise:** SSO/SCIM, SOC 2 Type II, GDPR, 99.9% uptime, custom onboarding
- Pricing: plan gratuito (Lite), Starter ($8/mes), Business ($12/mes), Enterprise

### Métricas que declaran
- +7.6h focus time / semana
- -2.3 reuniones / semana
- -49% tiempo desperdiciado
- -4.15h overtime / semana
- +55.4% productividad
- +41.9% work-life balance
- -46.7% burnout
- -66.6% decision paralysis
- -77.2% work stress

### Qué NO tiene (vs. AppVoz 5G)
- **Sin voz:** la interacción es vía UI (drag & drop, formularios) o chat texto. No hay conversación por voz.
- **Sin RAG anclado a un método:** optimiza el calendario con heurísticas + AI, pero no "enseña" ni está grounded en un libro/metodología (no sabe de Eisenhower, Kairós/Cronos, T.A.R.G.E.T., los 4 pilares, etc.).
- **Sin pedagogía conversacional:** es un scheduler, no un coach socrático. No hace preguntas para que elabores; ejecuta por ti.
- **Sin onboarding guiado por voz:** no te lleva de la mano por las fases del método (conciencia → agenda → aplicación).
- **Enfoque equipo/empresa:** la capa de analytics y las Initiatives están pensadas para managers/orgs, no para el viaje personal de autoliderazgo.
- **Sin diagnósticos de perfil:** no determina si eres Guerrero/Planificador/Director/Zen, no ajusta el tono.
- **Sin memoria del "quién eres":** no recuerda tu PEP, tus valores, tu dotación, tu €/min, tus rachas, tus cronófagos entre sesiones más allá de preferencias de scheduling.

### Qué SÍ tiene (solapamiento parcial)
- Acción real sobre Calendar (crea bloques, los refleja)
- Time blocking + hábitos + tareas
- AI Assistant por chat (conversación textual, no voz)
- Métricas y analytics de uso del tiempo



## 2. Sesame

**URL:** <https://www.sesame.com>
**Tipo:** Agentes conversacionales por voz — "Personal intelligence with a point of view"
**Tracción:** Early stage. Gafas inteligentes previstas para 2027. Research preview disponible.

### Qué hace
- Agentes de voz con personalidad ("a collection of personal agents")
- Conversación natural para "los momentos entre momentos" (in-between moments)
- "Think out loud. Follow a thread. Discover something unexpected."
- Hardware propio en camino: gafas con audio de alta calidad para uso manos-libres
- Enfoque: curiosidad, exploración, acompañamiento

### Qué NO tiene (vs. AppVoz 5G)
- **Sin RAG anclado a método:** propósito general, no formación/coaching
- **Sin acción (Calendar):** conversa pero no ejecuta; no agenda bloques
- **Sin memoria estructurada:** no persiste Canva, PEP, rachas entre sesiones
- **Sin pedagogía:** no sigue un método (Eisenhower, T.A.R.G.E.T., etc.)
- **Enfoque distinto:** es un compañero de conversación, no un coach de productividad

### Qué SÍ tiene (solapamiento parcial)
- Voz como interfaz principal
- Conversación natural, tono personal
- Visión de "agentes personales" (alineado con el concepto de copiloto)
- Hardware dedicado (gafas) — apuesta por voz manos-libres



## 3. Pi.ai (Inflection AI)

**URL:** <https://pi.ai>
**Tipo:** Chatbot conversacional con tono empático de "coach personal"

### Qué hace
- Conversación texto/voz con tono cálido, empático, de apoyo
- Diseñado para ser un "compañero" más que un asistente transaccional
- Puede mantener conversaciones largas con memoria de contexto

### Qué NO tiene (vs. AppVoz 5G)
- **Sin RAG anclado:** conocimiento genérico del LLM, no grounded en material concreto
- **Sin acción (Calendar):** no agenda, no ejecuta
- **Sin memoria persistente estructurada** entre sesiones
- **Sin método/productividad:** no enseña un sistema, no tiene pedagogía
- **Sin orquestación de modalidades:** no lanza tests, esquemas, vídeos

### Qué SÍ tiene (solapamiento parcial)
- Tono conversacional empático
- Cierto nivel de memoria conversacional
- Enfoque en bienestar/coaching personal



## 4. Gemini Live (Google)

**URL:** Producto integrado en la app de Gemini / Google AI Studio
**Tipo:** Voz full-duplex nativa con capacidad multimodal (audio + video)

### Qué hace
- Conversación por voz en tiempo real con el modelo `gemini-2.5-flash-native-audio`
- Barge-in nativo (interrupción)
- VAD (Voice Activity Detection) del lado de Google
- Streaming de audio bidireccional
- Comprensión de video en tiempo real (compartir pantalla/cámara)

### Qué NO tiene (vs. AppVoz 5G)
- **Sin RAG anclado a método propio:** conocimiento genérico
- **Sin acción (Calendar):** no agenda, no crea eventos
- **Sin memoria entre sesiones:** cada sesión es independiente
- **Sin pedagogía:** no sigue un currículum/método
- **Sin personalización por perfil**
- **Producto de consumo generalista**, no verticalizado

### Qué SÍ tiene (solapamiento parcial)
- Voz full-duplex (es la misma tecnología base que usa AppVoz en su vía Live Relay)
- Barge-in y VAD nativos
- Calidad de voz excelente
- Latencia baja



## 5. VoiceRAG (proyectos open-source)

### VoiceRAG — petermartens98
**URL:** <https://github.com/petermartens98/VoiceRAG-AI-Powered-Voice-Assistant-with-Knowledge-Retrieval>
- Combina ElevenLabs Voice Agents + OpenAI GPT + Supabase/Vector DB + n8n
- Voice-to-voice con RAG sobre base de conocimiento personal

### Building a Real-Time Voice-to-Voice Conversational Agent with RAG (Medium)
**URL:** <https://medium.com/@geetmanik2/building-a-real-time-voice-to-voice-conversational-agent-with-retrieval-augmented-generation-rag-92c090d91934>
- Arquitectura completa de agente conversacional voz-a-voz con RAG

### AI Personal Productivity Assistant — Bayzid03
**URL:** <https://github.com/Bayzid03/AI-Personal-Productivity-Assistant>
- RAG-based assistant que transforma notas/documentos en base de conocimiento conversacional

### Voice-Enabled RAG (artículo ChatNexus)
**URL:** <https://articles.chatnexus.io/knowledge-base/voice-enabled-rag-the-future-of-spoken-ai-interact/>
- "Voice-enabled RAG is not just an incremental upgrade; it's a transformational shift"

### RAG for voice platforms (Gladia)
**URL:** <https://www.gladia.io/blog/rag-for-voice-platforms-combining-the-power-of-llms-with-real-time-knowledge>
- Combinación de STT + LLM + RAG para plataformas voice-first

### Qué NO tienen (vs. AppVoz 5G)
- Son infraestructura/tecnología, no producto
- Sin acción (Calendar)
- Sin método pedagógico concreto
- Sin onboarding guiado
- Sin memoria del alumno estructurada



## 6. Microsoft Copilot Studio

**URL:** <https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/retrieval-augmented-generation>
**Tipo:** Plataforma enterprise para construir agentes con RAG sobre documentos corporativos

### Qué hace
- RAG sobre SharePoint, bases de conocimiento, documentos enterprise
- Agentes conversacionales personalizables
- Grounding en contenido organizacional
- Orientado a soporte interno, RRHH, IT helpdesk

### Qué NO tiene (vs. AppVoz 5G)
- **Sin voz nativa:** orientado a chat texto
- **Sin coaching/productividad personal:** casos de uso enterprise/soporte
- **Sin acción (Calendar) sobre cuenta personal**
- **Sin pedagogía/método**
- **Sin memoria del alumno entre sesiones**



## 7. Motion (usemotion.com)

**Tipo:** AI scheduler que planifica automáticamente tu día
(Nota: no confundir con motionapp.com que es de creative analytics para anuncios)

### Qué hace
- Planificación diaria automática por prioridades
- Reorganiza tareas si surge algo urgente
- Time blocking automático

### Qué NO tiene (vs. AppVoz 5G)
- Sin voz
- Sin conversación
- Sin RAG anclado a método
- Sin pedagogía
- Sin diagnósticos de perfil
- Sin memoria del "quién eres"



## 8. Otros actores tangenciales

- **Yoodli:** AI speech coach (presentaciones, entrevistas) — voz + feedback, pero sin productividad/agenda
- **Otter.ai / Fireflies.ai:** transcripción de reuniones + resúmenes — sin coaching ni agenda
- **Notion AI / Mem / Reflect:** notas con AI — sin voz, sin acción calendar
- **Rosebud:** AI journaling — voz + reflexión, pero sin método de productividad ni acción



## Resumen: matriz comparativa

| Capacidad | Reclaim | Sesame | Pi.ai | Gemini Live | VoiceRAG | Copilot Studio | **AppVoz 5G** |
|---|---|---|---|---|---|---|---|
| Voz full-duplex | ❌ | ✅ | ✅ parcial | ✅ | ✅ | ❌ | ✅ |
| RAG anclado a método | ❌ | ❌ | ❌ | ❌ | ✅ (genérico) | ✅ (enterprise) | ✅ (libro 4G) |
| Acción real (Calendar) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Memoria del alumno | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Pedagogía socrática | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Diagnósticos de perfil | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Orquestación de modalidades | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Onboarding guiado | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Métricas de progreso | ✅ (equipo) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (personal) |

## Conclusión

**El hueco está confirmado.** Nadie ha juntado las tres patas (Conversación + Conocimiento + Acción) en un solo producto, y menos aún con la cuarta pata (Memoria del alumno + pedagogía).

Los competidores más cercanos atacan **una** dimensión cada uno:
- **Reclaim** → Acción (calendar), sin voz ni pedagogía
- **Sesame / Pi** → Voz + empatía, sin método ni acción
- **Gemini Live** → Infraestructura de voz, sin dominio ni memoria

La tesis del documento `Vision-Agenda-5G-Pedagogia-Conversacional.md` se sostiene: *"que hable no es el foso — cualquiera enchufa un LLM. El foso es la intersección de tres cosas: anclado (RAG), con memoria, con acción. Quita una y se cae."*

---

*Fuentes consultadas el 2026-06-22: reclaim.ai, sesame.com, pi.ai, Google AI Studio, GitHub (VoiceRAG, AI-Personal-Productivity-Assistant), Gladia.io, Microsoft Learn, ChatNexus, DuckDuckGo.*
