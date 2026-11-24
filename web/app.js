/* Mochi app: talks to the Pi's /api. Works in a phone browser and inside the Android app
   (window.MochiApp = the Android bridge: speech input, "find another Mochi"). */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const cap = s => String(s || "").replace(/\b\w/g, c => c.toUpperCase());
let S = null, online = false, tab = "home";

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch("/api/" + path, opt);
  const j = await r.json().catch(() => ({}));
  if (body !== undefined && !j.ok) throw new Error(typeof j.msg === "string" ? j.msg : "failed");
  return body === undefined ? j : j.msg;
}
function toast(msg, err) {
  const t = $("toast"); t.className = "toast"; void t.offsetWidth;   // restart the nod / shake
  t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  Eyes.react(err ? "no" : "yes");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.className = "toast", 2600);
}
async function act(fn, ok) { try { const r = await fn(); if (ok) toast(typeof ok === "function" ? ok(r) : ok); refresh(); return r; } catch (e) { toast(e.message, true); } }

/* ---------- tabs ---------- */
document.querySelectorAll("nav button").forEach(b => b.onclick = () => show(b.dataset.tab));
function show(name) {
  tab = name;
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach(s => s.classList.toggle("on", s.id === "t-" + name));
  if (name === "wifi") loadWifi();
  if (name === "set") loadSettings();
  if (name === "places") loadPlaces();
  camLoop();
}

/* ---------- status ---------- */
const MOVE_LABEL = { happy: "Happy", excited: "Excited", angry: "Angry", sad: "Sad", curious: "Curious",
  sleepy: "Sleepy", love: "Love", no: "No", yes: "Yes", spin: "Spin" };
async function refresh() {
  try {
    S = await api("status");
    online = true;
  } catch (e) { online = false; }
  $("dot").className = "dot " + (online ? "on" : "off");
  $("connTxt").textContent = online ? "online" : "offline";
  if (!online || !S) return;
  $("name").textContent = S.name;
  document.title = S.name;
  const p = S.places;
  $("sub").textContent = p.here ? `in the ${p.here}` : "your little helper";
  $("where").textContent = p.here ? "📍 " + cap(p.here) : "";
  const busy = !!S.task.current;
  Eyes.set({ label: S.emotion.label, talking: S.voice.talking, busy });
  $("mood").textContent = S.emotion.label;
  if (S.voice.last && S.voice.last !== refresh.lastSaid) { $("bubble").textContent = S.voice.last; refresh.lastSaid = S.voice.last; }

  // task card
  $("taskCard").hidden = !busy;
  if (busy) {
    $("taskText").textContent = "“" + S.task.current.text + "”";
    const st = S.task.current.step || "";
    $("taskStep").textContent = st.charAt(0).toUpperCase() + st.slice(1);
    $("loadedBtn").hidden = !S.task.current.waiting;
  }
  // moves (once)
  if (!$("moves").children.length) for (const m of S.moves) {
    const b = document.createElement("button"); b.textContent = MOVE_LABEL[m] || m;
    b.onclick = () => act(() => api("move", { name: m })); $("moves").appendChild(b);
  }
  // examples from her places
  const ex = [];
  const other = p.places.filter(x => x !== p.here);
  if (other[0]) ex.push(`Bring my remote from the ${other[0]}`, `Go to the ${other[0]}`);
  ex.push("Come here");
  const exKey = ex.join("|");
  if ($("examples").dataset.k !== exKey) {
    $("examples").dataset.k = exKey;
    $("examples").innerHTML = ex.map(e => `<span class="chip" role="button">${esc(e)}</span>`).join("");
    $("examples").querySelectorAll(".chip").forEach(c => c.onclick = () => { $("askIn").value = c.textContent; });
  }
  // chips
  const b = S.body, pi = S.pi, chips = [];
  if (b.sim) chips.push(["Simulated pins"]);
  if (b.reflex) chips.push(["⚠ " + b.reflex, 1]);
  if (b.distance_cm != null) chips.push([`Front ${b.distance_cm} cm`]);
  if (b.tray != null) chips.push([b.tray ? "Tray: loaded" : "Tray: empty"]);
  if (pi.temp_c != null) chips.push([`CPU ${pi.temp_c} °C`, pi.temp_c > 75]);
  if (pi.undervoltage_now) chips.push(["⚠ Power bank too weak", 1]);
  chips.push([`Voice: ${S.voice.state}`, /error|not installed/.test(S.voice.state)]);
  chips.push([`Awake ${Math.floor(S.uptime_s / 60)} min`]);
  $("chips").innerHTML = chips.map(([t, w]) => `<span class="chip${w ? " warn" : ""}">${esc(t)}</span>`).join("");
  // teaching banner
  $("teachCard").hidden = !p.teaching;
  if (p.teaching) $("teachTxt").textContent = `From the ${p.here} to the ${p.teaching.to} · ${p.teaching.seconds}s`;
  if (tab === "places") renderPlaces(p);
}

