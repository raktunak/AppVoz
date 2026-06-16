---
titulo: "Mercado: APIs de voz en tiempo real con voz propia/clonada"
tags: [investigacion, voz, tiempo-real, clonacion, mercado, tts, s2s]
fecha: 2026-06-16
fuente: workflow multi-agente (18 agentes, doc oficial de cada proveedor)
aviso: "El mercado de voz cambia rápido. Precios y capacidades a junio-2026; reverificar antes de decidir."
---

# Voz en tiempo real + voz propia/clonada — comparativa de mercado

Pregunta de partida: **¿qué APIs de voz en tiempo real (Live) permiten usar voz propia/clonada?**
Contexto AppVoz: hoy usamos **Gemini Live**, que **solo admite voces preset** (no clona). Esto recopila las
alternativas por si en el futuro queremos "voz propia" en el tutor.

> **TL;DR:** 8 plataformas combinan tiempo real + voz propia. Solo **3 son speech-to-speech (S2S) nativo**
> como Gemini Live (OpenAI Realtime, Hume EVI 3, Azure Voice Live con modelos `*-realtime`); el resto son
> **cascada** (STT→LLM→TTS) donde el clon vive en la capa TTS. Para self-serve con S2S nativo, **Hume EVI 3**
> es lo más directo; en cascada, **ElevenLabs / Cartesia / Inworld**.

## Tabla resumen

| Proveedor | Arquitectura | Clonación | Self-serve | Precio aprox. |
|---|---|---|---|---|
| **ElevenLabs** (Agents) | Cascada + turn-taking propio | instant (~1-2 min) + professional | ✅ | $0.08–0.10/min agente |
| **Cartesia** (Sonic + Ink) | Cascada | instant (~3-10s) + PVC | ✅ | ~$0.06/min agente; TTS ~$0.03/min |
| **Resemble AI** | Cascada (LiveKit/WebRTC/SIP) | Rapid (~10s) + professional | ⚠️ WS streaming solo plan Business | ~$0.36/min |
| **Play.ai** (PlayHT) | Cascada | instant (~30s) + high-fidelity | ✅ | ~$0.18/min extra (Starter) |
| **Inworld AI** | Cascada (compat. OpenAI Realtime) | instant gratis (5-60s) + pro | ✅ | TTS ~$0.01/min (+LLM/STT) |
| **OpenAI Realtime** | **S2S nativo** (WebRTC/WS) | professional (consentimiento) | ❌ clientes aprobados | por tokens (audio caro) |
| **Hume AI EVI 3** | **S2S nativo** | instant (~15-30s) | ✅ | $0.04–0.07/min |
| **Azure Voice Live** | S2S o cascada según modelo | Personal (~1 min) + Custom Neural | ❌ acceso limitado | por tokens |

### No permiten voz propia (solo preset)
- **Gemini Live** (lo que usamos hoy).
- **Amazon Nova Sonic** (S2S nativo, voz→voz ~<500ms, pero "diseñado para responder solo con voces preseleccionadas, no replica la voz de entrada").
- **Deepgram Aura-2** (TTS realtime <200ms TTFB, sin clonación).
- **Rime AI** (realtime TTS, clonación de TU voz no documentada claramente — sin confirmar).

## Detalle por proveedor (lo relevante)

