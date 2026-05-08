const TAB_CONFIG = {
  models: {
    title: "Models",
    help: "Snipe-IT asset models cached locally for sync and dropdowns.",
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
    help: "Snipe-IT locations cached locally for create and update workflows.",
    endpoint: "/snipe-catalog/api/locations",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Location" }
    ]
  },
  statuslabels: {
    title: "Status Labels",
    help: "Snipe-IT status labels. Assets must use a deployable status before checkout.",
    endpoint: "/snipe-catalog/api/statuslabels",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Label" }
    ]
  },
  suppliers: {
    title: "Suppliers",
    help: "Snipe-IT suppliers cached locally.",
    endpoint: "/snipe-catalog/api/suppliers",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Supplier" }
    ]
  },
  depreciations: {
    title: "Depreciations",
    help: "Snipe-IT depreciation records cached locally.",
    endpoint: "/snipe-catalog/api/depreciations",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Depreciation Name" }
    ]
  },

  categories: {
    title: "Categories",
    help: "Snipe-IT categories used when creating new models from Catalog.",
    endpoint: "/snipe-catalog/api/categories",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Category" }
    ]
  },

  manufacturers: {
    title: "Manufacturers",
    help: "Snipe-IT manufacturers used when creating new models from Catalog.",
    endpoint: "/snipe-catalog/api/manufacturers",
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "Manufacturer" }
    ]
  },
  
  modelMappings: {
    title: "Model Mapping",
    help: "Map raw Intune and Mosyle model values to friendly Snipe-IT model names."
  },
};

let activeTab = "models";
let activeRows = [];
let mappingRows = [];
let mappingModels = [];
let mappingCategories = [];
let mappingManufacturers = [];

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

  const appTimezone = window.APP_CONFIG?.timezone || "UTC";
  const d = new Date(isoString);

  if (isNaN(d)) return isoString;

  return d.toLocaleString("en-US", {
    timeZone: appTimezone,
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true
  });
}

function setPanelMode(tab) {
  const isMapping = tab === "modelMappings";

  document.getElementById("standardPanel").hidden = isMapping;
  document.getElementById("modelMappingPanel").hidden = !isMapping;
  document.getElementById("filterBox").hidden = isMapping;
}

function renderTable(rows) {
  const cfg = TAB_CONFIG[activeTab];
  const head = document.getElementById("tableHead");
  const body = document.getElementById("tableBody");

  head.innerHTML = "";
  body.innerHTML = "";

  cfg.columns.forEach(col => {
    const th = document.createElement("th");
    th.textContent = col.label;
    head.appendChild(th);
  });

  const q = document.getElementById("filterBox").value.toLowerCase();

  if (q) {
    rows = rows.filter(row => JSON.stringify(row).toLowerCase().includes(q));
  }

  document.getElementById("countHint").textContent =
    rows.length.toLocaleString() + " row(s)";

  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = cfg.columns.length;
    td.textContent = "No rows found.";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }

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
  document.getElementById("panelHelp").textContent = cfg.help || "";
  setPanelMode(activeTab);

  if (activeTab === "modelMappings") {
    document.getElementById("countHint").textContent =
      mappingRows.length ? mappingRows.length.toLocaleString() + " model value(s)" : "";
    return;
  }

  try {
    activeRows = await fetchRows(cfg.endpoint);
    renderTable(activeRows);
  } catch (e) {
    console.error(e);
    document.getElementById("countHint").textContent = "Load failed.";
  }
}

function setActiveTab(tab) {
  activeTab = tab;

  document.querySelectorAll(".catalog-tab").forEach(btn => {
    const isActive = btn.dataset.tab === tab;
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-selected", isActive ? "true" : "false");
  });

  document.getElementById("filterBox").value = "";
  loadActiveTab();
}

async function runSync() {
  const btn = document.getElementById("syncBtn");
  const status = document.getElementById("syncStatus");

  btn.disabled = true;
  status.textContent = "Syncing...";

  try {
    const res = await fetch("/snipe-catalog/sync", { method: "POST" });
    const data = await res.json();

    if (!res.ok || data.ok === false) {
      throw new Error(data.error || "Sync failed.");
    }

    status.textContent = "Sync complete.";

    const nowIso = new Date().toISOString();
    const lastSyncEl = document.getElementById("lastSync");

    lastSyncEl.dataset.utc = nowIso;
    lastSyncEl.textContent = formatLocalDate(nowIso);

    await loadActiveTab();
  } catch (err) {
    status.textContent = err.message || "Sync failed.";
  } finally {
    btn.disabled = false;
  }
}

function modelOptionLabel(model) {
  if (model.display) return model.display;

  if (model.name && model.model_number) {
    return `${model.name} — ${model.model_number}`;
  }

  return model.name || model.model_number || "";
}

function buildModelSelect(row) {
  const select = document.createElement("select");
  select.className = "snipeops-input";
  select.dataset.rawValue = row.raw_value;

  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "Leave unmapped";
  select.appendChild(empty);

  mappingModels.forEach(model => {
    const option = document.createElement("option");
    const label = modelOptionLabel(model);

    option.value = model.name || "";
    option.textContent = label;

    if (row.mapped_value && row.mapped_value === option.value) {
      option.selected = true;
    }

    select.appendChild(option);
  });

  return select;
}

