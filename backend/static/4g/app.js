// Cliente del onboarding 4G: mic → PCM16 16k → WS /ws/4g; recibe audio (24k) + Canva en vivo.
// AGENTES POR BLOQUE sobre UNA sola sesión: cada apartado tiene su botón «▶ Empezar»; al pulsarlo,
// ese 'agente' (con la memoria de lo anterior) coge el testigo → manda {type:'goto', idx} y el backend
// le inyecta su rol en la MISMA línea de audio (la voz no se toca).
const $ = (id) => document.getElementById(id);
let ws, micCtx, micStream, micNode, playCtx, nextTime = 0, sources = [];
let connected = false, micActivo = false;
let SECCIONES = [], ACTIVA = -1, CANVA = {}, BOOKED = null, DONE = new Set();
let curWho = null, curBubble = null;

// ---- identidad persistente (misma clave que el panel /call) ----
function newId() {
  return (crypto && crypto.randomUUID) ? crypto.randomUUID()
    : "u-" + Date.now() + "-" + Math.random().toString(36).slice(2);
}
function getUserId() {
  let id = localStorage.getItem("appvoz_user_id");
  if (!id) { id = newId(); localStorage.setItem("appvoz_user_id", id); }
  return id;
}
function setStatus(s) { $("status").textContent = s; }

// ---- reproducción (PCM16 24kHz) ----
function ensurePlay() {
  if (!playCtx) playCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (playCtx.state === "suspended") playCtx.resume();
}
function playChunk(int16) {
  ensurePlay();
  const f32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 32768;
  const buf = playCtx.createBuffer(1, f32.length, 24000);
  buf.copyToChannel(f32, 0);
  const src = playCtx.createBufferSource();
  src.buffer = buf; src.connect(playCtx.destination);
  const now = playCtx.currentTime;
  if (nextTime < now) nextTime = now + 0.02;
  src.start(nextTime); nextTime += buf.duration;
  sources.push(src);
  src.onended = () => { sources = sources.filter((s) => s !== src); };
}
function flushPlayback() {
  sources.forEach((s) => { try { s.stop(); } catch (e) {} });
  sources = []; nextTime = 0;
}

// ---- captura: float32 -> PCM16 16kHz ----
function downsample(buf, srcRate, dstRate) {
  if (dstRate >= srcRate) return buf;
  const ratio = srcRate / dstRate, n = Math.round(buf.length / ratio), out = new Float32Array(n);
  let oi = 0, ii = 0;
  while (oi < n) {
    const next = Math.round((oi + 1) * ratio);
    let sum = 0, c = 0;
    for (; ii < next && ii < buf.length; ii++) { sum += buf[ii]; c++; }
    out[oi++] = c ? sum / c : 0;
  }
  return out;
}
function toPCM16(f32) {
  const dv = new DataView(new ArrayBuffer(f32.length * 2));
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]));
    dv.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return dv.buffer;
}

// ---- transcripción (panel derecho) ----
function addChunk(who, text) {
  if (who !== curWho || !curBubble) {
    curBubble = document.createElement("div");
    curBubble.className = "msg " + who;
    const w = document.createElement("div");
    w.className = "who"; w.textContent = who === "user" ? "Tú" : "Guía";
    const b = document.createElement("div"); b.className = "body";
    curBubble.appendChild(w); curBubble.appendChild(b);
    $("chat").appendChild(curBubble); curWho = who;
  }
  curBubble.querySelector(".body").textContent =
    (curBubble.querySelector(".body").textContent + " " + text).trim();
  $("chat").scrollTop = $("chat").scrollHeight;
}

// ---- stepper (izquierda) — done por DATOS (DONE), clic = iniciar ese bloque ----
function renderStepper() {
  const nav = $("stepper"); nav.innerHTML = "";
  SECCIONES.forEach((s, i) => {
    const done = DONE.has(s.key);
    const el = document.createElement("div");
    el.className = "step" + (done ? " done" : "") + (i === ACTIVA && !done ? " active" : "");
    el.style.cursor = "pointer";
    el.onclick = () => iniciarBloque(i);
    const dot = document.createElement("div");
    dot.className = "dot"; dot.textContent = done ? "✓" : (i + 1);
    const lbl = document.createElement("div"); lbl.textContent = s.titulo;
    el.appendChild(dot); el.appendChild(lbl);
    nav.appendChild(el);
  });
}