/* ---------- buttons with data-act ---------- */
const ACTS = {
  ask: () => { const t = $("askIn").value.trim(); if (!t) return; act(() => api("task", { text: t }), r => r).then(r => { if (r) $("askIn").value = ""; }); },
  say: () => { const t = $("sayIn").value.trim(); if (t) act(() => api("say", { text: t }), "Saying it").then(() => $("sayIn").value = ""); },
  taskCancel: () => act(() => api("task/cancel", {}), "Stopped"),
  taskConfirm: () => act(() => api("task/confirm", {}), "Thanks!"),
  stop: () => act(() => api("stop", {}), "Stopped"),
  teachStart: () => {
    const to = $("teachNew").value.trim() || $("teachTo").value;
    if (!to) return toast("Pick where to go", true);
    act(() => api("route/start", { to }), r => `Drive her to the ${r}`).then(r => { if (r) { $("teachNew").value = ""; show("drive"); } });
  },
  teachFinish: () => act(() => api("route/finish", {}), r => `Learned: ${r.from} → ${r.to} (${r.seconds}s)`),
  teachCancel: () => act(() => api("route/cancel", {}), "Cancelled"),
  addPlace: () => { const n = prompt("Name of the place (e.g. kitchen)"); if (n) act(() => api("places/add", { name: n }), "Added").then(loadPlaces); },
  scan: async () => {
    $("scanList").innerHTML = '<div class="hint">Scanning…</div>';
    try {
      const nets = await api("wifi/scan", {});
      $("scanList").innerHTML = nets.slice(0, 8).map(n => `<div class="item" data-ssid="${esc(n.ssid)}"><span class="name" style="text-transform:none">${esc(n.ssid)}</span><span class="meta">${n.signal}%</span></div>`).join("") || '<div class="hint">Nothing found</div>';
      $("scanList").querySelectorAll(".item").forEach(i => i.onclick = () => { $("wSsid").value = i.dataset.ssid; $("wPass").focus(); });
    } catch (e) { $("scanList").innerHTML = ""; toast(e.message, true); }
  },
  wifiAdd: () => act(() => api("wifi/add", { ssid: $("wSsid").value, password: $("wPass").value, priority: +$("wPrio").value || 0 }), "Saved 📶")
    .then(r => { if (r) { $("wSsid").value = $("wPass").value = ""; loadWifi(); } }),
  saveSet: () => act(() => api("settings", collectSettings()), r => r.restart ? "Saved. Restart Mochi to apply sensor changes." : "Saved ✓"),
  restart: () => { if (confirm("Restart Mochi's software now?")) act(() => api("restart", {}), "Restarting… back in a few seconds"); },
};
document.addEventListener("click", e => { const b = e.target.closest("[data-act]"); if (b && ACTS[b.dataset.act]) ACTS[b.dataset.act](); });
$("askIn").addEventListener("keydown", e => { if (e.key === "Enter") ACTS.ask(); });
$("sayIn").addEventListener("keydown", e => { if (e.key === "Enter") ACTS.say(); });

