const $ = (id) => document.getElementById(id);
let ws, micCtx, micStream, micNode, playCtx, nextTime = 0, sources = [], onCall = false;
let curWho = null, curBubble = null;
let accTokens = 0, nReports = 0;
let accAudioIn = 0, accAudioOut = 0, accTextIn = 0, accTextOut = 0;
let CAPS = {}, USD_EUR = 0.92, VOICE_GENDERS = {};
let sessionId = null;

// ---- identidad de sesión ----
function newId() {
  return (crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : "u-" + Date.now() + "-" + Math.random().toString(36).slice(2);
}
// user_id persistente entre llamadas (localStorage); session_id nuevo por llamada.
function getUserId() {
  let id = localStorage.getItem("appvoz_user_id");
  if (!id) { id = newId(); localStorage.setItem("appvoz_user_id", id); }
  return id;
}

function setStatus(s) { $("status").textContent = s; }
function clearChat() { $("chat").innerHTML = ""; curWho = null; curBubble = null; }
function addChunk(who, text) {
  if (who !== curWho || !curBubble) {
    curBubble = document.createElement("div");
    curBubble.className = "msg " + who;
    const w = document.createElement("div");
    w.className = "who"; w.textContent = who === "user" ? "Tú" : "Bot";
    const b = document.createElement("div"); b.className = "body";
    curBubble.appendChild(w); curBubble.appendChild(b);
    $("chat").appendChild(curBubble); curWho = who;
  }
  const body = curBubble.querySelector(".body");
  body.textContent = (body.textContent + " " + text).trim();
  $("chat").scrollTop = $("chat").scrollHeight;
}

// ---- panel de ajustes (adaptativo por modelo) ----
function fillSelect(sel, items, selected) {
  sel.innerHTML = "";
  items.forEach((it) => {
    const val = (typeof it === "object") ? it.value : it;
    const txt = (typeof it === "object") ? it.label : it;
    const o = document.createElement("option");
    o.value = val; o.textContent = txt; if (val === selected) o.selected = true;
    sel.appendChild(o);
  });
}
// Rellena el desplegable de voces del modelo actual, filtrado por género.
function renderVoices() {
  const c = CAPS[$("model").value]; if (!c) return;
  const g = $("gender").value;
  const filtradas = c.voices.filter((v) => g === "todas" || VOICE_GENDERS[v] === g);
  const lista = filtradas.length ? filtradas : c.voices;  // si el filtro deja vacío, todas
  const sel = lista.includes(c.default_voice) ? c.default_voice : lista[0];
  fillSelect($("voice"), lista, sel);
}
function renderModel(model) {
  const c = CAPS[model]; if (!c) return;
  $("modelHint").textContent = c.label || "";
  renderVoices();
  // Idioma: solo si el modelo lo admite
  if (c.language && c.language.configurable) {
    fillSelect($("language"), c.language.codes || [], c.language.default || "");
    $("langBox").classList.remove("hidden");
    $("langHint").textContent = c.language.note || "";
  } else {
    $("langBox").classList.add("hidden");
    $("langHint").textContent = (c.language && c.language.note) || "";
  }
  // Features native-audio
  const f = c.features || {};
  const hasFeat = !!(f.affective_dialog || f.proactivity);
  $("featBox").classList.toggle("hidden", !hasFeat);
  $("affective").parentElement.classList.toggle("hidden", !f.affective_dialog);
  $("proactive").parentElement.classList.toggle("hidden", !f.proactivity);
  $("affective").checked = false; $("proactive").checked = false;
  const p = c.pricing;
  $("priceHint").textContent = p
    ? `Audio $${p.audio_in}/$${p.audio_out} · texto $${p.text_in}/$${p.text_out} por 1M tok ($1≈${USD_EUR}€)`
    : "";
  updateCost();
}
async function loadDefaults() {
  try {
    const d = await (await fetch("/api/live/defaults")).json();
    CAPS = d.caps || {};
    USD_EUR = d.usd_eur || USD_EUR;
    VOICE_GENDERS = d.voice_genders || {};
    const models = (d.models || []).map((m) => ({ value: m, label: (CAPS[m] && CAPS[m].label) || m }));
    fillSelect($("model"), models, d.default_model);
    $("prompt").value = d.persona || "";
    renderModel(d.default_model);
    $("model").addEventListener("change", (e) => renderModel(e.target.value));
    $("gender").addEventListener("change", renderVoices);
    $("prompt").addEventListener("input", schedulePromptCount);
    countPromptTokens();
    setStatus(`Listo · región ${d.location}. Edita el prompt y pulsa Iniciar.`);
  } catch (e) {
    setStatus("No pude cargar ajustes: " + e);
  }
}
function lockPanel(locked) {
  $("panel").classList.toggle("locked", locked);
  $("lockNote").textContent = locked ? "🔒 En llamada: cuelga para cambiar ajustes." : "";
}

// ---- historial de conversaciones guardadas ----
let activeHistId = null;
// Convierte un ISO 8601 a algo legible en es-ES; "—" si no hay fecha.
function fmtFecha(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("es-ES", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
// Pinta la lista de sesiones del usuario en #history.
async function loadHistory() {
  const cont = $("history");
  try {
    const r = await fetch("/api/live/sessions?user_id=" + encodeURIComponent(getUserId()) + "&limit=20");
    const j = await r.json();
    const sesiones = j.sessions || [];
    cont.innerHTML = "";
    if (!sesiones.length) {
      const e = document.createElement("div");
      e.className = "hist-empty"; e.textContent = "Sin conversaciones guardadas";
      cont.appendChild(e);
      return;
    }
    sesiones.forEach((s) => {
      const item = document.createElement("div");
      item.className = "hist-item";
      if (s.id === activeHistId) item.classList.add("active");
      item.dataset.id = s.id;

      const fecha = document.createElement("div");
      fecha.className = "h-date"; fecha.textContent = fmtFecha(s.started_at);

      const meta = document.createElement("div");
      meta.className = "h-meta";
      meta.textContent = (s.n_turnos || 0) + " turno" + ((s.n_turnos === 1) ? "" : "s");

      item.appendChild(fecha); item.appendChild(meta);

      if (s.preview) {
        const pv = document.createElement("div");
        pv.className = "h-preview"; pv.textContent = s.preview;
        item.appendChild(pv);
      }

      item.addEventListener("click", () => verConversacion(s.id));
      cont.appendChild(item);
    });
  } catch (e) {
    cont.innerHTML = "";
    const err = document.createElement("div");
    err.className = "hist-empty"; err.textContent = "No pude cargar el historial.";
    cont.appendChild(err);
  }
}
// Carga una sesión guardada en el chat (solo lectura). No toca la llamada en vivo.
async function verConversacion(id) {
  if (onCall) return; // no pisar una llamada en curso
  try {
    const r = await fetch("/api/live/sessions/" + id);
    if (!r.ok) { setStatus("No pude abrir la conversación."); return; }
    const j = await r.json();
    clearChat();
    (j.turnos || []).forEach((t) => {
      if (t.user_text) addChunk("user", t.user_text);
      if (t.bot_text) addChunk("bot", t.bot_text);
    });
    activeHistId = id;
    document.querySelectorAll("#history .hist-item").forEach((el) => {
      el.classList.toggle("active", Number(el.dataset.id) === id);
    });
    setStatus("Viendo conversación guardada (" + fmtFecha(j.started_at) + ").");
  } catch (e) {
    setStatus("No pude abrir la conversación: " + e);
  }
}

// ---- tamaño del prompt (tokens reales vía count_tokens; estimación local si la API falla) ----
let promptCountTimer = null;
function estTokens(t) { return Math.max(1, Math.round(t.trim().length / 4)); }
function schedulePromptCount() {
  clearTimeout(promptCountTimer);
  promptCountTimer = setTimeout(countPromptTokens, 600);
}
async function countPromptTokens() {
  const text = $("prompt").value;
  const el = $("promptTokens");
  if (!text.trim()) { el.textContent = "Tamaño del prompt: 0 tokens"; return; }
  el.textContent = "Tamaño del prompt: … tokens";
  try {
    const r = await fetch("/api/live/count_tokens", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, model: $("model").value }),
    });
    const j = await r.json();
    el.textContent = (j.tokens != null)
      ? `Tamaño del prompt: ${fmt(j.tokens)} tokens`
      : `Tamaño del prompt: ~${fmt(estTokens(text))} tokens (estimado)`;
  } catch (e) {
    el.textContent = `Tamaño del prompt: ~${fmt(estTokens(text))} tokens (estimado)`;
  }
}

