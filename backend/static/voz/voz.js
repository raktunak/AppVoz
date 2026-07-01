// Vista de configuración "SOLO VOZ": un panel reducido con únicamente los controles de voz de un
// servicio (Modelo, Voz, Idioma, Inmersión, Micrófono, Generación). Reutiliza los MISMOS endpoints
// que el panel /call (`/api/live/defaults` para las capacidades, `/api/servicios` para cargar/guardar)
// y los MISMOS mapeos de sliders. NO hay WebSocket, ni prompt, ni llamada de prueba, ni consumo.
// Al GUARDAR se PRESERVAN los campos que esta vista no edita (prompt, nombre, ruta, subject_id).
// Pensada para reutilizarse en otras partes de la app vía `/voz?svc=<ruta|nombre>`.
const $ = (id) => document.getElementById(id);
let CAPS = {}, VOICE_GENDERS = {};
let svcActual = null;   // servicio cargado (con su cfg COMPLETA; de ahí preservamos lo no-editable)
let listo = false;      // true tras volcar la cfg → habilita el auto-guardado (evita guardar al cargar)

function setStatus(s) { $("status").textContent = s; }

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
// Voces del modelo actual, filtradas por género (si el filtro deja vacío, todas).
function renderVoices() {
  const c = CAPS[$("model").value]; if (!c) return;
  const g = $("gender").value;
  const filtradas = c.voices.filter((v) => g === "todas" || VOICE_GENDERS[v] === g);
  const lista = filtradas.length ? filtradas : c.voices;
  const sel = lista.includes(c.default_voice) ? c.default_voice : lista[0];
  fillSelect($("voice"), lista, sel);
}
// Ajusta el panel a las CAPACIDADES del modelo (voces, idioma configurable, features native-audio).
function renderModel(model) {
  const c = CAPS[model]; if (!c) return;
  $("modelHint").textContent = c.label || "";
  renderVoices();
  if (c.language && c.language.configurable) {
    fillSelect($("language"), c.language.codes || [], c.language.default || "");
    $("langBox").classList.remove("hidden");
    $("langHint").textContent = c.language.note || "";
  } else {
    $("langBox").classList.add("hidden");
    $("langHint").textContent = (c.language && c.language.note) || "";
  }
  const f = c.features || {};
  const hasFeat = !!(f.affective_dialog || f.proactivity);
  $("featBox").classList.toggle("hidden", !hasFeat);
  $("affective").parentElement.classList.toggle("hidden", !f.affective_dialog);
  $("proactive").parentElement.classList.toggle("hidden", !f.proactivity);
  $("affective").checked = false; $("proactive").checked = false;
}

// ---- sliders VAD: MISMOS mapeos que el panel /call ----
function micThreshold() {
  const s = Number($("micSens").value);
  return Math.round(3000 - (s / 100) * (3000 - 600));   // 0 → 3000, 100 → 600
}
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
  $("micLevel").textContent = lv.name; $("micLevel").style.color = lv.color;
  $("micSens").style.accentColor = lv.color;
  $("micSensVal").textContent = "umbral " + micThreshold();
}
const FRAME_MS = 85;
function silFrames() { return Number($("silSlider").value); }
function renderSil() { $("silVal").innerHTML = (silFrames() * FRAME_MS / 1000).toFixed(1) + "&nbsp;s"; }
function bargeFrames() { return Number($("bargeSlider").value); }
function renderBarge() { $("bargeVal").innerHTML = (bargeFrames() * FRAME_MS / 1000).toFixed(1) + "&nbsp;s"; }
function nudge(id, delta, min, max, render) {
  $(id).value = Math.max(min, Math.min(max, Number($(id).value) + delta));
  render();
}
$("micSens").addEventListener("input", renderMicSens);
$("micMinus").addEventListener("click", () => nudge("micSens", -2, 0, 100, renderMicSens));
$("micPlus").addEventListener("click", () => nudge("micSens", +2, 0, 100, renderMicSens));
$("silSlider").addEventListener("input", renderSil);
$("silMinus").addEventListener("click", () => nudge("silSlider", -1, 3, 30, renderSil));
$("silPlus").addEventListener("click", () => nudge("silSlider", +1, 3, 30, renderSil));
$("bargeSlider").addEventListener("input", renderBarge);
$("bargeMinus").addEventListener("click", () => nudge("bargeSlider", -1, 2, 12, renderBarge));
$("bargePlus").addEventListener("click", () => nudge("bargeSlider", +1, 2, 12, renderBarge));
renderMicSens(); renderSil(); renderBarge();

$("model").addEventListener("change", (e) => renderModel(e.target.value));
$("gender").addEventListener("change", renderVoices);

