const token = document.body.dataset.token;
const appKey = document.body.dataset.appkey;

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
  } catch (e) {
    document.getElementById("updated").textContent = "Fehler beim Laden";
  }
}

async function enableNotifications() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    alert("Push wird hier nicht unterstützt.\nAuf dem iPhone: Seite über Teilen → „Zum Home-Bildschirm“ hinzufügen und von dort öffnen.");
    return;
  }
  try {
    const reg = await navigator.serviceWorker.register("/sw.js");
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { alert("Benachrichtigungen wurden nicht erlaubt."); return; }
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: b64ToU8(appKey),
    });
    await fetch(`/w/${token}/subscribe`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sub),
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
