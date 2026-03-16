// import_by_scan.js

const STORAGE_KEY = "snipeops_import_by_scan_defaults_v1";

// ---- helpers ----
function $(id){ return document.getElementById(id); }

function setStatus(el, msg, ok=true){
  el.textContent = msg;
  el.classList.remove("bad", "ok", "shake");
  el.classList.add(ok ? "ok" : "bad");

  if (!ok){
    // trigger shake
    void el.offsetWidth; // reflow
    el.classList.add("shake");
  }
}

function readDefaultsFromForm(){
  // NOTE: asset_tag is intentionally NOT included here.
  // It's treated as a one-off override per scan (and will be cleared after scanning).
  return {
    model_id: $("model_id").value || null,
    status_id: $("status_id").value || null,
    location_id: $("location_id").value || null,
    depreciation_id: $("depreciation_id").value || null,
    supplier_id: $("supplier_id").value || null,

    purchase_cost: ($("purchase_cost").value || "").trim() || null,
    purchase_date: $("purchase_date").value || null,
    order_number: ($("order_number").value || "").trim() || null,
    warranty_months: ($("warranty_months").value || "").trim() || null,
  };
}

function applyDefaultsToForm(d){
  if (!d) return;
  if (d.model_id != null) $("model_id").value = d.model_id;
  if (d.status_id != null) $("status_id").value = d.status_id;
  if (d.location_id != null) $("location_id").value = d.location_id;
  if (d.depreciation_id != null) $("depreciation_id").value = d.depreciation_id;
  if (d.supplier_id != null) $("supplier_id").value = d.supplier_id;

  $("purchase_cost").value = d.purchase_cost ?? "";
  $("purchase_date").value = d.purchase_date ?? "";
  $("order_number").value = d.order_number ?? "";
  $("warranty_months").value = d.warranty_months ?? "";

  // asset_tag intentionally NOT applied from defaults
}

function saveDefaults(){
  const d = readDefaultsFromForm();
  localStorage.setItem(STORAGE_KEY, JSON.stringify(d));
  setStatus($("defaultsStatus"), "Defaults saved.", true);
}

function resetDefaults(){
  localStorage.removeItem(STORAGE_KEY);
  applyDefaultsToForm({
    model_id: "",
    status_id: "",
    location_id: "",
    depreciation_id: "",
    supplier_id: "",
    purchase_cost: "",
    purchase_date: "",
    order_number: "",
    warranty_months: "",
  });

  // Clear one-off asset tag too
  const assetTagEl = $("asset_tag");
  if (assetTagEl) assetTagEl.value = "";

  setStatus($("defaultsStatus"), "Defaults cleared.", true);
}

function loadSavedDefaults(){
  try{
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  }catch(e){
    return null;
  }
}

function formatTimestampDisplay(ts){
  if (!ts) return "";

  // If it's already in pretty format (no "T"), leave it alone
  if (typeof ts === "string" && !ts.includes("T")) return ts;

  // Try parsing ISO like: 2026-03-03T12:10:19-06:00
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);

  // Format: 03/03/2026 12:10 PM
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const yyyy = d.getFullYear();

  let hours = d.getHours();
  const minutes = String(d.getMinutes()).padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  hours = hours ? hours : 12;

  return `${mm}/${dd}/${yyyy} ${hours}:${minutes} ${ampm}`;
}

function prependRecentRow({timestamp, serial, ok, asset_tag, asset_url, message}){
  const tbody = $("recentBody");
  const tr = document.createElement("tr");
  tr.className = ok ? "ok" : "bad";

  const goLink = asset_url
    ? `<a href="${asset_url}" target="_blank" rel="noopener">Go to Asset</a>`
    : "—";

  tr.innerHTML = `
    <td class="mono">${formatTimestampDisplay(timestamp)}</td>
    <td class="mono">${goLink}</td>
    <td class="mono">${serial || ""}</td>
    <td class="mono">${asset_tag || ""}</td>
    <td>${ok ? "Created" : "Error"}</td>
    <td class="muted">${message || ""}</td>
  `;

  tbody.prepend(tr);
}

// ---- main ----
document.addEventListener("DOMContentLoaded", async () => {
  $("saveDefaults")?.addEventListener("click", saveDefaults);
  $("resetDefaults")?.addEventListener("click", resetDefaults);

  const saved = loadSavedDefaults();
  if (saved){
    applyDefaultsToForm(saved);
    setStatus($("defaultsStatus"), "Defaults loaded from this device.", true);
  } else {
    setStatus($("defaultsStatus"), "No saved defaults yet.", true);
  }

  $("scanForm").addEventListener("submit", async (e) => {
    e.preventDefault();

    const serialEl = $("serial");
    const statusEl = $("status");
    const assetTagEl = $("asset_tag"); // one-off override field

    // scanner timing safety
    await new Promise(r => setTimeout(r, 0));

    const serial = (serialEl.value || "").trim();
    if (!serial){
      setStatus(statusEl, "Scan a serial first.", false);
      serialEl.focus();
      return;
    }

    const modelId = $("model_id").value;
    if (!modelId){
      setStatus(statusEl, "Select a model before scanning.", false);
      return;
    }

    const defaults = readDefaultsFromForm();

    // Save defaults (does NOT include asset_tag)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(defaults));

    // Read one-off asset_tag and send it, but do NOT persist it
    const asset_tag = (assetTagEl?.value || "").trim() || null;

    setStatus(statusEl, "Creating…", true);

    try{
      const resp = await fetch("/import-by-scan/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ serial, ...defaults, asset_tag })
      });

      const contentType = resp.headers.get("content-type") || "";
      const rawText = await resp.text();

      let data = null;
      if (contentType.includes("application/json")) {
        try { data = JSON.parse(rawText); } catch (e) { /* ignore */ }
      }

      if (!resp.ok) {
        const msg =
          (data && (data.message || data.error)) ||
          `HTTP ${resp.status}: ${rawText.slice(0, 200)}`;

        setStatus(statusEl, msg, false);
        console.error("Scan failed:", { status: resp.status, rawText, data });
        return;
      }

      if (!data) {
        setStatus(statusEl, "Server returned success but not JSON.", true);
        console.warn("Non-JSON success response:", rawText);
      } else {
        if (data.ok === false) {
          const msg = data.error || data.message || "Error creating asset.";
          setStatus(statusEl, msg, false);

          prependRecentRow({
            timestamp: data.timestamp_display || data.timestamp || new Date().toLocaleString(),
            serial,
            ok: false,
            asset_tag: data.asset_tag || "",
            asset_url: data.asset_url || "",
            message: msg,
          });

          serialEl.value = "";
          if (assetTagEl) assetTagEl.value = ""; // clear one-off field after attempt
          serialEl.focus();
          return;
        }

        setStatus(statusEl, data.message || "Created.", true);

        prependRecentRow({
          timestamp: data.timestamp_display || data.timestamp || new Date().toLocaleString(),
          serial,
          ok: true,
          asset_tag: data.asset_tag || "",
          asset_url: data.asset_url || "",
          message: data.message || "Created",
        });
      }

      serialEl.value = "";
      if (assetTagEl) assetTagEl.value = ""; // clear one-off field after attempt
      serialEl.focus();

    }catch(err){
      setStatus(statusEl, "Request failed (network/server).", false);
    }
  });
});