// ---- volcar la cfg del servicio a los controles (solo campos de VOZ) ----
function applyConfigToPanel(cfg) {
  cfg = cfg || {};
  if (cfg.model && CAPS[cfg.model]) $("model").value = cfg.model;
  renderModel($("model").value);
  $("gender").value = "todas"; renderVoices();
  if (cfg.voice && [...$("voice").options].some((o) => o.value === cfg.voice)) $("voice").value = cfg.voice;
  if (cfg.language && !$("langBox").classList.contains("hidden")) $("language").value = cfg.language;
  $("temp").value = (cfg.temperature == null) ? "" : cfg.temperature;
  $("maxtok").value = (cfg.max_output_tokens == null) ? "" : cfg.max_output_tokens;
  $("affective").checked = !!cfg.affective_dialog;
  $("proactive").checked = !!cfg.proactivity;
  if (cfg.mic_threshold != null) {
    $("micSens").value = Math.max(0, Math.min(100,
      Math.round((3000 - Number(cfg.mic_threshold)) / (3000 - 600) * 100)));
  }
  if (cfg.end_silence != null) $("silSlider").value = Math.max(3, Math.min(30, Number(cfg.end_silence)));
  if (cfg.barge_frames != null) $("bargeSlider").value = Math.max(2, Math.min(12, Number(cfg.barge_frames)));
  renderMicSens(); renderSil(); renderBarge();
}

// Solo los campos de VOZ que esta vista edita (los demás cfg se preservan al guardar).
function vozFields() {
  return {
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
  };
}

// ---- AUTO-GUARDADO: como el panel /call, se guarda solo al modificar (debounce). PRESERVA lo que
// esta vista NO edita (prompt, nombre, ruta, subject_id, es_default). Sin botón de guardar. ----
let saveTimer = null;
function autoGuardar() {
  if (!listo || !svcActual || !svcActual.id) return;   // solo con servicio cargado y tras el volcado
  const prev = svcActual.cfg || {};
  const body = {
    id: svcActual.id,
    nombre: svcActual.nombre,
    ruta: svcActual.ruta,
    subject_id: svcActual.subject_id || "demo",
    es_default: !!svcActual.es_default,
    system_instruction: (prev.system_instruction != null) ? prev.system_instruction : "",  // preservar prompt
    ...vozFields(),
  };
  setStatus("Guardando…");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      const j = await (await fetch("/api/servicios", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      })).json();
      if (j.ok) { svcActual.cfg = { ...prev, ...vozFields() }; setStatus("✓ Guardado"); }
      else setStatus("Error: " + (j.error || "no se pudo guardar"));
    } catch (e) { setStatus("Error: " + e); }
  }, 600);
}
function wireAutosave() {
  ["model", "gender", "voice", "language", "affective", "proactive"]
    .forEach((id) => $(id).addEventListener("change", autoGuardar));
  ["temp", "maxtok", "micSens", "silSlider", "bargeSlider"]
    .forEach((id) => $(id).addEventListener("input", autoGuardar));
  ["micMinus", "micPlus", "silMinus", "silPlus", "bargeMinus", "bargePlus"]
    .forEach((id) => $(id).addEventListener("click", autoGuardar));
}
wireAutosave();

// ---- arranque: capacidades (para poder volcar la cfg) + servicio por ?svc= ----
async function loadDefaults() {
  const d = await (await fetch("/api/live/defaults")).json();
  CAPS = d.caps || {};
  VOICE_GENDERS = d.voice_genders || {};
  const models = (d.models || []).map((m) => ({ value: m, label: (CAPS[m] && CAPS[m].label) || m }));
  fillSelect($("model"), models, d.default_model);
  renderModel(d.default_model);
}
async function loadServicio() {
  const ruta = new URLSearchParams(location.search).get("svc");
  if (!ruta) { setStatus("Sin ?svc=: ajustes por defecto (no hay servicio que guardar)."); return; }
  try {
    const j = await (await fetch("/api/servicios")).json();
    const svc = (j.servicios || []).find((s) => String(s.ruta) === String(ruta) || s.nombre === ruta);
    if (!svc) { setStatus("No encontré el servicio «" + ruta + "»."); return; }
    svcActual = svc;
    $("vozTitle").textContent = "Voz · " + (svc.nombre || ruta);
    applyConfigToPanel(svc.cfg);
    listo = true;   // a partir de aquí, cualquier cambio se auto-guarda
    setStatus("Editando la voz de «" + (svc.nombre || ruta) + "» · los cambios se guardan solos.");
  } catch (e) { setStatus("No pude cargar el servicio: " + e); }
}
loadDefaults().then(loadServicio).catch((e) => setStatus("No pude cargar los ajustes: " + e));
