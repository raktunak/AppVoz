# Revisión técnica del proyecto AppVoz

**Fecha:** 23 de junio de 2026  
**Alcance:** arquitectura, código backend, persistencia, RAG, voz en tiempo real, telefonía, agenda, frontend, configuración, pruebas, seguridad, despliegue y mantenibilidad.

## Resumen ejecutivo

AppVoz es un prototipo técnicamente prometedor y con una visión de producto interesante. La combinación de voz en tiempo real, RAG, telefonía, agenda, persistencia y onboarding demuestra trabajo de producto real, no solamente una maqueta visual.

Valoración orientativa del estado actual:

- **8/10 como laboratorio o MVP interno.**
- **4/10 como servicio preparado para publicarse o manejar usuarios reales.**

El principal riesgo no está en la arquitectura de IA o de voz, sino en la frontera de confianza: el sistema todavía funciona como una demo que confía en todos los clientes. Antes de ampliar funcionalidades conviene consolidar seguridad, aislamiento de usuarios, pruebas, migraciones y operación.

## Aspectos positivos que conviene conservar

### Arquitectura y organización

- La separación por módulos es razonable: voz, Gemini Live, Telnyx, persistencia, RAG, embeddings, agenda y onboarding tienen responsabilidades reconocibles.
- El código usa SQL parametrizado, reduciendo el riesgo de inyección SQL.
- Las escrituras importantes usan transacciones mediante `engine.begin()`.
- El acceso síncrono a Google Calendar se desplaza a hilos mediante `asyncio.to_thread()`, evitando bloquear directamente el event loop.
- `subject_id` está presente desde una fase temprana en el diseño del RAG y en varias entidades de persistencia.
- La instrumentación de latencias, turnos y consumo es una buena base para observar costes y calidad.
- La validación del progreso del Canva 4G se decide de forma determinista en código, en lugar de confiar totalmente en la decisión de un LLM.
- El frontend construye la mayor parte del contenido dinámico con `textContent`, lo que reduce el riesgo de XSS.
- El fichero `.env` está ignorado por Git y no aparece versionado.

### Producto

- Existe una propuesta diferenciada: tutor o asistente por voz basado en contenido propio, con memoria, telefonía y agenda.
- Las interfaces de banco de voz, llamada y onboarding permiten validar verticales y configuraciones rápidamente.
- La capa de servicios telefónicos anticipa una arquitectura multi-vertical.
- La persistencia de turnos, métricas y sesiones puede convertirse en una ventaja importante para evaluación y mejora del producto.

## Hallazgos y mejoras prioritarias

## 1. Seguridad, autenticación y privacidad — prioridad crítica

### Situación actual

El despliegue de Cloud Run permite acceso no autenticado mediante `--allow-unauthenticated` en `cloudbuild.yaml`. Esto puede ser adecuado para webhooks o páginas públicas concretas, pero actualmente el mismo servicio expone también rutas de administración, consulta de conversaciones y operaciones que generan coste.

No se observa una capa general de autenticación ni autorización. Entre las operaciones expuestas se encuentran:

- Ingesta de contenido y generación de embeddings mediante `POST /ingest`.
- Búsqueda RAG mediante `POST /search`.
- Acceso a Gemini, TTS y otros servicios de pago mediante rutas HTTP y WebSockets.
- Consulta de sesiones por `user_id`.
- Consulta del detalle de cualquier conversación mediante un `session_id` entero.
- Lectura y modificación de la configuración telefónica.
- Creación, modificación y borrado de servicios telefónicos.
- Reinicio y consulta del Canva 4G.
- Modificación del `system_instruction`, modelo, voz y parámetros de una llamada.

El endpoint `GET /api/live/sessions/{session_id}` recupera una sesión solamente por su identificador. No recibe ni verifica el propietario. Un cliente que conozca o pruebe identificadores correlativos podría acceder a conversaciones ajenas.