/* ---------- voice input: Android bridge, else the browser's speech recognition ---------- */
window.onSpeech = text => { $("micBtn").classList.remove("live"); if (text) { $("askIn").value = text; ACTS.ask(); } };
$("micBtn").onclick = () => {
  if (window.MochiApp && MochiApp.listen) { $("micBtn").classList.add("live"); MochiApp.listen(); return; }
  const R = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!R) return toast("Voice input needs the Mochi Android app", true);
  const r = new R(); r.lang = "en-IN"; r.onresult = e => onSpeech(e.results[0][0].transcript);
  r.onend = () => $("micBtn").classList.remove("live"); $("micBtn").classList.add("live"); r.start();
};

/* ---------- joystick ---------- */
const pad = $("pad"), knob = $("knob");
let vec = null, timer = null;
$("speed").oninput = () => $("speedVal").textContent = Math.round($("speed").value * 100) + "%";
function setKnob(x, y) { knob.style.transform = `translate(${x * 105}%, ${y * 105}%)`; }
function padMove(e) {
  const r = pad.getBoundingClientRect(), t = e.touches ? e.touches[0] : e;
  let x = (t.clientX - r.left) / r.width * 2 - 1, y = (t.clientY - r.top) / r.height * 2 - 1;
  const m = Math.hypot(x, y); if (m > 1) { x /= m; y /= m; }
  vec = [x, y]; setKnob(x, y); e.preventDefault && e.preventDefault();
}
function send() {
  if (!vec) return;
  const k = +$("speed").value, fwd = -vec[1], turn = vec[0] * 0.75;
  let l = fwd + turn, r = fwd - turn; const n = Math.max(1, Math.abs(l), Math.abs(r));
  fetch("/api/drive", { method: "POST", body: JSON.stringify({ l: l / n * k, r: r / n * k }) }).catch(() => {});
}
function padStart(e) { padMove(e); send(); clearInterval(timer); timer = setInterval(send, 100); if (navigator.vibrate) navigator.vibrate(12); }
function padEnd() { if (!vec) return; vec = null; clearInterval(timer); setKnob(0, 0); fetch("/api/stop", { method: "POST", body: "{}" }).catch(() => {}); }
pad.addEventListener("touchstart", padStart, { passive: false });
pad.addEventListener("touchmove", padMove, { passive: false });
pad.addEventListener("touchend", padEnd); pad.addEventListener("touchcancel", padEnd);
pad.addEventListener("mousedown", e => {
  padStart(e); const mm = ev => padMove(ev);
  window.addEventListener("mousemove", mm);
  window.addEventListener("mouseup", () => { window.removeEventListener("mousemove", mm); padEnd(); }, { once: true });
});
document.addEventListener("visibilitychange", () => { if (document.hidden) padEnd(); });

/* ---------- camera (only while the Drive tab is open) ---------- */
let camBusy = false;
function camLoop() {
  if (tab !== "drive" || camBusy) return;
  if (!S || !S.camera) return;
  camBusy = true;
  const img = new Image();
  img.onload = () => { $("cam").innerHTML = ""; $("cam").appendChild(img); camBusy = false; setTimeout(camLoop, 150); };
  img.onerror = () => { $("cam").textContent = "Can't reach the robot phone's camera."; camBusy = false; setTimeout(camLoop, 2000); };
  img.src = "/camera.jpg?t=" + Date.now();
}