// ---- Canva (centro) ----
function chip(txt, sub) {
  const c = document.createElement("span");
  c.className = "chip"; c.textContent = txt;
  if (sub) { const s = document.createElement("small"); s.textContent = " · " + sub; c.appendChild(s); }
  return c;
}
function renderSeccion(card, seccion, datos) {
  datos = datos || {};
  const wrap = document.createElement("div");
  if (seccion.tipo === "lista") {
    if (seccion.pregunta) {
      const q = document.createElement("div"); q.className = "seccion-q"; q.textContent = seccion.pregunta;
      wrap.appendChild(q);
    }
    const arr = datos[seccion.lista] || [];
    if (!arr.length) {
      const e = document.createElement("div"); e.className = "empty";
      e.textContent = "Aún nada — lo iremos añadiendo"; wrap.appendChild(e);
    } else {
      arr.forEach((it) => wrap.appendChild(chip(it.valor || it.nombre || it, it.explicacion || it.pilar)));
    }
  } else {
    (seccion.apartados || []).forEach((a) => {
      const v = datos[a.campo];
      const row = document.createElement("div");
      row.className = "apart" + (v ? " done" : "");
      const q = document.createElement("div"); q.className = "apart-q"; q.textContent = a.pregunta || a.etiqueta;
      const val = document.createElement("div"); val.className = "apart-a"; val.textContent = v ? v : "pendiente";
      row.appendChild(q); row.appendChild(val);
      wrap.appendChild(row);
    });
  }
  card.appendChild(wrap);
  if (seccion.key === "bloque" && BOOKED) {
    const b = document.createElement("div");
    b.className = "booked" + (BOOKED.ok ? "" : " err");
    if (BOOKED.ok && BOOKED.event) {
      b.innerHTML = "✓ Agendado en tu Calendar — " +
        (BOOKED.event.html_link ? '<a href="' + BOOKED.event.html_link + '" target="_blank">ver evento</a>' : "");
    } else { b.textContent = "No se pudo agendar: " + (BOOKED.error || "error"); }
    card.appendChild(b);
  }
}
// ---- prompt por agente (editable) + referencia de lo que se inyecta ----
function promptKey(key) { return "4g_prompt_" + key; }
function guionDefault(s) {   // por defecto = las preguntas literales del bloque
  if (s.tipo === "lista") return s.pregunta || "";
  return (s.apartados || []).filter((a) => a.pregunta).map((a) => "«" + a.pregunta + "»").join("  ");
}
function guionDe(s) { return localStorage.getItem(promptKey(s.key)) || guionDefault(s); }
function inyeccionPreview(s, guion) {   // boceto fiel de _inyectar_agente (referencia)
  return "(Ahora céntrate SOLO en la fase «" + s.titulo + "». [1er bloque: preséntate como Faro; resto: " +
    "enlaza sin saludar de nuevo.] Para dar continuidad, la persona YA te ha contado: {resumen de lo " +
    "capturado}. Haz estas preguntas, una a una y TAL CUAL, esperando respuesta a cada una: " +
    (guion || "—") + " Cuando tengas TODAS, NO sigas con otra fase: invita a pulsar el siguiente y espera.)";
}
function promptBox(s) {
  const det = document.createElement("details"); det.className = "promptbox";
  const sum = document.createElement("summary"); sum.textContent = "🔧 Prompt del agente";
  const lblE = document.createElement("div"); lblE.className = "prompt-lbl";
  lblE.textContent = "Editable (se usa al iniciar este bloque):";
  const ta = document.createElement("textarea"); ta.className = "prompt-edit"; ta.rows = 3;
  ta.value = guionDe(s);
  const lblR = document.createElement("div"); lblR.className = "prompt-lbl";
  lblR.textContent = "Lo que se inyecta (referencia):";
  const ref = document.createElement("pre"); ref.className = "prompt-ref";
  const refresh = () => { ref.textContent = inyeccionPreview(s, ta.value); };
  ta.oninput = () => { localStorage.setItem(promptKey(s.key), ta.value); refresh(); };
  refresh();
  det.appendChild(sum); det.appendChild(lblE); det.appendChild(ta);
  det.appendChild(lblR); det.appendChild(ref);
  return det;
}
function hayDatos(s) {   // ¿el bloque tiene ALGO capturado (a medias) aunque no esté completo?
  const d = CANVA[s.key]; if (!d) return false;
  if (s.tipo === "lista") return ((d[s.lista] || []).length > 0);
  return (s.apartados || []).some((a) => d[a.campo]);
}
function renderCanva() {
  const grid = $("grid"); grid.innerHTML = "";
  let firstPending = SECCIONES.findIndex((s) => !DONE.has(s.key));
  if (firstPending < 0) firstPending = SECCIONES.length;   // todo hecho
  SECCIONES.forEach((s, i) => {
    const done = DONE.has(s.key);
    const enCurso = (i === ACTIVA && !done);   // 'done' manda: un bloque completo NO sigue activo
    const habilitado = done || enCurso || i === firstPending;   // ORDEN: solo el actual o repasar hechos
    const card = document.createElement("div");
    card.className = "cv" + (enCurso ? " active" : "") + (done ? " done" : "") + (habilitado ? "" : " locked");
    const head = document.createElement("div"); head.className = "cv-head";
    const h = document.createElement("h3"); h.textContent = s.titulo;
    const btn = document.createElement("button");
    // Estados: completo → ✓ Repasar · en curso → ■ Pausar · a medias → ▶ Seguir · vacío → ▶ Empezar
    let txt = "▶ Empezar", cls = "", onclick = () => iniciarBloque(i);
    if (done) { txt = "✓ Repasar"; cls = " is-done"; }
    else if (enCurso) { txt = "■ Pausar"; cls = " pausar"; onclick = () => pausar(); }
    else if (hayDatos(s)) { txt = "▶ Seguir"; cls = " seguir"; }
    btn.className = "go" + cls;
    btn.textContent = txt;
    btn.disabled = !habilitado;
    if (habilitado) btn.onclick = onclick;
    head.appendChild(h); head.appendChild(btn);
    card.appendChild(head);
    renderSeccion(card, s, CANVA[s.key]);
    card.appendChild(promptBox(s));
    grid.appendChild(card);
  });
}

