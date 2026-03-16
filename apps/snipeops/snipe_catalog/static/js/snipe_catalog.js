const TAB_CONFIG = {
  models: {
    title: "Models",
    endpoint: "/snipe-catalog/api/models",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Model" },
      { key: "manufacturer_name", label: "Manufacturer" },
      { key: "model_number", label: "Model #" }
    ]
  },
  locations: {
    title: "Locations",
    endpoint: "/snipe-catalog/api/locations",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Location" }
    ]
  },
  statuslabels: {
    title: "Status Labels",
    endpoint: "/snipe-catalog/api/statuslabels",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Label" }
    ]
  },
  suppliers: {
    title: "Suppliers",
    endpoint: "/snipe-catalog/api/suppliers",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Supplier" }
    ]
  },
  depreciations: {
    title: "Depreciations",
    endpoint: "/snipe-catalog/api/depreciations",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Depreciation Name" }
    ]
  }
};

let activeTab = "models";
let activeRows = [];

async function fetchRows(endpoint) {
  const res = await fetch(endpoint);
  const data = await res.json();
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || "Request failed");
  }
  return data.rows || [];
}

function formatLocalDate(isoString) {
  if (!isoString) return "Never";

  const APP_TIMEZONE = window.APP_CONFIG?.timezone || "UTC";

  const d = new Date(isoString);
  if (isNaN(d)) return isoString;

  return d.toLocaleString("en-US", {
    timeZone: APP_TIMEZONE,
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true
  });
}

function renderTable(rows) {
  const cfg = TAB_CONFIG[activeTab];
  const head = document.getElementById("tableHead");
  const body = document.getElementById("tableBody");

  head.innerHTML = "";
  body.innerHTML = "";

  // Build header
  cfg.columns.forEach(col => {
    const th = document.createElement("th");
    th.textContent = col.label;
    head.appendChild(th);
  });

  // Filter
  const q = document.getElementById("filterBox").value.toLowerCase();
  if (q) {
    rows = rows.filter(r =>
      JSON.stringify(r).toLowerCase().includes(q)
    );
  }

  document.getElementById("countHint").textContent =
    rows.length.toLocaleString() + " row(s)";

  // Build rows
  rows.forEach(row => {
    const tr = document.createElement("tr");

    cfg.columns.forEach(col => {
      const td = document.createElement("td");
      td.textContent = row[col.key] || "";
      tr.appendChild(td);
    });

    body.appendChild(tr);
  });
}

async function loadActiveTab() {
  const cfg = TAB_CONFIG[activeTab];
  document.getElementById("panelTitle").textContent = cfg.title;

  try {
    activeRows = await fetchRows(cfg.endpoint);
    renderTable(activeRows);
  } catch (e) {
    console.error(e);
  }
}

function setActiveTab(tab) {
  activeTab = tab;

  document.querySelectorAll(".catalog-tab").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });

  document.getElementById("filterBox").value = "";
  loadActiveTab();
}

async function runSync() {
  const btn = document.getElementById("syncBtn");
  btn.disabled = true;
  document.getElementById("syncStatus").textContent = "Syncing...";

  try {
    const res = await fetch("/snipe-catalog/sync", { method: "POST" });
    const data = await res.json();
    if (!res.ok || data.ok === false) throw new Error();

    document.getElementById("syncStatus").textContent = "Sync complete.";

    const nowIso = new Date().toISOString();
    const lastSyncEl = document.getElementById("lastSync");
    lastSyncEl.dataset.utc = nowIso;
    lastSyncEl.textContent = formatLocalDate(nowIso);

    await loadActiveTab();
  } catch {
    document.getElementById("syncStatus").textContent = "Sync failed.";
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  // Format initial lastSync from server
  const lastSyncEl = document.getElementById("lastSync");
  const utcValue = lastSyncEl.dataset.utc;
  if (utcValue) {
    lastSyncEl.textContent = formatLocalDate(utcValue);
  }
  document.querySelectorAll(".catalog-tab").forEach(btn => {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
  });

  document.getElementById("filterBox")
    .addEventListener("input", () => renderTable(activeRows));

  document.getElementById("syncBtn")
    .addEventListener("click", runSync);

  setActiveTab("models");
});