El `user_id` del navegador se genera y guarda en `localStorage`, pero esto no constituye autenticación. Cualquier cliente puede enviar otro `user_id` y consultar los datos asociados.

### Webhook y WebSocket de Telnyx

El propio código indica que todavía no se verifica la firma Ed25519 del webhook de Telnyx. Esto debe considerarse crítico antes de conectar telefonía real.

El webhook utiliza el encabezado `Host` para construir la URL WebSocket si no existe un `TELNYX_PUBLIC_WS_URL` configurado. Sin validación de firma y con un host controlable, una petición manipulada podría provocar comportamientos no deseados. Además, el WebSocket `/ws/telnyx` acepta conexiones sin autenticar el origen del media stream.

### Datos personales

El sistema guarda o procesa:

- Transcripciones completas.
- Respuestas del asistente.
- Números de teléfono.
- Datos de agenda.
- Posibles nombres y datos personales.
- Resúmenes, temas y dudas del usuario.
- Contenido estratégico y personal del Canva 4G.

El número de teléfono aparece también en registros de aplicación. Esto aumenta la exposición de datos personales.

No se ha identificado una política técnica de:

- Consentimiento informado.
- Retención de conversaciones.
- Borrado a petición del usuario.
- Minimización o anonimización.
- Separación entre datos de prueba y datos reales.
- Cifrado o protección adicional de campos sensibles.
- Auditoría de accesos administrativos.

### Recomendaciones

1. Separar claramente tres superficies:
   - API pública estrictamente necesaria.
   - API autenticada de usuario.
   - API administrativa.
2. Introducir autenticación real y una identidad de usuario verificable.
3. Comprobar propiedad o pertenencia al tenant en todas las lecturas y escrituras.
4. Evitar identificadores enteros predecibles en recursos expuestos o combinarlos con controles de autorización sólidos.
5. Verificar la firma Ed25519, timestamp y antigüedad de todos los webhooks de Telnyx.
6. Autenticar o validar el media stream de Telnyx.
7. Configurar explícitamente la URL pública de Telnyx; no derivarla libremente del encabezado `Host` en producción.
8. Proteger las rutas administrativas de configuración y servicios.
9. Añadir rate limiting por usuario, IP, tenant y operación.
10. Añadir cuotas de uso para Gemini, embeddings, TTS y Live API.
11. No registrar números de teléfono completos ni contenido sensible salvo necesidad justificada.
12. Definir políticas de consentimiento, retención, exportación y borrado.
13. Añadir cabeceras de seguridad y una política de orígenes explícita para HTTP y WebSocket.
14. Gestionar secretos mediante Secret Manager o un mecanismo equivalente, con rotación y mínimo privilegio.

## 2. Pruebas automatizadas y CI — prioridad crítica

### Resultado de la revisión

El código Python de `backend/app` compila correctamente con `compileall`.

Sin embargo, `pytest` no consigue completar la recopilación de pruebas en el entorno revisado:

- `_4g_test.py` falla porque no está disponible `google.genai`.
- `_agenda_test.py` falla porque no está disponible `loguru`.

`loguru` se importa en diversos módulos, pero no aparece declarado directamente en `backend/requirements.txt`. Puede llegar de forma transitiva a través de otra biblioteca, pero depender de una dependencia transitiva es frágil.

Los ficheros `_4g_test.py` y `_agenda_test.py` se comportan más como scripts manuales o pruebas de integración con efectos externos que como una suite automatizada aislada. La prueba de agenda puede crear y borrar eventos reales.

No se observa una configuración formal de:

- Pytest.
- Cobertura.
- Ruff o linting equivalente.
- Comprobación de tipos.
- Tests en Cloud Build antes del despliegue.
- Entorno separado para pruebas.

### Recomendaciones

