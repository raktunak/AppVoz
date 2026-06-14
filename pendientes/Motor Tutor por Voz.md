---
titulo: "Motor Tutor por Voz"
tags: [proyecto, voz, rag, ia, gcp, plataforma]
fecha: 2026-06-14
estado: MVP próximo a lanzar
---

# Motor Tutor por Voz

**Un tutor por voz en tiempo real que enseña desde el material que aporta el dueño del producto** (no desde internet genérico): el alumno habla → RAG recupera el fragmento del temario → un LLM responde → se devuelve hablado, con latencia de conversación.

> **Tesis:** no es "un tutor", es un **esqueleto genérico voz+RAG con memoria**. El conocimiento es un dato de entrada (corpus indexado por materia), no código. Cambiar corpus + persona del tutor = otro vertical **sin tocar la arquitectura** → de "un producto" a "una plataforma".

## Stack en una línea
Gemini Flash (Vertex AI) + **pgvector** sobre Postgres + **Pipecat** (cascada STT→LLM→TTS) sobre FastAPI, todo en **GCP** (Cloud SQL + Memorystore). Coste ~$0.025/min (~$0.37 por sesión de 15 min).

## Documentos
- [[Arquitectura-Core-vs-Vertical]] — **visión acordada**: base conversacional + habilidades enchufables + conocimiento por vertical; dónde está la línea core vs. vertical y cómo construirlo.
- [[MVP-Plan]] — plan del tutor por voz en 3 vueltas (MVP básico → 2ª → 3ª).
- [[Documento-Tecnico-Stack]] — stack completo, fortalezas, qué es crítico vs. cambiable, reutilización por verticales y veredicto.
- [[motor_tutor_voz_reutilizacion.docx]] — documento original (Descargas, 14 jun 2026).

## Relación con otros proyectos
- [[App 4 Generación]] — el **coach 4G por voz es justo un vertical voz+RAG**: este motor podría ser su plataforma (corpus = el libro 4G, persona = coach). Encaja con [[Arquitectura-Agentes]].
- [[Truebalance]] — **no es el producto a comparar; es la prueba de que el core funciona** (ya usa LangGraph, RAG, Cloud Run, multi-tenant). Lo común (arquitectura) se comparte; las habilidades y lo no común se desarrollan por vertical. Ver [[Arquitectura-Core-vs-Vertical]].

## Lo crítico antes de escalar (del doc)
- **Cerrar la capa de datos**: migrar la VM única a Cloud SQL + Memorystore (punto único de fallo). Innegociable antes de meter usuarios o duplicar verticales.
- Fijar **embeddings + chunking** antes de escalar (cambiarlos = reingestar todo).
- **Multi-tenancy explícito**: nunca retrieval sin filtro `subject_id`.

## Próximos pasos
1. Elegir un **2º vertical candidato** (corpus + público) — p. ej. el coach 4G.
2. Confirmar que encaja en "enseña desde un corpus fijo".
3. Estimar volumen de chunks y QPS (que siga en rango de pgvector).
4. Cerrar la capa de datos del primer producto antes de duplicar nada.
