// Cliente del onboarding 4G — SESIÓN-POR-SECCIÓN: cada apartado del Canva es una conversación
// que el usuario abre/cierra con su botón "Hablar". Un solo WS + un solo micro; por debajo el
// backend cicla la sesión Gemini. mic → PCM16 16k → /ws/4g; recibe audio 24k + Canva en vivo.
const $ = (id) => document.getElementById(id);
let ws, micCtx, micStream, micNode, playCtx, nextTime = 0, sources = [];
let connected = false, micOn = false;
let SECCIONES = [], CANVA = {}, BOOKED = null;
let ACTIVE = -1;            // índice de la sección abierta (-1 = ninguna)
let DONE = new Set();       // keys de secciones completas
let curWho = null, curBubble = null, lastUserBubble = null;

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
    if (who === "user") lastUserBubble = curBubble;
  }
  curBubble.querySelector(".body").textContent =
    (curBubble.querySelector(".body").textContent + " " + text).trim();
  $("chat").scrollTop = $("chat").scrollHeight;
}

// ---- stepper (izquierda) ----
function renderStepper() {
  const nav = $("stepper"); nav.innerHTML = "";
  SECCIONES.forEach((s, i) => {
    const done = DONE.has(s.key), active = i === ACTIVE;
    const el = document.createElement("div");
    el.className = "step" + (done ? " done" : "") + (active ? " active" : "");
    el.style.cursor = "pointer";
    const dot = document.createElement("div");
    dot.className = "dot"; dot.textContent = done ? "✓" : (i + 1);
    const lbl = document.createElement("div"); lbl.textContent = s.titulo;
    el.appendChild(dot); el.appendChild(lbl);
    el.onclick = () => startSection(i);   // saltar a una sección desde el stepper
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
  // Banner de agendado en la sección "Primer bloque".
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
function botonSeccion(i, key) {
  const btn = document.createElement("button");
  if (i === ACTIVE) {
    btn.className = "hablar on"; btn.textContent = "■ Terminar";
    btn.onclick = (e) => { e.stopPropagation(); stopSection(); };
  } else if (DONE.has(key)) {
    btn.className = "hablar rev"; btn.textContent = "✏ Revisar";
    btn.onclick = (e) => { e.stopPropagation(); startSection(i); };
  } else {
    btn.className = "hablar"; btn.textContent = "🎙 Hablar";
    btn.onclick = (e) => { e.stopPropagation(); startSection(i); };
  }
  return btn;
}
function renderCanva() {
  const grid = $("grid"); grid.innerHTML = "";
  SECCIONES.forEach((s, i) => {
    const card = document.createElement("div");
    card.className = "cv" + (i === ACTIVE ? " active" : "") + (DONE.has(s.key) ? " done" : "");
    const head = document.createElement("div"); head.className = "cv-head";
    const h = document.createElement("h3"); h.textContent = s.titulo;
    head.appendChild(h); head.appendChild(botonSeccion(i, s.key));
    card.appendChild(head);
    renderSeccion(card, s, CANVA[s.key]);
    // Desplegable de pruebas: el prompt que se le inyecta a Faro en esta sección.
    if (s.prompt_seccion) {
      const det = document.createElement("details"); det.className = "promptbox";
      const sum = document.createElement("summary"); sum.textContent = "🔧 Prompt de Faro";
      const pre = document.createElement("pre");
      pre.textContent = "— CONDUCCIÓN DE SECCIÓN —\n" + s.prompt_seccion +
        "\n\n— INVITACIÓN A SEGUIR —\n" + (s.prompt_confirmacion || "");
      det.appendChild(sum); det.appendChild(pre); card.appendChild(det);
    }
    grid.appendChild(card);
  });
}

// ---- WebSocket ----
let connectPromise = null;   // memoiza la conexión en curso: evita abrir dos WS a la vez
function connect() {
  if (connectPromise) return connectPromise;
  connectPromise = new Promise((resolve, reject) => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/4g`);
    ws.binaryType = "arraybuffer";
    let settled = false;
    ws.onopen = () => { ws.send(JSON.stringify({ type: "config", user_id: getUserId() })); };
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        const j = JSON.parse(ev.data);
        if (j.type === "ready" && !settled) { settled = true; handleMsg(j); resolve(); }
        else handleMsg(j);
      } else {
        playChunk(new Int16Array(ev.data));
      }
    };
    ws.onerror = () => { setStatus("Error de conexión."); if (!settled) { settled = true; connectPromise = null; reject(new Error("ws")); } };
    ws.onclose = () => {
      connected = false; ACTIVE = -1; connectPromise = null; renderStepper(); renderCanva();
      setStatus("Desconectado. Recarga para continuar.");
    };
  });
  return connectPromise;
}

function tituloDe(i) { return SECCIONES[i] ? SECCIONES[i].titulo : ""; }

function handleMsg(j) {
  switch (j.type) {
    case "ready":
      SECCIONES = j.secciones || []; CANVA = j.canva || {}; DONE = new Set(j.completas || []);
      connected = true; renderStepper(); renderCanva();
      setStatus("Listo. Pulsa «🎙 Hablar» en una sección para empezar.");
      break;
    case "section_started":
      ACTIVE = j.idx; renderStepper(); renderCanva();
      setStatus("Hablando: «" + (SECCIONES[j.idx] ? SECCIONES[j.idx].titulo : "") + "» — escucha a Faro y responde.");
      break;
    case "section_stopped":
      if (ACTIVE === j.idx) ACTIVE = -1;
      flushPlayback(); renderStepper(); renderCanva(); curWho = null; curBubble = null;
      break;
    case "section_done":   // el bloque queda completo (✓); el avance al siguiente lo decide el usuario
      DONE.add(j.key); renderStepper(); renderCanva();
      if (DONE.size >= SECCIONES.length) setStatus("✓ ¡Onboarding completo! Tu Canva está listo.");
      else setStatus("✓ «" + tituloDe(j.idx) + "» lista — pulsa el siguiente bloque cuando quieras.");
      break;
    case "canva": CANVA = j.canva || CANVA; renderCanva(); break;
    case "booked": BOOKED = j; renderCanva(); break;
    case "user": addChunk("user", j.text); break;
    case "user_fix":   // corrige la última burbuja del usuario con el STT fiable (es-ES)
      if (lastUserBubble) lastUserBubble.querySelector(".body").textContent = j.text;
      break;
    case "bot": addChunk("bot", j.text); break;
    case "interrupted": flushPlayback(); curWho = null; break;
    case "error": setStatus("Error: " + (j.detail || "")); break;
  }
}

// ---- micrófono (perezoso: se pide en el primer "Hablar"; luego emite en continuo) ----
async function ensureMic() {
  if (micOn) return;
  ensurePlay();
  // AGC desactivado a propósito: el control automático de ganancia mueve el nivel del audio y
  // desestabiliza el umbral de energía fijo del VAD (la calibración deja de ser fiable).
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: false },
  });
  micCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = micCtx.createMediaStreamSource(micStream);
  micNode = micCtx.createScriptProcessor(4096, 1, 1);
  const silent = micCtx.createGain(); silent.gain.value = 0;
  micNode.onaudioprocess = (e) => {
    if (!ws || ws.readyState !== 1) return;
    // Anti-eco: no enviar el micro mientras Faro está SONANDO (cola hasta nextTime), para que su
    // propio audio por el altavoz no abra turno ni le interrumpa. El margen tras acabar es PEQUEÑO
    // (~60ms) para no comerse el arranque de una respuesta rápida ("sí"/"no") justo tras el recap;
    // el eco residual lo cubre el echoCancellation del micro (ensureMic) + el gate de servidor.
    if (playCtx && playCtx.currentTime < nextTime + 0.06) return;
    const ds = downsample(e.inputBuffer.getChannelData(0), micCtx.sampleRate, 16000);
    ws.send(toPCM16(ds));
  };
  src.connect(micNode); micNode.connect(silent); silent.connect(micCtx.destination);
  micOn = true;
}

// ---- secciones ----
async function startSection(idx) {
  if (!connected) { try { await connect(); } catch (e) { setStatus("No pude conectar al servidor."); return; } }
  try { await ensureMic(); } catch (e) { setStatus("Necesito permiso de micrófono para hablar."); return; }
  curWho = null; curBubble = null;   // la conversación se ACUMULA entre secciones (solo Reiniciar la borra)
  flushPlayback();
  ws.send(JSON.stringify({ type: "start_section", idx }));
  setStatus("Abriendo «" + (SECCIONES[idx] ? SECCIONES[idx].titulo : "") + "»…");
}
function stopSection() {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "stop_section" }));
}

// ---- reiniciar (pruebas): borra el Canva del usuario y sus citas de prueba ----
$("reset").addEventListener("click", async () => {
  if (!confirm("¿Reiniciar desde cero? Se borrará tu Canva y las citas de prueba de tu Calendar.")) return;
  // Cierra la sección activa si la hubiera (para no dejar a Faro hablando tras el reinicio).
  if (ACTIVE >= 0) { stopSection(); ACTIVE = -1; }
  // Limpia la UI YA (conversación + Canva), sin esperar al backend ni depender del estado.
  CANVA = {}; DONE = new Set(); BOOKED = null; curWho = null; curBubble = null; $("chat").innerHTML = "";
  renderStepper(); renderCanva();
  setStatus("Reiniciando…");
  try {
    const j = await (await fetch("/api/4g/reset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: getUserId() }),
    })).json();
    setStatus("Reiniciado desde cero" +
      (j.eventos_borrados ? ` (${j.eventos_borrados} cita(s) borradas)` : "") + ". Pulsa «🎙 Hablar».");
  } catch (e) { setStatus("Pantalla limpiada; el borrado en el servidor falló: " + e); }
});

// ---- arranque: conecta el WS al cargar (NO abre Gemini hasta pulsar «Hablar») ----
(async () => {
  setStatus("Conectando…");
  try { await connect(); } catch (e) { setStatus("No pude conectar al servidor."); }
})();