1. Crear una suite `tests/` convencional.
2. Añadir pruebas unitarias para:
   - `chunk_text`.
   - Validación de parámetros.
   - Merge y completitud de secciones del Canva.
   - Normalización de fechas y zonas horarias.
   - Resolución de servicios telefónicos.
   - Construcción y filtrado de configuraciones.
   - Formateo de vectores.
3. Simular Gemini, Google Calendar, Telnyx, TTS y la base de datos cuando corresponda.
4. Añadir tests de API con el cliente de pruebas de FastAPI.
5. Añadir tests de WebSocket para voz, Gemini Live y onboarding.
6. Probar explícitamente el aislamiento entre usuarios y `subject_id`.
7. Probar límites de tamaño, timeouts, desconexiones y mensajes inválidos.
8. Separar las pruebas manuales que usan servicios reales mediante una marca como `integration`.
9. Crear una base de datos efímera para integración.
10. Añadir CI con, como mínimo:
    - Instalación reproducible.
    - `pytest`.
    - Ruff.
    - Comprobación de tipos gradual.
    - `docker compose config`.
    - Construcción de la imagen.
11. Impedir el despliegue si fallan las comprobaciones.

## 3. Dependencias y reproducibilidad — prioridad alta

### Situación actual

Algunas dependencias están fijadas a una versión concreta, pero otras no:

- `httpx` no tiene versión fijada.
- `google-genai` no tiene versión fijada.
- Pipecat usa un mínimo abierto `>=1.3.0`.
- Google TTS y Google Calendar usan rangos abiertos.
- `loguru` no está declarado directamente.

Esto puede producir imágenes diferentes en dos builds realizados en fechas distintas y provocar incompatibilidades, especialmente en una zona tan cambiante como Gemini Live y Pipecat.

### Recomendaciones

1. Declarar todas las dependencias directas, incluido `loguru`.
2. Generar un fichero de bloqueo reproducible.
3. Separar dependencias de producción, desarrollo y pruebas.
4. Fijar versiones compatibles de `google-genai`, Pipecat y sus extras.
5. Automatizar actualizaciones de dependencias con pruebas.
6. Añadir escaneo de vulnerabilidades de dependencias e imagen Docker.

## 4. Base de datos, esquema y migraciones — prioridad alta

### Situación actual

El esquema se crea actualmente mediante dos mecanismos:

- `db/init/01_init.sql` crea `pgvector`, `chunks` e índices en el primer arranque del contenedor.
- El startup de FastAPI ejecuta DDL idempotente para sesiones, turnos, memoria, servicios, configuración telefónica y Canva.

Este enfoque sirve durante el prototipo inicial, pero no mantiene una historia de migraciones ni permite modificar columnas, restricciones o datos con seguridad en producción.

Si el startup no puede crear una tabla o índice, la aplicación puede no arrancar. Además, las tablas de `db/init` solamente se crean automáticamente cuando se inicializa por primera vez el volumen de PostgreSQL.

### Problema de modelado del Canva

La tabla `canva_4g` utiliza `user_id` como clave primaria, aunque también guarda `subject_id`. Esto significa que un usuario solamente puede tener un Canva en total. Guardar otro `subject_id` sobrescribe el anterior.

La clave debería ser `(user_id, subject_id)` o existir un identificador de Canva independiente con restricciones adecuadas.

### Aislamiento multi-tenant

El uso de `subject_id` como comentario de “tenant” no garantiza aislamiento por sí mismo. El cliente puede elegir libremente el `subject_id` en distintas rutas. Se necesita derivar el tenant desde la identidad autenticada y aplicarlo en todas las consultas.

### Recomendaciones

1. Incorporar Alembic o una herramienta equivalente.
2. Crear una migración inicial que represente todo el esquema actual.
3. Eliminar progresivamente el DDL de producción del evento de startup.
4. Corregir la clave de `canva_4g`.
5. Añadir restricciones de unicidad para turnos, por ejemplo `(session_id, idx)`, si el modelo lo requiere.
6. Revisar índices según consultas reales.
7. Añadir políticas explícitas de borrado en cascada y retención.
8. Considerar Row Level Security si PostgreSQL va a ser una barrera adicional entre tenants.
9. Versionar el modelo de configuración JSON para poder migrarlo.