/* ---------- places ---------- */
async function loadPlaces() { try { renderPlaces(await api("places")); } catch (e) {} }
function renderPlaces(p) {
  const opts = (sel, cur, none) => {
    const html = `<option value="">${none}</option>` + p.places.map(x => `<option value="${esc(x)}"${x === cur ? " selected" : ""}>${esc(cap(x))}</option>`).join("");
    if ($(sel).dataset.h !== html && document.activeElement !== $(sel)) { $(sel).innerHTML = html; $(sel).dataset.h = html; }
  };
  opts("hereSel", p.here, "— not set —");
  opts("ownerSel", p.owner, "— not set —");
  const toHtml = p.places.filter(x => x !== p.here).map(x => `<option value="${esc(x)}">${esc(cap(x))}</option>`).join("") || '<option value="">(add a place)</option>';
  if ($("teachTo").dataset.h !== toHtml && document.activeElement !== $("teachTo")) { $("teachTo").innerHTML = toHtml; $("teachTo").dataset.h = toHtml; }
  const pl = p.places.map(x => `<div class="item"><span class="name">${esc(x)}</span>${x === p.here ? '<span class="tag">Mochi</span>' : ""}${x === p.owner ? '<span class="tag">You</span>' : ""}<button class="small ghost" data-rm="${esc(x)}">✕</button></div>`).join("")
    || '<div class="hint">No places yet. Add the rooms of your home.</div>';
  if ($("placeList").dataset.h !== pl) { $("placeList").innerHTML = pl; $("placeList").dataset.h = pl; }
  const rl = p.routes.map(r => `<div class="item"><span class="name">${esc(r.from)} ⇄ ${esc(r.to)}</span><span class="meta">${r.seconds}s</span><button class="small ghost" data-rf="${esc(r.from)}" data-rt="${esc(r.to)}">✕</button></div>`).join("")
    || '<div class="hint">No routes yet. Teach her one above.</div>';
  if ($("routeList").dataset.h !== rl) { $("routeList").innerHTML = rl; $("routeList").dataset.h = rl; }
  const hist = (S && S.task.history || []).slice().reverse();
  $("histList").innerHTML = hist.map(h => `<div class="item"><span class="name" style="text-transform:none">${esc(h.text)}</span><span class="meta">${esc(h.result.split(":")[0])}</span></div>`).join("") || '<div class="hint">Nothing yet.</div>';
}
$("hereSel").onchange = () => act(() => api("places/here", { name: $("hereSel").value }), "Got it");
$("ownerSel").onchange = () => act(() => api("places/owner", { name: $("ownerSel").value }), "Got it");
$("placeList").onclick = e => { const n = e.target.dataset.rm; if (n && confirm(`Remove ${n} and its routes?`)) act(() => api("places/remove", { name: n }), "Removed").then(loadPlaces); };
$("routeList").onclick = e => { const f = e.target.dataset.rf; if (f && confirm("Delete this route?")) act(() => api("route/delete", { from: f, to: e.target.dataset.rt }), "Deleted").then(loadPlaces); };

/* ---------- wifi ---------- */
async function loadWifi() {
  try {
    const w = await api("wifi");
    $("wifiCur").textContent = w.hotspot ? `Own hotspot: ${w.hotspot_name}` : (w.current || "Not connected");
    $("wifiInfo").textContent = [w.ip && `IP ${w.ip}`, w.signal != null && `signal ${w.signal}%`].filter(Boolean).join(" · ");
    $("hotspotSw").checked = !!w.hotspot;
    $("wifiNote").textContent = w.note || (w.hotspot ? "Phones connect to her hotspot and open this app at 10.42.0.1:8080." : "");
    $("wifiList").innerHTML = (w.saved || []).map(n => `<div class="item"><span class="name" style="text-transform:none">${esc(n.name.replace(/^pet-/, ""))}</span>${n.name === w.current ? '<span class="tag">connected</span>' : `<button class="small" data-con="${esc(n.name)}">Connect</button>`}<span class="meta">p${n.priority}</span><button class="small ghost" data-del="${esc(n.name)}">✕</button></div>`).join("") || '<div class="hint">None saved.</div>';
  } catch (e) { toast("Couldn't read Wi-Fi", true); }
}
$("wifiList").onclick = e => {
  const c = e.target.dataset.con, d = e.target.dataset.del;
  if (c && confirm(`Switch Mochi to ${c.replace(/^pet-/, "")}? If your phone isn't on that network, the app will lose her until it is.`)) act(() => api("wifi/connect", { name: c }), "Switching…");
  if (d && confirm(`Forget ${d.replace(/^pet-/, "")}?`)) act(() => api("wifi/remove", { name: d }), "Forgotten").then(loadWifi);
};
$("hotspotSw").onchange = () => {
  const on = $("hotspotSw").checked;
  if (!confirm(on ? "Start her own hotspot? She leaves your Wi-Fi; join her hotspot from your phone." : "Stop her hotspot and rejoin saved Wi-Fi?")) { $("hotspotSw").checked = !on; return; }
  act(() => api("wifi/hotspot", { on }), on ? "Hotspot starting" : "Hotspot off");
};

