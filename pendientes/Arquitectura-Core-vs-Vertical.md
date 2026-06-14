---
titulo: "Visión de arquitectura — core compartido vs. vertical"
tags: [proyecto, arquitectura, ia, langraph, rag, voz, plataforma]
fecha: 2026-06-14
---

# Arquitectura: core compartido vs. vertical

Visión acordada del Motor: **una base conversacional sólida y reutilizable + habilidades enchufables + conocimiento por vertical**. Sirve para **cualquier curso/utilidad**; lo que cambia —y lo que aporta el valor— es **el conocimiento que se le añade**.

## La idea en limpio
Un **motor conversacional por voz** con dos entradas genéricas por cada caso de uso:
1. **El conocimiento** que le inyectas (el corpus: cualquier curso, libro o material) → vía RAG. *Aquí está el valor y la defensa: el motor es genérico, el conocimiento lo hace único.*
2. **Las habilidades** (acciones) que le activas (gestionar la agenda/Calendar, recordatorios, captura, quizzes…) como **módulos conectables**.

**Un caso de uso = conocimiento + habilidades + persona.**
- *Coach 4G:* libro de 4ª Generación (conocimiento) + gestión de agenda (habilidad) + coach (persona).
- *Curso de historia:* su temario (conocimiento) + quizá sin agenda.
- *Formación de ventas:* su material + agenda de práctica.

Mismo motor, distinto conocimiento.

## Dónde está la línea (lo importante)

**CORE compartido — genérico y estable:**
- Capa de **LLM** (enrutado de modelos, fallback; Vertex / LiteLLM).
- **Runtime de RAG** (ingesta, embeddings, retrieval, aislamiento multi-tenant por `subject_id`).
- **Runtime de LangGraph / agentes**: el *andamiaje* — gestión de estado, bucle de tool-calling, streaming, human-in-the-loop, manejo de errores.
- **Pipeline de voz** (cascada STT→LLM→TTS, barge-in, WebSocket).
- **Infra y datos** (Postgres+pgvector, Cloud SQL, Redis/Memorystore, auth, multi-tenancy, observabilidad).
- **Los contratos/interfaces** de habilidades y de ingesta de conocimiento.

**POR VERTICAL — desarrollado por separado, encima del core:**
- El **conocimiento** (corpus).
- Las **habilidades** concretas (agenda, quizzes, recordatorios…), implementadas contra la interfaz del core.
- Los **grafos/flujos de agentes concretos**, la **persona** (prompts) y la **UI/branding**.

## El matiz que no hay que perder
Lo común es **el motor para construir agentes** (el framework/SDK), **no los agentes concretos**. Los grafos específicos tienden a ser de cada vertical; si intentas hacerlos genéricos, sobre-abstraes y el core acaba "sabiendo" demasiado de cada caso.

> Regla: **el core ofrece el "cómo se ejecutan los agentes"; cada vertical define "qué agentes y con qué habilidades".**

## Sobre Truebalance (aclaración)
Truebalance **no es el producto a comparar** ni se mezcla con esto. Es la **prueba de que el core funciona**: ya implementa buena parte del común (LangGraph, RAG, Cloud Run, multi-tenant). Las partes **arquitectónicas comunes** sí tiene sentido compartirlas; las **habilidades y lo no común** se desarrollan por separado en cada utilidad. Que el stack se parezca es la señal de que el core es real, no un error de planteamiento.

## Cómo construirlo (sequencing)
1. **Extraer el core del código que ya funciona** (no diseñarlo en abstracto): factorizar lo común a una base probada.
2. **Congelar pronto lo caro de cambiar**: par embeddings + chunking, capa de datos, y **la interfaz de habilidades**.
3. **Cerrar la capa de datos** antes de escalar (salir de la VM única → Cloud SQL + Memorystore). Innegociable.
4. Montar el **tutor / coach 4G como primer vertical limpio** encima del core.

## La disciplina que lo sostiene (o degenera en N forks)
- **Multi-tenancy invariante:** nunca un retrieval sin filtro `subject_id`.
- **Embeddings/chunking congelados** antes de escalar (cambiarlos = reingestar todo).
- **Conocimiento y habilidades como dato/config detrás de interfaz**, nunca cableados en el core.
- **Core delgado:** resistir meter lógica de un vertical concreto en el core (la necesidad de un vertical va a su habilidad/config, no al común).

## Riesgos
- **Sobre-abstracción** de los grafos de agentes (hacer genérico lo que es de cada vertical).
- **Platformizar antes de validar** un vertical que funcione/se pague → extraer el core *de lo que ya funciona*, no construir framework desde cero.
- **Capa de datos como punto único de fallo** → multiplicaría el riesgo por cada vertical.