## 5. Validación de entradas, límites y control de costes — prioridad alta

### Ingesta y RAG

`POST /ingest` acepta un texto sin límite explícito. Un documento muy grande puede provocar:

- Gran número de chunks.
- Coste elevado de embeddings.
- Uso excesivo de memoria.
- Transacciones largas.
- Saturación de conexiones.

La inserción de chunks se hace de uno en uno dentro de una transacción. Es correcta funcionalmente, pero puede ser ineficiente para documentos grandes.

### Voz HTTP

En `POST /voice/turn`:

- `k` no tiene el límite de 1 a 20 aplicado en `SearchRequest`.
- Si no llega `text_input` ni `audio`, se intenta ejecutar `audio.read()` sobre `None`.
- No hay límite explícito para el tamaño o duración del audio.
- La forma y contenido del archivo no se validan antes de enviarlo al proveedor.

### WebSockets

Los WebSockets aceptan parámetros y configuración enviados por el cliente:

- `subject_id`.
- `user_id`.
- Modelo.
- Voz.
- Instrucción del sistema.
- Valores VAD.
- Audio de tamaño y duración potencialmente ilimitados.

Aunque parte de la configuración se filtra, faltan límites generales de duración de sesión, bytes, mensajes por segundo y gasto.

### Endpoints con diccionarios genéricos

Varias rutas reciben `payload: dict`. Esto reduce la documentación automática y dificulta asegurar tipos, longitudes, formatos y compatibilidad futura.

### Recomendaciones

1. Crear modelos Pydantic específicos para cada operación.
2. Limitar longitud de textos, nombres, rutas, identificadores e instrucciones del sistema.
3. Limitar tamaño, duración y formato del audio.
4. Limitar duración total de cada llamada o sesión.
5. Limitar mensajes por segundo y conexiones simultáneas.
6. Validar `k` de forma coherente en todas las rutas.
7. Procesar embeddings por lotes con límites controlados.
8. Añadir timeouts a llamadas externas.
9. Establecer presupuestos por usuario y tenant.
10. Devolver códigos HTTP correctos:
    - `400` para peticiones semánticamente inválidas.
    - `401/403` para autenticación y autorización.
    - `404` para recursos inexistentes.
    - `409` para conflictos como rutas duplicadas.
    - `422` para validación estructural.
    - `429` para cuotas o rate limiting.
11. Evitar devolver detalles internos de excepciones al cliente.

## 6. Fiabilidad de tareas asíncronas y WebSockets — prioridad media/alta

### Tareas de resumen no supervisadas

Al finalizar una conversación, el resumen se lanza mediante `asyncio.create_task()`. La tarea no se registra, no se espera y no se reintenta.

En Cloud Run, la instancia puede perder CPU o finalizar después de cerrar la petición o conexión. El resumen y la actualización de memoria pueden quedar sin ejecutar.

### Cancelación de tareas

En los relays se crean tareas para los dos sentidos del audio y se usa `FIRST_COMPLETED`. Las tareas pendientes se cancelan, pero no se espera formalmente su finalización. Esto puede dejar excepciones sin consumir, recursos abiertos o cierres incompletos.

### Manejo de excepciones

Hay numerosos bloques `except Exception`. Algunos son apropiados para limpieza defensiva, pero otros ocultan fallos y continúan con un estado incompleto. En ciertos casos el cliente recibe el texto de una excepción interna.

### Recomendaciones

