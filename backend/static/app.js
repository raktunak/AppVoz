const $ = (id) => document.getElementById(id);
let ctx, stream, proc, source, frames = [], recording = false;
const history = [];

// ---------- Reproductor PCM en streaming ----------
let playCtx = null, nextTime = 0;
function ensurePlay() {
  if (!playCtx) playCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (playCtx.state === "suspended") playCtx.resume();
}
function playPCM(int16, rate) {
  const f32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 32768;
  const buf = playCtx.createBuffer(1, f32.length, rate);
  buf.copyToChannel(f32, 0);
  const src = playCtx.createBufferSource();
  src.buffer = buf; src.connect(playCtx.destination);
  const now = playCtx.currentTime;
  if (nextTime < now) nextTime = now + 0.03;
  src.start(nextTime);
  nextTime += buf.duration;
}

// ---------- Grabación (push-to-talk) ----------
async function startRec() {
  if (recording) return;
  ensurePlay();
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (e) { $("status").textContent = "No hay acceso al micro: " + e; return; }
  ctx = new (window.AudioContext || window.webkitAudioContext)();
  source = ctx.createMediaStreamSource(stream);
  proc = ctx.createScriptProcessor(4096, 1, 1);
  frames = [];
  proc.onaudioprocess = (e) => {
    if (recording) frames.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };
  source.connect(proc); proc.connect(ctx.destination);
  recording = true;
  const b = $("talk"); b.classList.add("rec"); b.textContent = "🔴 Grabando… suelta para enviar";
}

function stopRec() {
  if (!recording) return;
  recording = false;
  const srcRate = ctx.sampleRate;
  proc.disconnect(); source.disconnect();
  stream.getTracks().forEach((t) => t.stop());
  const b = $("talk"); b.classList.remove("rec"); b.textContent = "🎤 Mantén pulsado para hablar";
  const wav = encodeWAV(flatten(frames), srcRate, 16000);
  if (wav.byteLength < 2000) { $("status").textContent = "Audio demasiado corto."; return; }
  runTurn((ws) => ws.send(wav));
}

function flatten(arrs) {
  const len = arrs.reduce((a, b) => a + b.length, 0);
  const out = new Float32Array(len);
  let o = 0; for (const a of arrs) { out.set(a, o); o += a.length; }
  return out;
}
function downsample(buf, srcRate, dstRate) {
  if (dstRate >= srcRate) return buf;
  const ratio = srcRate / dstRate, newLen = Math.round(buf.length / ratio);
  const out = new Float32Array(newLen);
  let oi = 0, ii = 0;
  while (oi < newLen) {
    const next = Math.round((oi + 1) * ratio);
    let sum = 0, c = 0;
    for (; ii < next && ii < buf.length; ii++) { sum += buf[ii]; c++; }
    out[oi++] = c ? sum / c : 0;
  }
  return out;
}
function encodeWAV(buf, srcRate, dstRate) {
  const d = downsample(buf, srcRate, dstRate);
  const ab = new ArrayBuffer(44 + d.length * 2);
  const dv = new DataView(ab);
  let p = 0;
  const str = (s) => { for (let i = 0; i < s.length; i++) dv.setUint8(p++, s.charCodeAt(i)); };
  str("RIFF"); dv.setUint32(p, 36 + d.length * 2, true); p += 4; str("WAVE");
  str("fmt "); dv.setUint32(p, 16, true); p += 4; dv.setUint16(p, 1, true); p += 2;
  dv.setUint16(p, 1, true); p += 2; dv.setUint32(p, dstRate, true); p += 4;
  dv.setUint32(p, dstRate * 2, true); p += 4; dv.setUint16(p, 2, true); p += 2;
  dv.setUint16(p, 16, true); p += 2; str("data"); dv.setUint32(p, d.length * 2, true); p += 4;
  for (let i = 0; i < d.length; i++) {
    const s = Math.max(-1, Math.min(1, d[i]));
    dv.setInt16(p, s < 0 ? s * 0x8000 : s * 0x7fff, true); p += 2;
  }
  return ab;
}

// ---------- Turno por WebSocket (streaming) ----------
function runTurn(sendFn) {
  ensurePlay(); nextTime = 0;
  const subject = $("subject").value.trim() || "demo_voz";
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/voice/ws?subject_id=${encodeURIComponent(subject)}`);
  ws.binaryType = "arraybuffer";
  let rate = 24000, t0 = 0, firstAudio = null;
  $("transcript").textContent = "…"; $("answer").textContent = "…";
  ws.onopen = () => { t0 = performance.now(); $("status").textContent = "⏳ Procesando…"; sendFn(ws); };
  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      const j = JSON.parse(ev.data);
      if (j.type === "transcript") $("transcript").textContent = j.text || "(vacío)";
      else if (j.type === "answer") $("answer").textContent = j.text || "";
      else if (j.type === "audio_start") rate = j.sample_rate || 24000;
      else if (j.type === "metrics") {
        if (firstAudio !== null) j.metrics.client_ttfa_ms = Math.round(firstAudio - t0);
        renderMetrics(j.metrics); $("status").textContent = "✅ Listo";
      }
    } else {
      if (firstAudio === null) firstAudio = performance.now();
      playPCM(new Int16Array(ev.data), rate);
    }
  };
  ws.onerror = () => { $("status").textContent = "Error de conexión WS"; };
}

function renderMetrics(m) {
  const order = ["stt_ms", "retrieval_ms", "llm_ttft_ms", "llm_total_ms",
    "tts_first_ms", "ttfa_ms", "total_ms", "client_ttfa_ms"];
  $("metrics").innerHTML = order.filter((k) => k in m)
    .map((k) => `<tr><td>${k}</td><td>${m[k]} ms</td></tr>`).join("");
  history.push(m); renderAvg();
}
function renderAvg() {
  $("nturns").textContent = history.length;
  const keys = ["stt_ms", "retrieval_ms", "llm_total_ms", "ttfa_ms", "total_ms"];
  $("avg").innerHTML = keys.map((k) => {
    const vals = history.map((h) => h[k]).filter((v) => typeof v === "number");
    if (!vals.length) return "";
    const avg = Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
    return `<tr><td>${k}</td><td>${avg} ms</td></tr>`;
  }).join("");
}

// ---------- Wiring ----------
const talk = $("talk");
talk.addEventListener("mousedown", startRec);
talk.addEventListener("mouseup", stopRec);
talk.addEventListener("mouseleave", () => recording && stopRec());
talk.addEventListener("touchstart", (e) => { e.preventDefault(); startRec(); });
talk.addEventListener("touchend", (e) => { e.preventDefault(); stopRec(); });
$("ask").addEventListener("click", () => {
  const q = $("q").value.trim();
  if (q) runTurn((ws) => ws.send(JSON.stringify({ text: q, subject_id: $("subject").value.trim() || "demo_voz" })));
});
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") $("ask").click(); });
