const token = document.body.dataset.token;
const appKey = document.body.dataset.appkey;
let seenAvailable = null;   // Set of "shop|title" keys currently qualifying (null = first load)
let appVersion = null;      // build id we loaded with; if the server reports a newer one, prompt refresh

function showUpdateBanner() {
  const b = document.getElementById("updateBar");
  if (b) b.hidden = false;
}

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
    // Detect a new deployment: remember the first version we see; if the server
    // later reports a different one, the page is running stale code → prompt refresh.
    if (d.version) {
      if (appVersion === null) appVersion = d.version;
      else if (d.version !== appVersion) showUpdateBanner();
    }
    const tsLabel = d.updated
      ? new Date(d.updated * 1000).toLocaleString("de-DE", {day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"})
      : "—";
    const staleTxt = d.stale ? ` <span class="stale">⚠️ veraltet</span>` : "";
    document.getElementById("updated").innerHTML = `Stand: ${esc(tsLabel)} · ${esc(d.city || "")}${staleTxt}`;
    const min = (d.min_price == null) ? 0 : d.min_price;
    const max = (d.max_price == null) ? Infinity : d.max_price;

    const tb = document.querySelector("#results tbody");
    tb.innerHTML = "";
    for (const it of d.results) {
      const hasPrice = typeof it.price === "number";
      const inBudget = hasPrice && it.price >= min && it.price <= max;
      const overBudget = hasPrice && it.price > max;
      const underBudget = hasPrice && it.price < min;

      const priceText = hasPrice ? it.price.toFixed(2) + " €" : "—";
      const budgetNote = overBudget ? " ↑" : (underBudget ? " ↓" : "");
      const status = it.in_stock === true ? "✅" : (it.in_stock === false ? "❌" : (it.error ? "⚠️" : "❓"));
      const link = it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">↗</a>` : "";

      const tr = document.createElement("tr");
      if (it.in_stock === true && inBudget) tr.classList.add("in-budget");
      else if (overBudget || underBudget) tr.classList.add("out-of-budget");
      if (it.error) tr.classList.add("blocked");

      const priceTitle = overBudget ? `Über Budget (max ${max.toFixed(0)} €)`
                       : underBudget ? `Unter Budget (min ${min.toFixed(0)} €)` : "";
      // data-label drives the mobile card layout (see style.css @media).
      tr.innerHTML = `<td data-label="Shop">${esc(it.shop || "")}</td>` +
        `<td data-label="Produkt">${esc(it.title || "")}</td>` +
        `<td data-label="Preis" title="${priceTitle}">${priceText}<span class="budget-note">${budgetNote}</span></td>` +
        `<td data-label="Status" title="${esc(it.error || "")}">${status}</td>` +
        `<td data-label="Link">${link}</td>`;
      tb.appendChild(tr);
    }
    if (!d.results.length) {
      tb.innerHTML = `<tr><td colspan="5" class="muted">Noch keine Daten — der erste Scan läuft…</td></tr>`;
    } else if (d.results.every(it => it.error)) {
      tb.innerHTML = `<tr><td colspan="5" class="muted">⚠️ Alle Shops sind aktuell blockiert oder nicht erreichbar — bitte später erneut versuchen.</td></tr>`;
    }

    // Detect NEW available products within budget -> ping + popup.
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

// Refresh button with a spinning-icon busy state.
async function refreshResults() {
  const btn = document.getElementById("refreshBtn");
  if (btn) { btn.disabled = true; btn.classList.add("spinning"); }
  try { await loadResults(); }
  finally { if (btn) { btn.disabled = false; btn.classList.remove("spinning"); } }
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
document.getElementById("refreshBtn").onclick = refreshResults;
const _upBtn = document.getElementById("updateReload");
if (_upBtn) _upBtn.onclick = () => location.reload();

const _delBtn = document.getElementById("deleteBtn");
if (_delBtn) _delBtn.onclick = async () => {
  if (!confirm("Diesen Watch wirklich löschen? Der Link wird ungültig und Benachrichtigungen werden gestoppt.")) return;
  try {
    if ("serviceWorker" in navigator) {
      const reg = await navigator.serviceWorker.getRegistration();
      const sub = reg && await reg.pushManager.getSubscription();
      if (sub) await sub.unsubscribe();
    }
  } catch (e) { /* ignore unsubscribe errors */ }
  // Native form submit follows the server's 303 redirect back to "/".
  const f = document.createElement("form");
  f.method = "POST"; f.action = `/w/${token}/delete`;
  document.body.appendChild(f); f.submit();
};
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
loadResults();
setInterval(loadResults, 60000);