1. Mover los resúmenes a una cola persistente de trabajos.
2. Añadir reintentos idempotentes y estado de trabajo.
3. Si se mantiene `create_task`, registrar las tareas, capturar sus resultados y cerrarlas ordenadamente en el shutdown.
4. Esperar las tareas canceladas mediante `gather(..., return_exceptions=True)`.
5. Usar timeouts explícitos en conexiones, handshakes y llamadas a proveedores.
6. Clasificar errores recuperables y no recuperables.
7. Evitar silencios generales; registrar contexto estructurado sin datos sensibles.
8. Diseñar reconexión e idempotencia para webhooks repetidos.

## 7. Memoria conversacional — prioridad media/alta

La documentación del módulo describe una “memoria acumulada”, pero la operación `ON CONFLICT` reemplaza `resumen`, `temas` y `dudas` por los valores de la última sesión. Solamente incrementa `n_sesiones`.

Por tanto, la memoria actual no es realmente acumulativa y puede olvidar información anterior.

### Opciones de mejora

1. Guardar una memoria por sesión y generar una memoria consolidada aparte.
2. Pasar la memoria anterior al modelo para producir una nueva consolidación.
3. Mantener hechos estructurados con procedencia, confianza y fecha.
4. Separar:
   - Perfil estable.
   - Temas tratados.
   - Objetivos.
   - Dudas pendientes.
   - Preferencias.
5. Permitir al usuario consultar, corregir y borrar su memoria.
6. No mezclar tenants o materias aunque compartan `user_id`.

## 8. Observabilidad y operación — prioridad media

### Estado actual

Existen métricas de latencia dentro de las sesiones y registros útiles para depuración. Es una buena base, pero falta una estrategia operacional completa.

El endpoint `/health` solamente devuelve `ok`; no comprueba base de datos ni proveedores. `/health/db` sí consulta PostgreSQL y pgvector, pero puede fallar con una excepción sin una respuesta de salud estructurada.

### Recomendaciones

1. Separar:
   - Liveness: el proceso funciona.
   - Readiness: dependencias mínimas disponibles.
2. Añadir métricas de:
   - Conexiones WebSocket activas.
   - Duración de llamadas.
   - Errores por proveedor.
   - Coste y tokens por tenant.
   - Latencia por etapa.
   - Fallos de persistencia y resumen.
   - Cola y reintentos.
3. Usar logs estructurados con un identificador de correlación.
4. Enmascarar teléfonos y contenido sensible.
5. Añadir trazas distribuidas para las llamadas externas.
6. Configurar alertas de coste, errores y saturación.
7. Crear cuadros de mando de calidad de conversación y negocio.

## 9. Docker y despliegue — prioridad media

### Hallazgos

- `docker compose config` es válido.
- El contenedor ejecuta Uvicorn con `--reload` tanto en Dockerfile como en el entorno de desarrollo de Compose.
- `--reload` no es adecuado en producción.
- Cloud Build construye y despliega directamente sin ejecutar tests.
- El servicio se publica sin autenticación global.
- La imagen instala herramientas de compilación y después las conserva, aumentando tamaño y superficie de ataque.
- La aplicación no muestra una estrategia explícita de ejecución como usuario no root.

### Recomendaciones

1. Separar comandos de desarrollo y producción.
2. Eliminar `--reload` del Dockerfile de producción.
3. Utilizar una imagen multi-stage si es posible.
4. Ejecutar como usuario no privilegiado.
5. Añadir `HEALTHCHECK` o integrar correctamente las sondas de Cloud Run.
6. Ejecutar tests antes de build y deploy.
7. Escanear la imagen.
8. Fijar imágenes base por digest cuando se necesite máxima reproducibilidad.
9. Revisar concurrencia, CPU, memoria, timeout y mínimo/máximo de instancias de Cloud Run para WebSockets largos.
10. Separar, si resulta necesario, el plano administrativo del relay de voz público.

## 10. Frontend y seguridad del navegador — prioridad media

La mayoría de los valores de usuario se insertan con `textContent`, lo cual es positivo.