/* ---------- settings (built from the Pi's list) ---------- */
let SET = null;
async function loadSettings() {
  try { SET = await api("settings"); } catch (e) { return; }
  const groups = {};
  for (const s of SET.schema) (groups[s.section] = groups[s.section] || []).push(s);
  $("setForm").innerHTML = Object.entries(groups).map(([sec, list]) => `<div class="card"><h2>${esc(sec)}</h2>${list.map(row).join("")}</div>`).join("");
  $("setForm").querySelectorAll("input[type=range]").forEach(r => r.oninput = () => r.nextElementSibling.textContent = r.value);
  $("appInfo").textContent = `Connected to ${location.host}` + (window.MochiApp ? " · Android app" : " · browser");
  $("findBtn").hidden = !(window.MochiApp && MochiApp.home);
}
function row(s) {
  const v = SET.values[s.key], id = "s_" + s.key.replace(/\W/g, "_");
  let input;
  if (s.kind === "bool") input = `<label class="switch"><input type="checkbox" id="${id}"${v ? " checked" : ""}><span></span></label>`;
  else if (s.kind === "float" || s.kind === "int") input = `<input type="range" id="${id}" min="${s.min}" max="${s.max}" step="${s.step}" value="${v}"><span class="val">${v}</span>`;
  else if (s.kind === "choice") input = `<select id="${id}">${s.choices.map(c => `<option${c === v ? " selected" : ""}>${esc(c)}</option>`).join("")}</select>`;
  else if (s.kind === "secret") input = `<input type="password" id="${id}" placeholder="${v ? "unchanged" : "not set"}" autocomplete="new-password">`;
  else input = `<input type="text" id="${id}" value="${esc(v)}">`;
  return `<div class="set"><span class="lab">${esc(s.label)}${s.restart ? ' <span class="hint">(restart)</span>' : ""}</span>${input}</div>`;
}
function collectSettings() {
  const out = {};
  for (const s of SET.schema) {
    const el = $("s_" + s.key.replace(/\W/g, "_")); if (!el) continue;
    const v = s.kind === "bool" ? el.checked : el.value;
    if (s.kind === "secret" && !v) continue;
    if (String(v) !== String(SET.values[s.key])) out[s.key] = v;
  }
  return out;
}
$("findBtn").onclick = () => window.MochiApp && MochiApp.home();

/* ---------- go ---------- */
Eyes.start($("eyes"));
// she glances at whatever you touch (anthropomorphic, but abstract: just her eyes)
document.addEventListener("pointerdown", e => {
  const r = $("eyes").getBoundingClientRect();
  if (!r.width) return;
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  Eyes.lookAt((e.clientX - cx) / (window.innerWidth / 2), (e.clientY - cy) / (window.innerHeight / 2));
}, { passive: true });
refresh();
setInterval(refresh, 1000);
