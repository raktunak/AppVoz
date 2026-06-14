---
titulo: "Plan MVP — Tutor por voz (3 vueltas)"
tags: [proyecto, mvp, plan, voz, rag, tutor]
fecha: 2026-06-14
---

# Plan MVP — Tutor por voz

Plan en tres vueltas para el **tutor por voz** (primer vertical del Motor — ver [[Motor Tutor por Voz]] y [[Arquitectura-Core-vs-Vertical]]). Aterrizado sobre el stack del [[Documento-Tecnico-Stack]] (cascada de voz, pgvector, `subject_id`, capa de datos sólida desde el día 1).

**Dos roles:** **Owner** (aporta el contenido) · **Alumno** (aprende por voz).

## 🟢 Lista 1 — MVP básico
*Objetivo: que un alumno hable con un tutor que responde DESDE un material concreto, y se pueda validar (y cobrar).* Lo mínimo imprescindible.

- **Ingesta de corpus** por materia: subir PDF/texto → chunking → embeddings → índice por `subject_id` (al inicio puede ser un script manual, sin panel).
- **Retrieval RAG** con **aislamiento por `subject_id`** (multi-tenancy invariante desde el día 1).
- **Pipeline de voz en cascada**: STT streaming → LLM → TTS, sobre WebSocket; detección de fin de turno y **barge-in** básico.
- **Respuesta anclada al material** (grounding): el tutor contesta desde el corpus, con logging del fragmento usado.
- **Frontend mínimo de conversación**: botón de micro, transcripción en vivo, audio de vuelta.
- **Auth básica** (login) + selección de materia.
- **Memoria de sesión** (historial dentro de la conversación).
- **Capa de datos sólida**: Postgres + pgvector en Cloud SQL (sin VM única / sin SPOF). *Innegociable.*
- **Observabilidad mínima**: latencia por etapa (TTFA), errores y **coste por sesión**.

## 🟡 Lista 2 — 2ª vuelta
*Objetivo: que sea bueno y retentivo — memoria, progreso y control del owner.*

- **Memoria del alumno entre sesiones**: perfil + conceptos vistos + resúmenes asíncronos post-sesión.
- **Seguimiento de progreso / mastery** por concepto (extraídos del propio corpus).
- **Panel del owner**: subir/gestionar corpus, ver estado de ingesta, calidad de retrieval.
- **Evaluación de retrieval**: 20–30 "preguntas doradas" por materia (antes de pulir la voz).
- **Persona/config del tutor** por materia (tono, estilo) — como dato, no código.
- **Modo texto** además de voz (accesibilidad / fallback).
- **Anti-alucinación explícito**: "esto no está en el material" en vez de inventar.
- **Reconexión/resume robusto** del WebSocket.
- **Planes y límites de uso** (freemium) + control de coste por sesión.
- **Afinado de latencia**: endpointing por público, retrieval especulativo.

## 🔵 Lista 3 — 3ª vuelta
*Objetivo: plataforma, habilidades y escala — aquí nace el "cualquier curso" y el puente al coach 4G.*

- **Multi-vertical self-service**: alta de nuevas materias/cursos sin tocar arquitectura.
- **Habilidades enchufables** (catálogo): la primera, **gestión de agenda / Google Calendar + recordatorios** → puente directo al [[App 4 Generación|coach 4G]].
- **Quizzes / ejercicios** generados desde el corpus + evaluación.
- **Analítica para el owner**: uso, temas difíciles, retención.
- **Pasarela de pago** real.
- **Escala**: WebRTC si la red lo exige; pgvector → Vertex AI Search / AlloyDB si el volumen crece.
- **Multimodal**: imágenes/diagramas en el corpus; voces/TTS de mayor calidad.
- **PWA / móvil** e **internacionalización** (multi-idioma).

## Criterio de corte
La **Lista 1** debe bastar para sentar a alguien a usarlo y aprender de verdad; todo lo que no impida eso baja a la 2 o la 3.