Hay al menos una construcción mediante `innerHTML` para el enlace de un evento de Calendar. Aunque el valor procede normalmente de Google Calendar, conviene evitar construir HTML con concatenación y crear el elemento `<a>` mediante APIs DOM, validando además el protocolo de la URL.

El identificador del usuario se guarda en `localStorage`. Esto sirve para continuidad informal de una demo, pero:

- Se pierde al limpiar almacenamiento.
- Se puede modificar manualmente.
- Puede ser leído por cualquier script ejecutado en el mismo origen.
- No demuestra identidad ni propiedad.

### Recomendaciones

1. Sustituir identificadores locales por sesiones autenticadas.
2. Eliminar concatenaciones con `innerHTML` para datos dinámicos.
3. Añadir Content Security Policy.
4. Añadir protección frente a clickjacking y otras cabeceras de seguridad.
5. Diseñar estados de error y reconexión más explícitos.
6. Evitar que el panel administrativo sea accesible desde la misma superficie pública sin protección.

## 11. Documentación y coherencia del proyecto — prioridad media

El README describe RAG, recuperación y voz como próximas fases, aunque buena parte de estas capacidades ya está implementada. Tampoco refleja adecuadamente:

- Gemini Live.
- Telefonía Telnyx.
- Servicios multi-vertical.
- Onboarding 4G.
- Agenda con Google Calendar.
- Persistencia y memoria.
- Despliegue real.
- Modelo de seguridad.
- Pruebas y limitaciones.

La estructura del repositorio contiene dos carpetas prácticamente equivalentes, `investigacion` e `investigación`. Esto puede generar confusión y problemas en scripts, enlaces o sistemas con distinta normalización Unicode.

También existe documentación extensa de visión y producto, pero falta una fuente técnica única que explique qué está implementado, qué es experimental y qué no debe utilizarse todavía con datos reales.

### Recomendaciones

1. Actualizar el README al estado real.
2. Añadir una guía de arquitectura.
3. Documentar flujos de datos y fronteras de confianza.
4. Añadir instrucciones reproducibles de desarrollo y pruebas.
5. Documentar variables de entorno, indicando cuáles son secretas.
6. Crear un registro de decisiones de arquitectura.
7. Unificar las carpetas `investigacion` e `investigación` con cuidado de no perder archivos.
8. Etiquetar claramente funcionalidades como demo, experimental o producción.
9. Documentar costes esperados y límites.

## 12. Diseño del producto y alcance — prioridad estratégica

El proyecto incluye varias líneas a la vez:

- Tutor RAG por voz.
- Banco de pruebas de voces y modelos.
- Recepcionista o agente telefónico multi-vertical.
- Onboarding estratégico 4G.
- Memoria de usuario.
- Agenda.

Esta amplitud es valiosa para explorar, pero aumenta la superficie técnica y de producto. Antes de añadir nuevas capacidades conviene decidir cuál es el flujo principal que debe alcanzar calidad de producción.

### Recomendación

Elegir un vertical y una métrica principal, por ejemplo:

- Finalización del onboarding 4G.
- Citas válidas creadas por llamadas.
- Resolución correcta de preguntas sobre un corpus.

Después, endurecer ese recorrido completo antes de extender otros verticales.

## Riesgos concretos resumidos

| Riesgo | Impacto | Prioridad |
|---|---|---|
| Conversaciones consultables sin autorización suficiente | Exposición de datos personales | Crítica |
| Configuración y servicios telefónicos públicos | Manipulación del producto y llamadas | Crítica |
| Webhook Telnyx sin firma | Peticiones falsas y abuso | Crítica |
| Acceso público a operaciones de IA | Costes inesperados y denegación de servicio | Crítica |
| Falta de pruebas automatizadas fiables | Regresiones frecuentes | Crítica |
| Ausencia de migraciones | Riesgo de rotura o pérdida al evolucionar esquema | Alta |
| `canva_4g` limitado a un Canva por usuario | Sobrescritura entre materias | Alta |
| Entradas y audio sin límites suficientes | Coste, memoria y disponibilidad | Alta |
| Tareas de resumen no supervisadas | Pérdida silenciosa de memoria | Media/alta |
| Memoria que reemplaza en vez de acumular | Pérdida funcional de contexto | Media/alta |
| Dependencias abiertas o transitivas | Builds no reproducibles | Alta |
| Falta de política de datos | Riesgo legal y de confianza | Crítica antes de usuarios reales |

