// Cliente del onboarding 4G: mic → PCM16 16k → WS /ws/4g; recibe audio (24k) + Canva en vivo.
const $ = (id) => document.getElementById(id);
let ws, micCtx, micStream, micNode, playCtx, nextTime = 0, sources = [], onCall = false;
let SECCIONES = [], ACTIVA = 0, CANVA = {}, BOOKED = null;
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

// ---- stepper (izquierda) ----
function renderStepper() {
  const nav = $("stepper"); nav.innerHTML = "";
  SECCIONES.forEach((s, i) => {
    const el = document.createElement("div");
    el.className = "step" + (i < ACTIVA ? " done" : "") + (i === ACTIVA ? " active" : "");
    const dot = document.createElement("div");
    dot.className = "dot"; dot.textContent = i < ACTIVA ? "✓" : (i + 1);
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
function renderCanva() {
  const grid = $("grid"); grid.innerHTML = "";
  SECCIONES.forEach((s, i) => {
    const card = document.createElement("div");
    card.className = "cv" + (i === ACTIVA ? " active" : "");
    const h = document.createElement("h3"); h.textContent = s.titulo;
    card.appendChild(h);
    renderSeccion(card, s, CANVA[s.key]);
    grid.appendChild(card);
  });
}

// ---- WebSocket / llamada ----
async function start() {
  ensurePlay();
  curWho = null; curBubble = null; $("chat").innerHTML = "";
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/4g`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "config", user_id: getUserId() }));
    setStatus("Conectando con la guía…");
  };
  const ready = new Promise((resolve, reject) => {
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        const j = JSON.parse(ev.data);
        if (j.type === "ready") {
          SECCIONES = j.secciones || []; ACTIVA = j.activa || 0; CANVA = j.canva || {}; BOOKED = null;
          renderStepper(); renderCanva();
          setStatus("En marcha — Faro te saluda; escucha y responde cuando termine.");
          resolve();
        } else if (j.type === "error") { setStatus("Error: " + j.detail); reject(new Error(j.detail)); }
        else if (j.type === "interrupted") { flushPlayback(); curWho = null; }
        else if (j.type === "user") addChunk("user", j.text);
        else if (j.type === "bot") addChunk("bot", j.text);
        else if (j.type === "canva") { CANVA = j.canva || CANVA; renderCanva(); }
        else if (j.type === "section") { ACTIVA = j.activa; renderStepper(); renderCanva(); }
        else if (j.type === "booked") { BOOKED = j; renderCanva(); }
      } else {
        playChunk(new Int16Array(ev.data));
      }
    };
    ws.onerror = () => { setStatus("Error de conexión."); reject(new Error("ws error")); };
  });
  ws.onclose = () => { if (onCall) stop(); };
  await ready;

  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  micCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = micCtx.createMediaStreamSource(micStream);
  micNode = micCtx.createScriptProcessor(4096, 1, 1);
  const silent = micCtx.createGain(); silent.gain.value = 0;
  micNode.onaudioprocess = (e) => {
    if (!ws || ws.readyState !== 1) return;
    // Anti-eco: no enviar el micro mientras Faro está SONANDO (incluida la cola de
    // reproducción, hasta `nextTime`), para que su propio audio por el altavoz no abra turno
    // ni le interrumpa. `nextTime` es el instante en que termina lo que hay encolado.
    if (playCtx && playCtx.currentTime < nextTime + 0.15) return;
    const ds = downsample(e.inputBuffer.getChannelData(0), micCtx.sampleRate, 16000);
    ws.send(toPCM16(ds));
  };
  src.connect(micNode); micNode.connect(silent); silent.connect(micCtx.destination);
}

function stop() {
  onCall = false;
  try { micNode && micNode.disconnect(); } catch (e) {}
  try { micStream && micStream.getTracks().forEach((t) => t.stop()); } catch (e) {}
  try { micCtx && micCtx.close(); } catch (e) {}
  try { ws && ws.close(); } catch (e) {}
  flushPlayback();
  $("mic").textContent = "🎙 Empezar"; $("mic").classList.remove("on");
  setStatus("Sesión finalizada. Tu Canva queda guardado.");
}

$("mic").addEventListener("click", async () => {
  if (onCall) { stop(); return; }
  onCall = true;
  $("mic").textContent = "■ Terminar"; $("mic").classList.add("on"); setStatus("Conectando…");
  try { await start(); } catch (e) { setStatus("Error: " + e); stop(); }
});

// Reiniciar desde cero (para pruebas): borra el Canva del usuario y sus citas de prueba.
$("reset").addEventListener("click", async () => {
  if (onCall) { setStatus("Termina la sesión antes de reiniciar."); return; }
  if (!confirm("¿Reiniciar desde cero? Se borrará tu Canva y las citas de prueba de tu Calendar.")) return;
  setStatus("Reiniciando…");
  try {
    const j = await (await fetch("/api/4g/reset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: getUserId() }),
    })).json();
    CANVA = {}; ACTIVA = 0; BOOKED = null; curWho = null; curBubble = null; $("chat").innerHTML = "";
    renderStepper(); renderCanva();
    setStatus("Reiniciado desde cero" +
      (j.eventos_borrados ? ` (${j.eventos_borrados} cita(s) borradas)` : "") + ". Pulsa «Empezar».");
  } catch (e) { setStatus("No pude reiniciar: " + e); }
});

// Al cargar: muestra el Canva ya guardado (si hay) y la sección activa REAL del backend
// (primera incompleta), no por mera existencia de la clave.
(async () => {
  try {
    const j = await (await fetch("/api/4g/canva?user_id=" + encodeURIComponent(getUserId()))).json();
    SECCIONES = j.secciones || []; CANVA = j.canva || {}; ACTIVA = j.activa || 0;
    renderStepper(); renderCanva();
  } catch (e) { /* sin datos previos */ }
})();