function renderMappingRows() {
  const body = document.getElementById("mappingTableBody");
  body.innerHTML = "";

  const q = document.getElementById("filterBox").value.toLowerCase();

  let rows = mappingRows;
  if (q) {
    rows = rows.filter(row => JSON.stringify(row).toLowerCase().includes(q));
  }

  document.getElementById("countHint").textContent =
    rows.length.toLocaleString() + " model value(s)";

  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");

    td.colSpan = 5;
    td.textContent = "No discovered model values found.";

    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }

  rows.forEach(row => {
    const tr = document.createElement("tr");

    const rawTd = document.createElement("td");
    rawTd.innerHTML = `<strong>${row.raw_value || ""}</strong>`;

    const sourceTd = document.createElement("td");
    sourceTd.textContent = row.source || "";

    const countTd = document.createElement("td");
    countTd.textContent = row.count || 0;

    const currentTd = document.createElement("td");
    currentTd.textContent = row.mapped_value || "—";

    const mapTd = document.createElement("td");
    mapTd.className = "catalog-model-map-cell";

    mapTd.appendChild(buildModelSelect(row));

    const createBtn = document.createElement("button");
    createBtn.type = "button";
    createBtn.className = "snipeops-btn snipeops-btn-secondary catalog-create-model-row-btn";
    createBtn.textContent = "Create New Model";
    createBtn.addEventListener("click", () => openCreateModelModal(row));

    mapTd.appendChild(createBtn);

    tr.appendChild(rawTd);
    tr.appendChild(sourceTd);
    tr.appendChild(countTd);
    tr.appendChild(currentTd);
    tr.appendChild(mapTd);

    body.appendChild(tr);
  });
}

async function loadModelMappings() {
  const source = document.getElementById("mappingSource").value;
  const limit = document.getElementById("mappingLimit").value || "all";
  const status = document.getElementById("mappingStatus");
  const btn = document.getElementById("loadMappingsBtn");

  btn.disabled = true;
  document.getElementById("saveMappingsBtn").disabled = true;
  status.textContent = "Loading discovered model values...";

  try {
    const res = await fetch(
      `/snipe-catalog/api/model-mappings?source=${encodeURIComponent(source)}&limit=${encodeURIComponent(limit)}`
    );
    const data = await res.json();

    if (!res.ok || data.ok === false) {
      throw new Error(data.error || "Failed to load model mappings.");
    }

    mappingRows = data.rows || [];
    mappingModels = data.models || [];
    mappingCategories = data.categories || [];
    mappingManufacturers = data.manufacturers || [];

    status.textContent = `Loaded ${mappingRows.length.toLocaleString()} discovered model value(s).`;
    document.getElementById("saveMappingsBtn").disabled = false;

    renderMappingRows();
  } catch (err) {
    status.textContent = err.message || "Failed to load model mappings.";
  } finally {
    btn.disabled = false;
  }
}

async function saveModelMappings() {
  const source = document.getElementById("mappingSource").value;
  const status = document.getElementById("mappingStatus");
  const btn = document.getElementById("saveMappingsBtn");

  const mappings = Array.from(
    document.querySelectorAll("#mappingTableBody select[data-raw-value]")
  )
    .map(select => ({
      raw_value: select.dataset.rawValue,
      mapped_value: select.value
    }))
    .filter(item => item.raw_value && item.mapped_value);

  btn.disabled = true;
  status.textContent = "Saving mappings...";

  try {
    const res = await fetch("/snipe-catalog/api/model-mappings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        source,
        mappings
      })
    });

    const data = await res.json();

    if (!res.ok || data.ok === false) {
      throw new Error(data.error || "Failed to save mappings.");
    }

    status.textContent = data.message || "Mappings saved.";
    await loadModelMappings();
  } catch (err) {
    status.textContent = err.message || "Failed to save mappings.";
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const lastSyncEl = document.getElementById("lastSync");
  const utcValue = lastSyncEl.dataset.utc;

  if (utcValue) {
    lastSyncEl.textContent = formatLocalDate(utcValue);
  }

  document.querySelectorAll(".catalog-tab").forEach(btn => {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
  });

  document.getElementById("filterBox")
    .addEventListener("input", () => {
      if (activeTab === "modelMappings") {
        renderMappingRows();
      } else {
        renderTable(activeRows);
      }
    });

  document.getElementById("syncBtn")
    .addEventListener("click", runSync);

  document.getElementById("loadMappingsBtn")
    .addEventListener("click", loadModelMappings);

  document.getElementById("saveMappingsBtn")
    .addEventListener("click", saveModelMappings);

  document.getElementById("mappingSource")
    .addEventListener("change", () => {
      mappingRows = [];
      document.getElementById("mappingTableBody").innerHTML =
        `<tr><td colspan="5">Choose a source and load discovered models.</td></tr>`;
      document.getElementById("saveMappingsBtn").disabled = true;
      document.getElementById("mappingStatus").textContent = "";
      document.getElementById("countHint").textContent = "";
    });

  document.querySelectorAll("[data-close-create-model-modal]").forEach(item => {
    item.addEventListener("click", closeCreateModelModal);
  });

  const modalCreateBtn = document.getElementById("modalCreateModelBtn");
  if (modalCreateBtn) {
    modalCreateBtn.addEventListener("click", createAndMapModelFromModal);
  }

  document.getElementById("modalCreateModelBtn")
    .addEventListener("click", createAndMapModelFromModal);

  activeTab = "models";
  loadActiveTab();
});