## Plan recomendado por fases

## Fase 0 — Contención inmediata

Objetivo: evitar exposición y gasto mientras continúa el desarrollo.

- Restringir acceso al despliegue actual.
- Proteger las rutas administrativas.
- Desactivar o limitar las operaciones costosas públicas.
- Configurar cuotas y alertas de proveedores.
- No conectar telefonía real sin verificar firmas.
- Revisar logs y eliminar datos personales innecesarios.

## Fase 1 — Frontera de confianza

Objetivo: establecer quién puede hacer qué.

- Autenticación.
- Autorización por usuario y tenant.
- Propiedad de sesiones y canvas.
- Firma de webhooks.
- Validación de WebSockets.
- Rate limiting y cuotas.
- Política mínima de consentimiento y borrado.

## Fase 2 — Red de seguridad técnica

Objetivo: poder cambiar el producto sin romperlo silenciosamente.

- Suite de tests.
- Mocks de proveedores.
- Pruebas WebSocket.
- CI obligatorio.
- Dependencias bloqueadas.
- Linting y tipos graduales.

## Fase 3 — Persistencia robusta

Objetivo: evolucionar datos sin riesgo.

- Alembic.
- Migración inicial.
- Corrección de claves y aislamiento.
- Retención y borrado.
- Memoria verdaderamente acumulativa.
- Trabajos persistentes para resúmenes.

## Fase 4 — Operación y escala

Objetivo: entender y controlar el comportamiento en producción.

- Logs estructurados.
- Métricas y trazas.
- Alertas de errores y costes.
- Timeouts y reintentos.
- Configuración de Cloud Run para WebSockets.
- Imagen Docker endurecida.

## Fase 5 — Calidad de producto

Objetivo: optimizar el recorrido principal elegido.

- Evaluaciones automáticas de conversación.
- Métricas de éxito del vertical.
- Pruebas con usuarios.
- Mejora de prompts y recuperación basada en resultados medidos.
- Experiencia de error, reconexión y recuperación.

## Orden de trabajo recomendado

1. Cerrar autenticación, permisos, firma Telnyx y límites.
2. Añadir pruebas automatizadas y CI.
3. Incorporar migraciones.
4. Corregir aislamiento multiusuario y política de datos.
5. Endurecer WebSockets y trabajos en segundo plano.
6. Actualizar documentación y dependencias.
7. Refactorizar módulos grandes cuando exista cobertura.
8. Añadir nuevas funcionalidades solamente después de consolidar el flujo principal.

## Conclusión

AppVoz tiene una base creativa y técnicamente valiosa. La arquitectura demuestra que las piezas principales pueden conversar entre sí: navegador, voz en tiempo real, Gemini, RAG, PostgreSQL, Telnyx y Calendar.

El siguiente salto de calidad no consiste en añadir otra integración, modelo o interfaz. Consiste en convertir la demo en un sistema que conozca sus fronteras: quién entra, qué puede consultar, cuánto puede gastar, qué datos conserva, cómo se recupera de errores y cómo se demuestra que un cambio no rompe lo anterior.

La recomendación general es detener temporalmente la expansión funcional y dedicar una fase explícita a consolidación. Con seguridad, pruebas, migraciones y observabilidad, el proyecto puede pasar de ser una demostración convincente a una plataforma sólida sobre la que sí resulte seguro construir más verticales.