- **ElevenLabs** — Agents = ASR Scribe → LLM a elección → TTS Flash v2.5 + turn-taking/barge-in propio. Objetivo sub-segundo (TTS ~75ms modelo / ~135ms TTFB). Clon Instant (~1-2 min, casi instantáneo) o Professional (≥30 min, ideal 1-3h, con verificación "solo tu propia voz"). El clon se asigna como voz del agente (incluso multi-voz). Precio agentes desde $0.10/min (no incluye LLM, hoy absorbido por ElevenLabs).
- **Cartesia** — Sonic (TTS streaming WS) + Ink (STT); LLM de tercero (recomiendan Claude/OpenAI). TTS sub-90ms TTFA. Clon Instant (~3-10s, 1 cr/char) o PVC (min 30 min, ~3h entrenamiento). Voice Agents $0.06/min. Consentimiento no detallado en docs.
- **Resemble AI** — TTS streaming WS (Chatterbox/Turbo) ~200ms TTFS; integra LiveKit/WebRTC/SIP. Clon Rapid (~10s, <1 min listo) o Professional (10-25+ min). ⚠️ el WebSocket de streaming requiere plan Business+. ~$0.0005/s (~$0.36/min).
- **Play.ai (PlayHT)** — Agents (WS/WebRTC/SIP), modelo PlayDialog + TTS Play 3.0 mini (~143-190ms TTFB). Clon instant (~30s) o high-fidelity (≥30 min). LLM propio aparte. ~$0.18/min extra.
- **Inworld AI** — Realtime S2S API + Realtime TTS-2/1.5 con clon (voiceId). Cascada "swappable", compatible con protocolo OpenAI Realtime (solo cambiar base URL). Primer chunk voz→voz <1s; TTS <200ms. Clon instant **gratis** (5-60s). TTS ~$0.01/min (+LLM/STT).
- **OpenAI Realtime** — S2S **nativo** (gpt-realtime), WebRTC o WS. Custom Voices = professional con grabación de consentimiento obligatoria; **acceso restringido** (clientes elegibles, ventas). Precio por tokens (audio input $32/1M, output $64/1M en gpt-realtime-2). Análogo directo a Gemini Live.
- **Hume AI EVI 3** — speech-language model **S2S nativo**; "configure EVI to use your voice clone", "speak with any voice". Clon instant (~15-30s, ilimitado desde plan Creator $14/mes). Latencia objetivo ~300ms. $0.04–0.07/min.
- **Azure Voice Live** — un servicio WS que orquesta S2S nativo (modelos `*-realtime`) o cascada (gpt-4o/4.1/5). Voz de salida `azure-personal` (clon ~1 min) o `azure-custom` (Custom Neural Voice, estudio). **Acceso limitado** (intake aka.ms/customneural). Matiz: el clon se aplica en la ruta de salida TTS → sugiere cascada en esa parte; no 100% confirmado que el audio nativo conserve el clon.

## Avisos / caveats

- **S2S nativo + clon:** en S2S puro la voz suele ser propia del modelo; OpenAI sí lista Custom Voices como salida válida de Realtime; en Azure el clon va por la ruta TTS (parece cascada ahí). Hume es el S2S nativo + clon self-serve más limpio.
- **Instant vs Professional:** ambos → ElevenLabs, Cartesia, Resemble, Play.ai, Azure, Inworld. Solo instant → Hume. Solo professional (estudio, consentimiento) → OpenAI.
- **Acceso restringido al clon:** OpenAI Custom Voices y Azure Custom/Personal Voice **no son self-serve** públicos. Resemble limita el WS de streaming a Business+.
- **Consentimiento/verificación** exigido y verificable: OpenAI, Azure, ElevenLabs Professional, Resemble Professional. Solo aceptar términos: clonado rápido de los demás. (Legal: clonar voz exige consentimiento del titular.)
- **Latencia:** ningún proveedor publica una cifra oficial voz→voz e2e del pipeline completo; las cifras 75-250ms son solo del **componente TTS** (time-to-first-audio), no del round-trip (que suma VAD/STT + LLM y depende del LLM en cascada).
- **Precios incomparables directamente:** por minuto de agente, por carácter/crédito, por segundo o por token; en cascada el LLM suele ir aparte (salvo ElevenLabs, que hoy lo absorbe).
- **Fuera de alcance / sin confirmar:** LMNT, Neuphonic, Smallest.ai (TTS streaming con instant cloning, pero componentes no agentes S2S), Speechify (read-aloud), Kyutai/Moshi (open-source self-hosted), Respeecher, Fish Audio.

## Fuentes
Documentación oficial de cada proveedor (elevenlabs.io/docs, cartesia.ai, resemble.ai, play.ai/docs,
platform.openai.com, learn.microsoft.com Azure AI Speech, dev.hume.ai, inworld.ai, AWS Bedrock Nova Sonic).
Verificado el cruce realtime+clonación con un agente verificador independiente por proveedor.