// ---- WebSocket ----
function handleMsg(j, resolve) {
  switch (j.type) {
    case "ready":
      SECCIONES = j.secciones || []; CANVA = j.canva || {}; BOOKED = null;
      DONE = new Set(j.completas || []); connected = true;
      renderStepper(); renderCanva();
      setStatus("Conectado. Pulsa «▶ Empezar» en un apartado.");
      if (resolve) resolve();
      break;
    case "canva":
      CANVA = j.canva || CANVA; if (j.completas) DONE = new Set(j.completas);
      renderStepper(); renderCanva(); break;
    case "cerrado": {   // bloque completo: Faro ya invitó → dejamos de escuchar y queda ✓ (se cierra solo)
      micActivo = false; ACTIVA = -1; renderStepper(); renderCanva();
      const sec = SECCIONES.find((s) => s.key === j.key);
      setStatus("✓ «" + (sec ? sec.titulo : "Apartado") + "» lista. Pulsa otro apartado cuando quieras.");
      break;
    }
    case "user": addChunk("user", j.text); break;
    case "bot": addChunk("bot", j.text); break;
    case "interrupted": flushPlayback(); curWho = null; break;
    case "booked": BOOKED = j; renderCanva(); break;
    case "error": setStatus("Error: " + (j.detail || "")); break;
  }
}

