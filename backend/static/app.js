const $ = (id) => document.getElementById(id);
let ctx, stream, proc, source, frames = [], recording = false;
const history = [];

// ---------- Grabación (push-to-talk) ----------
async function startRec() {
  if (recording) return;
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
  source.connect(proc);
  proc.connect(ctx.destination);
  recording = true;
  const b = $("talk"); b.classList.add("rec"); b.textContent = "🔴 Grabando… suelta para enviar";
}

async function stopRec() {
  if (!recording) return;
  recording = false;
  const srcRate = ctx.sampleRate;
  proc.disconnect(); source.disconnect();
  stream.getTracks().forEach((t) => t.stop());
  const b = $("talk"); b.classList.remove("rec"); b.textContent = "🎤 Mantén pulsado para hablar";
  const wav = encodeWAV(flatten(frames), srcRate, 16000);
  if (wav.size < 2000) { $("status").textContent = "Audio demasiado corto."; return; }
  await send({ audioBlob: wav });
}

function flatten(arrs) {
  const len = arrs.reduce((a, b) => a + b.length, 0);
  const out = new Float32Array(len);
  let o = 0; for (const a of arrs) { out.set(a, o); o += a.length; }
  return out;
}

function downsample(buf, srcRate, dstRate) {
  if (dstRate >= srcRate) return buf;
  const ratio = srcRate / dstRate;
  const newLen = Math.round(buf.length / ratio);
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
  const dv = new DataView(new ArrayBuffer(44 + d.length * 2));
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
  return new Blob([dv], { type: "audio/wav" });
}

// ---------- Envío ----------
async function send({ audioBlob, textQ }) {
  const fd = new FormData();
  fd.append("subject_id", $("subject").value.trim() || "demo_voz");
  if (audioBlob) fd.append("audio", audioBlob, "turn.wav");
  if (textQ) fd.append("text_input", textQ);
  $("status").textContent = "⏳ Procesando…";
  const t0 = performance.now();
  try {
    const r = await fetch("/voice/turn", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) { $("status").textContent = "Error: " + JSON.stringify(j); return; }
    j.metrics.network_ms = Math.round(performance.now() - t0);
    render(j);
    $("status").textContent = "✅ Listo";
  } catch (e) { $("status").textContent = "Error: " + e; }
}

function render(j) {
  $("transcript").textContent = j.transcript || "(vacío)";
  $("answer").textContent = j.answer || "";
  const audio = $("audio");
  audio.src = "data:audio/wav;base64," + j.audio_wav_b64;
  audio.play().catch(() => {});
  const order = ["stt_ms", "retrieval_ms", "llm_ttft_ms", "llm_total_ms", "tts_ms", "total_ms", "network_ms"];
  const m = j.metrics;
  $("metrics").innerHTML = order.filter((k) => k in m)
    .map((k) => `<tr><td>${k}</td><td>${m[k]} ms</td></tr>`).join("");
  history.push(m);
  renderAvg();
}

function renderAvg() {
  $("nturns").textContent = history.length;
  const keys = ["stt_ms", "retrieval_ms", "llm_ttft_ms", "llm_total_ms", "tts_ms", "total_ms"];
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
  const q = $("q").value.trim(); if (q) send({ textQ: q });
});
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") $("ask").click(); });
