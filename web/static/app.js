const token = document.body.dataset.token;
const appKey = document.body.dataset.appkey;
let seenAvailable = null;   // Set of "shop|title" keys currently qualifying (null = first load)

function esc(s) {
  return (s + "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function b64ToU8(base64) {
  const pad = "=".repeat((4 - (base64.length % 4)) % 4);
  const b = (base64 + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

// ── Sound (Web Audio; needs a user gesture to unlock, so we resume on click) ──
let audioCtx = null;
function initAudio() {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
  } catch (e) { /* ignore */ }
}
document.addEventListener("click", initAudio);

function tone(freq, start, dur) {
  const o = audioCtx.createOscillator(), g = audioCtx.createGain();
  o.type = "sine"; o.frequency.value = freq;
  o.connect(g); g.connect(audioCtx.destination);
  const t = audioCtx.currentTime + start;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.35, t + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.start(t); o.stop(t + dur + 0.02);
}
function ping() {
  initAudio();
  if (!audioCtx) return;
  tone(880, 0, 0.35);     // two-note "ping"
  tone(1175, 0.18, 0.45);
}

// ── Popup ─────────────────────────────────────────────────────────────────
function showDeals(deals) {
  const list = document.getElementById("dealList");
  list.innerHTML = deals.map(d =>
    `<div class="deal">${esc(d.shop || "")} — <b>${d.price.toFixed(2)} €</b>` +
    `<br><span class="muted">${esc(d.title || "")}</span> ` +
    (d.url ? `<a href="${esc(d.url)}" target="_blank" rel="noopener">↗ öffnen</a>` : "") +
    `</div>`).join("");
  document.getElementById("dealModal").hidden = false;
}
document.getElementById("dealClose").onclick = () => {
  document.getElementById("dealModal").hidden = true;
};

// ── Results ──────────────────────────────────────────────────────────────
async function loadResults() {
  try {
    const r = await fetch(`/api/results?token=${token}`);
    const d = await r.json();
    document.getElementById("updated").textContent = `Stand: ${d.updated_human} · ${d.city}`;
    const tb = document.querySelector("#results tbody");
    tb.innerHTML = "";
    for (const it of d.results) {
      const price = (it.price != null) ? it.price.toFixed(2) + " €" : "—";
      const status = it.in_stock === true ? "✅" : (it.in_stock === false ? "❌" : (it.error ? "⚠️" : "❓"));
      const link = it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">↗</a>` : "";
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(it.shop || "")}</td><td>${esc(it.title || "")}</td>` +
        `<td>${price}</td><td title="${esc(it.error || "")}">${status}</td><td>${link}</td>`;
      tb.appendChild(tr);
    }
    if (!d.results.length) tb.innerHTML = `<tr><td colspan="5" class="muted">Noch keine Daten — der erste Scan läuft…</td></tr>`;

    // Detect NEW available products within budget -> ping + popup.
    const min = (d.min_price == null) ? 0 : d.min_price;
    const max = (d.max_price == null) ? Infinity : d.max_price;
    const qualifying = d.results.filter(it =>
      it.in_stock === true && typeof it.price === "number" && it.price >= min && it.price <= max);
    const curKeys = new Set(qualifying.map(it => it.shop + "|" + it.title));
    if (seenAvailable !== null) {
      const fresh = qualifying.filter(it => !seenAvailable.has(it.shop + "|" + it.title));
      if (fresh.length) { ping(); showDeals(fresh); }
    }
    seenAvailable = curKeys;
  } catch (e) {
    document.getElementById("updated").textContent = "Fehler beim Laden";
  }
}

// ── Push ─────────────────────────────────────────────────────────────────
async function enableNotifications() {
  initAudio();
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    alert("Push wird hier nicht unterstützt.\nAuf dem iPhone: Seite über Teilen → „Zum Home-Bildschirm“ hinzufügen und von dort öffnen.");
    return;
  }
  try {
    const reg = await navigator.serviceWorker.register("/sw.js");
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { alert("Benachrichtigungen wurden nicht erlaubt."); return; }
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: b64ToU8(appKey),
    });
    await fetch(`/w/${token}/subscribe`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sub),
    });
    await fetch(`/w/${token}/test-push`, { method: "POST" });
    alert("Benachrichtigungen aktiviert ✅ (Test-Push gesendet)");
  } catch (e) {
    alert("Aktivierung fehlgeschlagen: " + e);
  }
}

document.getElementById("notifyBtn").onclick = enableNotifications;
document.getElementById("refreshBtn").onclick = loadResults;
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
loadResults();
setInterval(loadResults, 60000);