// ---- consumo ----
function audioOf(mod) {
  if (!mod) return 0;
  const k = Object.keys(mod).find((x) => x.toUpperCase().includes("AUDIO"));
  return (k && mod[k]) ? mod[k] : 0;
}
function fmt(n) { return (n == null) ? "—" : Number(n).toLocaleString("es-ES"); }
function updateCost() {
  const p = (CAPS[$("model").value] || {}).pricing;
  if (!p) { $("uCost").textContent = "—"; return; }
  const usd = (accAudioIn * p.audio_in + accAudioOut * p.audio_out
             + accTextIn * p.text_in + accTextOut * p.text_out) / 1e6;
  $("uCost").textContent = (usd * USD_EUR).toFixed(4) + " €";
}
function showUsage(u) {
  nReports++;
  const audioIn = audioOf(u.prompt_by_modality);
  const audioOut = audioOf(u.response_by_modality);
  // El resto del prompt/response que no es audio se factura como texto (system prompt, transcripción).
  accAudioIn += audioIn; accAudioOut += audioOut;
  accTextIn += Math.max((u.prompt || 0) - audioIn, 0);
  accTextOut += Math.max((u.response || 0) - audioOut, 0);
  if (u.total != null) accTokens += u.total;
  $("uTotal").textContent = fmt(u.total);
  $("uPrompt").textContent = fmt(u.prompt);
  $("uResp").textContent = fmt(u.response);
  $("uAudio").textContent = fmt(audioIn) + " / " + fmt(audioOut);
  $("uAcc").textContent = fmt(accTokens);
  $("uTurns").textContent = nReports;
  updateCost();
}
function resetUsage() {
  accTokens = 0; nReports = 0; accAudioIn = 0; accAudioOut = 0; accTextIn = 0; accTextOut = 0;
  ["uTotal","uPrompt","uResp"].forEach((id) => $(id).textContent = "—");
  $("uAudio").textContent = "—"; $("uAcc").textContent = "0"; $("uTurns").textContent = "0"; $("uCost").textContent = "—";
}

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