async function connect() {
  ensurePlay();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/4g`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { ws.send(JSON.stringify({ type: "config", user_id: getUserId() })); };
  const ready = new Promise((resolve, reject) => {
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") { handleMsg(JSON.parse(ev.data), resolve); }
      else { playChunk(new Int16Array(ev.data)); }
    };
    ws.onerror = () => { setStatus("Error de conexión."); reject(new Error("ws error")); };
  });
  ws.onclose = () => { connected = false; micActivo = false; ACTIVA = -1; renderStepper(); renderCanva(); };
  await ready;

  // micrófono continuo: el VAD del backend decide el turno (este bloque es el que daba la voz fina).
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  micCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = micCtx.createMediaStreamSource(micStream);
  micNode = micCtx.createScriptProcessor(4096, 1, 1);
  const silent = micCtx.createGain(); silent.gain.value = 0;
  micNode.onaudioprocess = (e) => {
    if (!ws || ws.readyState !== 1) return;
    if (!micActivo) return;   // bloque cerrado: no escuchar hasta que el usuario abra otro apartado
    // Anti-eco: no enviar el micro mientras Faro está SONANDO (cola hasta nextTime).
    if (playCtx && playCtx.currentTime < nextTime + 0.15) return;
    const ds = downsample(e.inputBuffer.getChannelData(0), micCtx.sampleRate, 16000);
    ws.send(toPCM16(ds));
  };
  src.connect(micNode); micNode.connect(silent); silent.connect(micCtx.destination);
}

// Inicio MANUAL de un bloque: conecta si hace falta y manda goto → el agente de ese bloque toma el testigo.
async function iniciarBloque(idx) {
  if (!connected) {
    setStatus("Conectando…");
    try { await connect(); } catch (e) { setStatus("No pude conectar: " + e); stop(); return; }
  }
  if (!ws || ws.readyState !== 1) { setStatus("Conexión no lista; pulsa de nuevo."); return; }
  const s = SECCIONES[idx];
  const repasar = !!(s && DONE.has(s.key));   // bloque YA completo → modo «Repasar» (solo ofrecer cambios)
  ws.send(JSON.stringify({ type: "goto", idx, guion: s ? guionDe(s) : "", repasar }));
  micActivo = true; ACTIVA = idx; curWho = null; curBubble = null;
  renderStepper(); renderCanva();
  setStatus((repasar ? "Repasando «" : "Hablando con el agente de «") +
    (SECCIONES[idx] ? SECCIONES[idx].titulo : "") + "» — escucha y responde.");
}

function stop() {
  connected = false; micActivo = false;
  try { micNode && micNode.disconnect(); } catch (e) {}
  try { micStream && micStream.getTracks().forEach((t) => t.stop()); } catch (e) {}
  try { micCtx && micCtx.close(); } catch (e) {}
  try { ws && ws.close(); } catch (e) {}
  flushPlayback();
  micNode = micStream = micCtx = null; ws = null; ACTIVA = -1;
  renderStepper(); renderCanva();
  setStatus("Sesión finalizada. Tu Canva queda guardado.");
}

// Pausar el apartado en curso SIN completarlo: cierra la escucha (los datos ya se guardan cada turno);
// el bloque queda «a medias» → botón «▶ Seguir», y al retomarlo el agente pregunta solo lo que falta.
function pausar() {
  const s = SECCIONES[ACTIVA];
  stop();
  setStatus("⏸ «" + (s ? s.titulo : "Apartado") + "» en pausa — pulsa «▶ Seguir» cuando quieras retomarlo.");
}

// Reiniciar desde cero (para pruebas): borra el Canva del usuario y sus citas de prueba.
$("reset").addEventListener("click", async () => {
  if (connected) { setStatus("Termina la sesión antes de reiniciar."); return; }
  if (!confirm("¿Reiniciar desde cero? Se borrará tu Canva y las citas de prueba de tu Calendar.")) return;
  setStatus("Reiniciando…");
  try {
    const j = await (await fetch("/api/4g/reset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: getUserId() }),
    })).json();
    CANVA = {}; ACTIVA = -1; DONE = new Set(); BOOKED = null; curWho = null; curBubble = null; $("chat").innerHTML = "";
    renderStepper(); renderCanva();
    setStatus("Reiniciado" + (j.eventos_borrados ? ` (${j.eventos_borrados} cita(s) borradas)` : "") +
      ". Pulsa «▶ Empezar» en un apartado.");
  } catch (e) { setStatus("No pude reiniciar: " + e); }
});

// Al cargar: muestra el Canva ya guardado (si hay) y qué bloques están completos (✓).
(async () => {
  try {
    const j = await (await fetch("/api/4g/canva?user_id=" + encodeURIComponent(getUserId()))).json();
    SECCIONES = j.secciones || []; CANVA = j.canva || {}; DONE = new Set(j.completas || []); ACTIVA = -1;
    renderStepper(); renderCanva();
    setStatus("Pulsa «▶ Empezar» en un apartado para que su agente te atienda.");
  } catch (e) { /* sin datos previos */ }
})();