async function createSnipeModel() {
  const status = document.getElementById("createModelStatus");
  const btn = document.getElementById("createModelBtn");

  const name = document.getElementById("newModelName").value.trim();
  const modelNumber = document.getElementById("newModelNumber").value.trim();
  const categoryId = document.getElementById("newModelCategoryId").value.trim();
  const manufacturerId = document.getElementById("newModelManufacturerId").value.trim();

  if (!name || !categoryId) {
    status.textContent = "Friendly model name and category ID are required.";
    return;
  }

  btn.disabled = true;
  status.textContent = "Creating Snipe model...";

  try {
    const res = await fetch("/snipe-catalog/api/models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        name,
        model_number: modelNumber,
        category_id: categoryId,
        manufacturer_id: manufacturerId
      })
    });

    const data = await res.json();

    if (!res.ok || data.ok === false) {
      throw new Error(data.error || "Failed to create model.");
    }

    status.textContent = data.message || "Model created.";

    document.getElementById("newModelName").value = "";
    document.getElementById("newModelNumber").value = "";

    await loadModelMappings();
  } catch (err) {
    status.textContent = err.message || "Failed to create model.";
  } finally {
    btn.disabled = false;
  }
}

function openCreateModelModal(row) {
  const modal = document.getElementById("createModelModal");

  document.getElementById("modalRawModelValue").value = row.raw_value || "";
  document.getElementById("modalRawModelDisplay").value = row.raw_value || "";
  document.getElementById("modalModelName").value = "";
  document.getElementById("modalModelNumber").value = row.raw_value || "";
  document.getElementById("modalCategoryId").value = "";
  document.getElementById("modalManufacturerId").value = "";
  document.getElementById("createModelModalStatus").textContent = "";
  populateCreateModelDropdowns();

  modal.hidden = false;
}

function closeCreateModelModal() {
  document.getElementById("createModelModal").hidden = true;
}

async function createAndMapModelFromModal() {
  const btn = document.getElementById("modalCreateModelBtn");
  const status = document.getElementById("createModelModalStatus");

  const rawValue = document.getElementById("modalRawModelValue").value.trim();
  const name = document.getElementById("modalModelName").value.trim();
  const modelNumber = document.getElementById("modalModelNumber").value.trim();
  const categoryId = document.getElementById("modalCategoryId").value.trim();
  const manufacturerId = document.getElementById("modalManufacturerId").value.trim();
  const source = document.getElementById("mappingSource").value;

  if (!rawValue || !name || !categoryId) {
    status.textContent = "Raw model, friendly model name, and category ID are required.";
    return;
  }

  btn.disabled = true;
  status.textContent = "Creating model...";

  try {
    const createRes = await fetch("/snipe-catalog/api/models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        name,
        model_number: modelNumber,
        category_id: categoryId,
        manufacturer_id: manufacturerId
      })
    });

    const createData = await createRes.json();

    if (!createRes.ok || createData.ok === false) {
      throw new Error(createData.error || "Failed to create model.");
    }

    status.textContent = "Model created. Saving mapping...";

    const mapRes = await fetch("/snipe-catalog/api/model-mappings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        source,
        mappings: [
          {
            raw_value: rawValue,
            mapped_value: name
          }
        ]
      })
    });

    const mapData = await mapRes.json();

    if (!mapRes.ok || mapData.ok === false) {
      throw new Error(mapData.error || "Model created, but mapping failed.");
    }

    status.textContent = "Model created and mapped.";
    closeCreateModelModal();
    await loadModelMappings();
  } catch (err) {
    status.textContent = err.message || "Failed to create and map model.";
  } finally {
    btn.disabled = false;
  }
}

function populateCreateModelDropdowns() {
  const categorySelect = document.getElementById("modalCategoryId");
  const manufacturerSelect = document.getElementById("modalManufacturerId");

  categorySelect.innerHTML = `<option value="">Choose category</option>`;
  manufacturerSelect.innerHTML = `<option value="">No manufacturer</option>`;

  mappingCategories.forEach(category => {
    const option = document.createElement("option");
    option.value = category.id;
    option.textContent = category.name;
    categorySelect.appendChild(option);
  });

  mappingManufacturers.forEach(manufacturer => {
    const option = document.createElement("option");
    option.value = manufacturer.id;
    option.textContent = manufacturer.name;
    manufacturerSelect.appendChild(option);
  });
}