async function start() {
  ensurePlay();
  // NO se limpia el chat: la conversación se conserva entre llamadas (se va añadiendo).
  activeHistId = null;   // al iniciar una llamada nueva, ya no estamos viendo historial
  resetUsage();
  sessionId = newId(); // session_id nuevo en cada llamada
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/call`);
  ws.binaryType = "arraybuffer";

  // Handshake: en cuanto abre, mandamos la config (prompt/voz/modelo) ANTES del audio.
  ws.onopen = () => {
    ws.send(JSON.stringify({
      type: "config",
      user_id: getUserId(),
      session_id: sessionId,
      subject_id: "demo",
      model: $("model").value,
      voice: $("voice").value,
      language: $("language").value,
      temperature: $("temp").value,
      max_output_tokens: $("maxtok").value,
      affective_dialog: $("affective").checked,
      proactivity: $("proactive").checked,
      mic_threshold: micThreshold(),
      end_silence: silFrames(),
      barge_frames: bargeFrames(),
      system_instruction: $("prompt").value,
    }));
    setStatus("Conectando con el modelo…");
  };

  // Esperamos 'ready' antes de abrir el micro.
  const ready = new Promise((resolve, reject) => {
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        const j = JSON.parse(ev.data);
        if (j.type === "ready") { setStatus(`En llamada (${j.model}) — habla cuando quieras.`); resolve(); }
        else if (j.type === "error") { setStatus("Error del modelo: " + j.detail); reject(new Error(j.detail)); }
        else if (j.type === "interrupted") { flushPlayback(); curWho = null; }
        else if (j.type === "user") addChunk("user", j.text);
        else if (j.type === "bot") addChunk("bot", j.text);
        else if (j.type === "usage") showUsage(j.usage);
      } else {
        playChunk(new Int16Array(ev.data));
      }
    };
    ws.onerror = () => { setStatus("Error de conexión."); reject(new Error("ws error")); };
  });
  ws.onclose = () => { if (onCall) hangup(); };
  await ready;

  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  micCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = micCtx.createMediaStreamSource(micStream);
  micNode = micCtx.createScriptProcessor(4096, 1, 1);
  const silent = micCtx.createGain();
  silent.gain.value = 0;
  micNode.onaudioprocess = (e) => {
    if (!ws || ws.readyState !== 1) return;
    const ds = downsample(e.inputBuffer.getChannelData(0), micCtx.sampleRate, 16000);
    ws.send(toPCM16(ds));
  };
  src.connect(micNode); micNode.connect(silent); silent.connect(micCtx.destination);
}

function hangup() {
  onCall = false;
  try { micNode && micNode.disconnect(); } catch (e) {}
  try { micStream && micStream.getTracks().forEach((t) => t.stop()); } catch (e) {}
  try { micCtx && micCtx.close(); } catch (e) {}
  try { ws && ws.close(); } catch (e) {}
  flushPlayback();
  lockPanel(false);
  $("call").textContent = "☎ Iniciar llamada"; $("call").classList.remove("on");
  setStatus("Llamada finalizada.");
  // La persistencia ocurre al cerrar el WS en el servidor; damos margen a que se guarde.
  setTimeout(loadHistory, 1800);
}

$("call").addEventListener("click", async () => {
  if (onCall) { hangup(); return; }
  onCall = true;
  lockPanel(true);
  $("call").textContent = "■ Colgar"; $("call").classList.add("on"); setStatus("Conectando…");
  try { await start(); } catch (e) { setStatus("Error: " + e); hangup(); }
});

// ---- ajustes de micro/VAD (sliders en vivo: ajustables en plena llamada) ----
// Sensibilidad: 0 (ignora ruido) → 100 (capta voz baja). Se mapea al umbral de energía.
function micThreshold() {
  const s = Number($("micSens").value);
  return Math.round(3000 - (s / 100) * (3000 - 600));  // 0 → 3000, 100 → 600
}
// Intensidad con nombre + color según la posición del slider.
function micLevel(s) {
  if (s < 20) return { name: "Muy baja", color: "#4a90d9" };
  if (s < 40) return { name: "Baja",     color: "#3a8c5e" };
  if (s < 60) return { name: "Media",    color: "#6fae3a" };
  if (s < 80) return { name: "Alta",     color: "#caa14a" };
  return                { name: "Muy alta", color: "#d9694a" };
}
function renderMicSens() {
  const s = Number($("micSens").value);
  const lv = micLevel(s);
  $("micLevel").textContent = lv.name;
  $("micLevel").style.color = lv.color;
  $("micSens").style.accentColor = lv.color;     // la barra cambia de color con el nivel
  $("micSensVal").textContent = "umbral " + micThreshold();
}
// Pausa de fin de turno y resistencia a cortes: sliders en frames (~85 ms); se muestran en segundos.
const FRAME_MS = 85;
function silFrames() { return Number($("silSlider").value); }
function renderSil() { $("silVal").innerHTML = (silFrames() * FRAME_MS / 1000).toFixed(1) + "&nbsp;s"; }
function bargeFrames() { return Number($("bargeSlider").value); }
function renderBarge() { $("bargeVal").innerHTML = (bargeFrames() * FRAME_MS / 1000).toFixed(1) + "&nbsp;s"; }
// En llamada, manda un snapshot de los tres parámetros para que el VAD se ajuste al instante.
function sendVadLive() {
  if (ws && ws.readyState === 1 && onCall) {
    ws.send(JSON.stringify({
      type: "vad", threshold: micThreshold(), end_silence: silFrames(), barge_frames: bargeFrames(),
    }));
  }
}
function nudgeMic(delta) {
  $("micSens").value = Math.max(0, Math.min(100, Number($("micSens").value) + delta));
  renderMicSens(); sendVadLive();
}
function nudgeSil(delta) {
  $("silSlider").value = Math.max(3, Math.min(30, silFrames() + delta));
  renderSil(); sendVadLive();
}
function nudgeBarge(delta) {
  $("bargeSlider").value = Math.max(2, Math.min(12, bargeFrames() + delta));
  renderBarge(); sendVadLive();
}
$("micSens").addEventListener("input", () => { renderMicSens(); sendVadLive(); });
$("micMinus").addEventListener("click", () => nudgeMic(-2));
$("micPlus").addEventListener("click", () => nudgeMic(+2));
$("silSlider").addEventListener("input", () => { renderSil(); sendVadLive(); });
$("silMinus").addEventListener("click", () => nudgeSil(-1));
$("silPlus").addEventListener("click", () => nudgeSil(+1));
$("bargeSlider").addEventListener("input", () => { renderBarge(); sendVadLive(); });
$("bargeMinus").addEventListener("click", () => nudgeBarge(-1));
$("bargePlus").addEventListener("click", () => nudgeBarge(+1));
renderMicSens(); renderSil(); renderBarge();

loadDefaults().then(loadHistory);
