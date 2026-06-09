document.addEventListener("DOMContentLoaded", initCheckoutAssetsPage);

const selectedChildren = new Map();
let selectedParent = null;
let pendingConfirmAction = null;

function initCheckoutAssetsPage() {
  bindParentSearch();
  bindChildSearch();
  bindChildScan();
  bindCheckoutActions();

  renderParent();
  renderSelectedChildren();
  bindConfirmModal();
}

function $(id) {
  return document.getElementById(id);
}

function setStatus(message, ok = true) {
  const el = $("status");
  if (!el) return;

  el.textContent = message;
  el.classList.remove("ok", "bad");
  el.classList.add(ok ? "ok" : "bad");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, function (m) {
    return ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    })[m];
  });
}

function debounce(fn, wait = 250) {
  let timeout = null;

  return (...args) => {
    window.clearTimeout(timeout);
    timeout = window.setTimeout(() => fn(...args), wait);
  };
}

async function searchAssets(query, limit = 25) {
  const resp = await fetch(
    `/checkout-assets/api/search?q=${encodeURIComponent(query)}&limit=${limit}`,
    { headers: { "Accept": "application/json" } }
  );

  const data = await resp.json();

  if (!resp.ok || data.ok === false) {
    throw new Error(data.error || "Search failed.");
  }

  return data.results || [];
}

function assetLabel(asset) {
  const tag = asset.asset_tag ? `#${asset.asset_tag}` : "No tag";
  const name = asset.name || asset.model_name || "Unnamed asset";
  const serial = asset.serial ? ` • ${asset.serial}` : "";
  return `${tag} • ${name}${serial}`;
}

function bindParentSearch() {
  const parentSearch = $("parentSearch");
  const parentSearchBtn = $("parentSearchBtn");

  if (!parentSearch || !parentSearchBtn) return;

  const parentTypeahead = debounce(async () => {
    const query = (parentSearch.value || "").trim();

    if (query.length < 2) {
      $("parentResults").innerHTML = "";
      return;
    }

    try {
      const results = await searchAssets(query, 25);
      renderSearchResults("parentResults", results, "parent");
    } catch (err) {
      setStatus(err.message || "Parent search failed.", false);
    }
  }, 250);

  parentSearch.addEventListener("input", parentTypeahead);

  parentSearch.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      e.preventDefault();
      parentTypeahead();
    }
  });

  parentSearchBtn.addEventListener("click", parentTypeahead);
}

function bindChildSearch() {
  const childSearch = $("childSearch");
  const childSearchBtn = $("childSearchBtn");

  if (!childSearch || !childSearchBtn) return;

  const childTypeahead = debounce(async () => {
    const query = (childSearch.value || "").trim();

    if (query.length < 2) {
      $("childResults").innerHTML = "";
      return;
    }

    try {
      const results = await searchAssets(query, 50);
      renderSearchResults("childResults", results, "child");
    } catch (err) {
      setStatus(err.message || "Child search failed.", false);
    }
  }, 250);

  childSearch.addEventListener("input", childTypeahead);

  childSearch.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      e.preventDefault();
      childTypeahead();
    }
  });

  childSearchBtn.addEventListener("click", childTypeahead);
}

function bindChildScan() {
  const childScan = $("childScan");
  const childScanBtn = $("childScanBtn");

  if (!childScan || !childScanBtn) return;

  childScanBtn.addEventListener("click", addFirstSearchResultFromScan);

  childScan.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      e.preventDefault();
      addFirstSearchResultFromScan();
    }
  });
}

function bindCheckoutActions() {
  const clearSelectedBtn = $("clearSelectedBtn");
  const checkoutBtn = $("checkoutBtn");
  $("checkinAllChildrenBtn")?.addEventListener("click", checkinAllChildrenForParent);

  clearSelectedBtn?.addEventListener("click", () => {
    selectedChildren.clear();
    renderSelectedChildren();
    refreshChildSearchResults();
    setStatus("Selected child assets cleared.", true);
  });

  checkoutBtn?.addEventListener("click", checkoutSelected);
}

function renderSearchResults(containerId, assets, mode) {
  const el = $(containerId);
  if (!el) return;

  if (!assets.length) {
    el.innerHTML = `<div class="muted search-empty">No assets found.</div>`;
    return;
  }

  el.innerHTML = assets.map(asset => {
    const isSelected = mode === "child" && selectedChildren.has(String(asset.id));

    const assigned = asset.assigned_name
      ? `<div class="muted small">Assigned: ${escapeHtml(asset.assigned_name)}</div>`
      : `<div class="muted small">Assigned: —</div>`;

    return `
      <button class="asset-result ${isSelected ? "is-selected" : ""}" type="button" data-mode="${mode}" data-id="${asset.id}">
        ${isSelected ? `<span class="asset-result-check">✓</span>` : ""}
        <div><strong>${escapeHtml(assetLabel(asset))}</strong></div>
        <div class="muted small">
          ${escapeHtml(asset.model_name || "")}
          ${asset.location_name ? "• " + escapeHtml(asset.location_name) : ""}
          ${asset.asset_url ? ` • <a class="snipe-link" href="${asset.asset_url}" target="_blank" rel="noopener">Open in Snipe-IT ↗</a>` : ""}
        </div>
        ${assigned}
      </button>
    `;
  }).join("");

  el.querySelectorAll(".asset-result").forEach(btn => {
    btn.addEventListener("click", event => {
      if (event.target.closest("a")) {
        return;
      }

      const asset = assets.find(a => String(a.id) === String(btn.dataset.id));
      if (!asset) return;

      if (btn.dataset.mode === "parent") {
        selectedParent = asset;
        renderParent();
        setStatus("Parent asset selected.", true);
        $("childScan")?.focus();
        return;
      }

      toggleChild(asset);
      renderSearchResults(containerId, assets, mode);
    });
  });
}

function renderParent() {
  const el = $("selectedParent");
  const parentSearchWrap = $("parentSearchWrap");

  if (!el) return;

  if (!selectedParent) {
    el.className = "selected-parent empty";
    el.innerHTML = "No parent asset selected.";

    if (parentSearchWrap) {
      parentSearchWrap.style.display = "";
    }

    return;
  }

  if (parentSearchWrap) {
    parentSearchWrap.style.display = "none";
  }

  el.className = "selected-parent";
  el.innerHTML = `
  <div class="selected-parent-topline">
    <div class="selected-parent-badge">✓ Parent Asset Selected</div>
    <div class="selected-parent-count" id="parentAssetCountBadge">Loading...</div>
  </div>

  <div class="selected-title">${escapeHtml(assetLabel(selectedParent))}</div>
  <div class="muted small">
    ${escapeHtml(selectedParent.model_name || "")}
    ${selectedParent.location_name ? " • " + escapeHtml(selectedParent.location_name) : ""}
    ${selectedParent.asset_url ? ` • <a class="snipe-link" href="${selectedParent.asset_url}" target="_blank" rel="noopener">Open in Snipe-IT ↗</a>` : ""}
  </div>

  <div class="selected-parent-actions">
    <button id="changeParentBtn" class="btn btn-ghost" type="button">Change Parent Asset</button>
    <button id="viewParentAssetsBtn" class="btn btn-ghost" type="button">View Assets</button>
    <button id="checkinAllChildrenBtn" class="btn btn-danger" type="button">Check All Assets In</button>
  </div>
`;
  $("changeParentBtn")?.addEventListener("click", clearParentSelection);
  $("viewParentAssetsBtn")?.addEventListener("click", viewParentAssets);
  $("checkinAllChildrenBtn")?.addEventListener("click", checkinAllChildrenForParent);
  loadParentAssetCount(selectedParent.id);
}

function clearParentSelection() {
  selectedParent = null;

  const parentResults = $("parentResults");
  const parentSearch = $("parentSearch");

  if (parentResults) {
    parentResults.innerHTML = "";
  }

  if (parentSearch) {
    parentSearch.value = "";
  }

  renderParent();
  setStatus("Parent asset cleared. Select a new parent asset.", true);
  parentSearch?.focus();
}

function toggleChild(asset) {
  if (!asset || !asset.id) return;

  const key = String(asset.id);

  if (selectedChildren.has(key)) {
    selectedChildren.delete(key);
    renderSelectedChildren();
    setStatus(`Removed child asset. ${selectedChildren.size} child asset(s) selected.`, true);
    return;
  }

  addChild(asset);
}

function addChild(asset) {
  if (!asset || !asset.id) return;

  if (selectedParent && String(asset.id) === String(selectedParent.id)) {
    setStatus("You cannot select the parent asset as a child asset.", false);
    return;
  }

  selectedChildren.set(String(asset.id), asset);
  renderSelectedChildren();
  setStatus(`Selected ${selectedChildren.size} child asset(s).`, true);

  const childScan = $("childScan");
  if (childScan) {
    childScan.value = "";
    childScan.focus();
  }
}

function removeChild(assetId) {
  selectedChildren.delete(String(assetId));
  renderSelectedChildren();
  refreshChildSearchResults();
}

function renderSelectedChildren() {
  const tbody = $("selectedChildrenBody");
  if (!tbody) return;

  const assets = Array.from(selectedChildren.values());

  if (!assets.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="muted">No child assets selected.</td></tr>`;
    return;
  }

  tbody.innerHTML = assets.map(asset => `
  <tr class="selected-child-row" data-id="${asset.id}">
    <td>
      <button class="btn-mini remove-child" type="button" data-id="${asset.id}">Remove</button>
    </td>
    <td class="mono">${escapeHtml(asset.asset_tag || "")}</td>
    <td class="mono">${escapeHtml(asset.serial || "")}</td>
    <td>${escapeHtml(asset.model_name || "")}</td>
    <td>${escapeHtml(asset.status_name || "")}</td>
    <td>${escapeHtml(asset.assigned_name || "—")}</td>
    <td>
      <button class="btn-mini btn-checkin checkin-child" type="button" data-id="${asset.id}">Check In</button>
    </td>
    <td>
      <button class="btn-mini btn-edit edit-asset-tag" type="button" data-id="${asset.id}">Edit</button>
    </td>
    <td>
      ${asset.asset_url ? `<a class="snipe-link" href="${asset.asset_url}" target="_blank" rel="noopener">Open ↗</a>` : "—"}
    </td>
  </tr>
`).join("");

  tbody.querySelectorAll(".remove-child").forEach(btn => {
    btn.addEventListener("click", () => removeChild(btn.dataset.id));
  });

  tbody.querySelectorAll(".checkin-child").forEach(btn => {
    btn.addEventListener("click", () => checkinSingleAsset(btn.dataset.id));
  });

  tbody.querySelectorAll(".edit-asset-tag").forEach(btn => {
    btn.addEventListener("click", () => openAssetTagModal(btn.dataset.id));
  });

  tbody.querySelectorAll(".selected-child-row").forEach(row => {
    row.addEventListener("click", event => {
      if (event.target.closest("button, a, input, select, textarea")) {
        return;
      }

      openAssetTagModal(row.dataset.id);
    });
  });
}

async function refreshChildSearchResults() {
  const childSearch = $("childSearch");
  const query = (childSearch?.value || "").trim();

  if (query.length < 2) return;

  try {
    const results = await searchAssets(query, 50);
    renderSearchResults("childResults", results, "child");
  } catch (err) {
    setStatus(err.message || "Child search refresh failed.", false);
  }
}

function formatRecentTimestamp(value) {
  if (!value) {
    return "";
  }

  const raw = String(value).trim();

  // If the server already sent a friendly/local DB timestamp, keep it.
  if (!raw.includes("T")) {
    return raw;
  }

  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return raw;
  }

  return date.toLocaleString([], {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit"
  });
}

function prependRecent(result) {
  const tbody = $("recentBody");
  if (!tbody) return;

  const child = result.child_asset || {};
  const parent = result.parent_asset || selectedParent || {};
  const createdAt = result.created_at || "";

  const tr = document.createElement("tr");
  tr.className = result.ok ? "ok" : "bad";
  tr.innerHTML = `
    <td class="mono">${escapeHtml(formatRecentTimestamp(createdAt))}</td>
    <td class="mono">${escapeHtml(child.asset_tag || child.name || child.id || "")}</td>
    <td class="mono">${escapeHtml(child.serial || "")}</td>
    <td class="mono">${escapeHtml(parent.asset_tag || parent.name || parent.id || "")}</td>
    <td>${result.ok ? "Success" : "Error"}</td>
    <td class="muted">${escapeHtml(result.message || "")}</td>
  `;

  tbody.prepend(tr);
}

async function addFirstSearchResultFromScan() {
  const childScan = $("childScan");
  const query = (childScan?.value || "").trim();

  if (!query) {
    setStatus("Scan or enter a child asset first.", false);
    childScan?.focus();
    return;
  }

  try {
    const results = await searchAssets(query, 10);

    if (!results.length) {
      setStatus("No child asset found in SnipeOps Catalog.", false);
      return;
    }

    if (results.length === 1) {
      addChild(results[0]);
      refreshChildSearchResults();
      return;
    }

    renderSearchResults("childResults", results, "child");
    setStatus("Multiple matches found. Select the correct child asset.", false);
  } catch (err) {
    setStatus(err.message || "Child asset lookup failed.", false);
  }
}

async function checkoutSelected() {
  if (!selectedParent) {
    setStatus("Select a parent asset first.", false);
    return;
  }

  const childIds = Array.from(selectedChildren.keys());

  if (!childIds.length) {
    setStatus("Select at least one child asset.", false);
    return;
  }

  const delayMs = Number($("delayMs")?.value || 350);
  const checkoutBtn = $("checkoutBtn");

  if (checkoutBtn) {
    checkoutBtn.disabled = true;
  }

  setStatus(`Checking out ${childIds.length} asset(s)...`, true);

  try {
    const resp = await fetch("/checkout-assets/api/checkout", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify({
        parent_asset_id: selectedParent.id,
        child_asset_ids: childIds,
        delay_ms: delayMs
      })
    });

    const data = await resp.json();

    if (!resp.ok || data.ok === false) {
      throw new Error(data.error || "Checkout failed.");
    }

    let successCount = 0;
    let errorCount = 0;

    (data.results || []).forEach(result => {
      prependRecent(result);

      if (result.ok) {
        successCount += 1;

        if (result.child_asset && result.child_asset.id) {
          selectedChildren.delete(String(result.child_asset.id));
        }
      } else {
        errorCount += 1;
      }
    });

    renderSelectedChildren();
    refreshChildSearchResults();

    if (errorCount) {
      setStatus(`Completed with ${successCount} success(es) and ${errorCount} error(s).`, false);
    } else {
      setStatus(`Checked out ${successCount} asset(s).`, true);
    }
  } catch (err) {
    setStatus(err.message || "Checkout request failed.", false);
  } finally {
    if (checkoutBtn) {
      checkoutBtn.disabled = false;
    }

    $("childScan")?.focus();
  }
}

async function checkinAllChildrenForParent() {
  if (!selectedParent) {
    setStatus("Select a parent asset first.", false);
    return;
  }

  const parentForCheckin = { ...selectedParent };
  let childCount = 0;

  try {
    childCount = await getAssignedChildrenCount(parentForCheckin.id);
  } catch (err) {
    setStatus(err.message || "Unable to count assigned child assets.", false);
    return;
  }

  openConfirmModal({
    title: "Check In All Assets?",
    messageHtml: `
      <p class="confirm-copy">
        This will unassign every asset currently assigned to this parent asset and return them to Ready to Deploy in Snipe-IT.
      </p>

      <div class="confirm-detail-card">
        <div class="confirm-detail-heading">Selected Parent</div>

        <div class="confirm-detail-row">
          <div class="confirm-detail-label">Asset Tag</div>
          <div class="confirm-detail-value">${escapeHtml(parentForCheckin.asset_tag || "—")}</div>
        </div>

        <div class="confirm-detail-row">
          <div class="confirm-detail-label">Name</div>
          <div class="confirm-detail-value">${escapeHtml(parentForCheckin.name || "—")}</div>
        </div>

        <div class="confirm-detail-row">
          <div class="confirm-detail-label">Model</div>
          <div class="confirm-detail-value">${escapeHtml(parentForCheckin.model_name || "—")}</div>
        </div>

        <div class="confirm-detail-row">
          <div class="confirm-detail-label">Devices Assigned</div>
          <div class="confirm-detail-value">${escapeHtml(childCount)}</div>
        </div>
      </div>

      <p class="confirm-copy confirm-warning">
        This is intended for full cart replacement workflows.
      </p>
    `,
    buttonText: "Check All In",
    action: async () => runCheckinAllChildrenForParent(parentForCheckin)
  });
}

async function runCheckinAllChildrenForParent(parentForCheckin) {
  const btn = $("checkinAllChildrenBtn");
  const delayMs = Number($("delayMs")?.value || 350);

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Checking in...";
  }

  setStatus("Checking in all child assets assigned to selected parent...", true);

  try {
    const resp = await fetch("/checkout-assets/api/checkin-parent-children", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify({
        parent_asset_id: parentForCheckin.id,
        delay_ms: delayMs
      })
    });

    const data = await resp.json();

    if (!resp.ok || data.ok === false) {
      throw new Error(data.error || "Bulk check-in failed.");
    }

    let successCount = 0;
    let errorCount = 0;

    (data.results || []).forEach(result => {
      prependRecent(result);

      if (result.ok) {
        successCount += 1;
      } else {
        errorCount += 1;
      }
    });

    selectedChildren.clear();
    renderSelectedChildren();
    refreshChildSearchResults();

    if (!data.results || !data.results.length) {
      setStatus(data.message || "No child assets were assigned to this parent in the local catalog.", true);
      return;
    }

    if (errorCount) {
      setStatus(`Bulk check-in completed with ${successCount} success(es) and ${errorCount} error(s).`, false);
    } else {
      setStatus(`Checked in ${successCount} asset(s). They are now unassigned/Ready to Deploy in Snipe-IT.`, true);
    }
  } catch (err) {
    setStatus(err.message || "Bulk check-in failed.", false);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Check All Assets In";
    }
  }
}

function bindConfirmModal() {
  $("cancelConfirmBtn")?.addEventListener("click", closeConfirmModal);

  $("confirmActionBtn")?.addEventListener("click", async () => {
    if (!pendingConfirmAction) {
      closeConfirmModal();
      return;
    }

    const action = pendingConfirmAction;
    closeConfirmModal();

    await action();
  });

  $("confirmModal")?.addEventListener("click", event => {
    if (event.target.id === "confirmModal") {
      closeConfirmModal();
    }
  });
}

function openConfirmModal({
  title,
  messageHtml,
  buttonText,
  action,
  wide = false,
  hideCancel = false,
  buttonClass = "btn-primary"
}) {
  pendingConfirmAction = action;

  $("confirmTitle").textContent = title || "Confirm";
  $("confirmMessage").innerHTML = messageHtml || "";

  const actionBtn = $("confirmActionBtn");
  if (actionBtn) {
    actionBtn.textContent = buttonText || "Continue";
    actionBtn.classList.remove("btn-danger", "btn-primary");
    actionBtn.classList.add(buttonClass);
    actionBtn.disabled = false;
  }

  const modalCard = $("confirmModal")?.querySelector(".checkout-modal-card");
  modalCard?.classList.toggle("modal-wide", Boolean(wide));

  const cancelBtn = $("cancelConfirmBtn");
  if (cancelBtn) {
    cancelBtn.classList.toggle("hidden", Boolean(hideCancel));
  }

  $("confirmModal")?.classList.remove("hidden");
}

function closeConfirmModal() {
  pendingConfirmAction = null;

  const modalCard = $("confirmModal")?.querySelector(".checkout-modal-card");
  modalCard?.classList.remove("modal-wide");

  $("cancelConfirmBtn")?.classList.remove("hidden");
  $("confirmModal")?.classList.add("hidden");
}

async function getAssignedChildrenCount(parentAssetId) {
  const resp = await fetch(`/checkout-assets/api/parent-children-count?parent_asset_id=${encodeURIComponent(parentAssetId)}`, {
    headers: { "Accept": "application/json" }
  });

  const data = await resp.json();

  if (!resp.ok || data.ok === false) {
    throw new Error(data.error || "Unable to count assigned child assets.");
  }

  return data.count || 0;
}

async function checkinSingleAsset(assetId) {
  const delayMs = Number($("delayMs")?.value || 350);

  try {
    const resp = await fetch(`/checkout-assets/api/assets/${encodeURIComponent(assetId)}/checkin`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify({ delay_ms: delayMs })
    });

    const data = await resp.json();

    if (!resp.ok || data.ok === false) {
      throw new Error(data.error || "Check-in failed.");
    }

    prependRecent(data);
    setStatus("Asset checked in.", true);
    refreshChildSearchResults();
  } catch (err) {
    setStatus(err.message || "Check-in failed.", false);
  }
}

function openAssetTagModal(assetId) {
  const asset = selectedChildren.get(String(assetId));
  if (!asset) return;

  openConfirmModal({
    title: "Edit Asset Tag",
    messageHtml: `
      <p class="confirm-copy">
        Update the asset number for this selected asset.
      </p>

      <div class="confirm-detail-card">
        <div class="confirm-detail-heading">Selected Asset</div>

        <div class="confirm-detail-row">
          <div class="confirm-detail-label">Current Tag</div>
          <div class="confirm-detail-value">${escapeHtml(asset.asset_tag || "—")}</div>
        </div>

        <div class="confirm-detail-row">
          <div class="confirm-detail-label">Serial</div>
          <div class="confirm-detail-value">${escapeHtml(asset.serial || "—")}</div>
        </div>

        <div class="confirm-detail-row">
          <div class="confirm-detail-label">Model</div>
          <div class="confirm-detail-value">${escapeHtml(asset.model_name || "—")}</div>
        </div>
      </div>

      <div class="modal-form">
        <label class="label" for="assetTagModalInput">New Asset Tag</label>
        <input id="assetTagModalInput" class="input" autocomplete="off" value="${escapeHtml(asset.asset_tag || "")}">
      </div>
    `,
    buttonText: "Save Asset Tag",
    action: async () => {
      const input = $("assetTagModalInput");
      await updateSelectedAssetTag(assetId, input?.value || "");
    }
  });

  window.setTimeout(() => {
    const input = $("assetTagModalInput");
    input?.focus();
    input?.select();
  }, 50);
}

async function updateSelectedAssetTag(assetId, assetTag) {
  try {
    const resp = await fetch(`/checkout-assets/api/assets/${encodeURIComponent(assetId)}/asset-tag`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify({ asset_tag: assetTag })
    });

    const data = await resp.json();

    if (!resp.ok || data.ok === false) {
      throw new Error(data.error || "Asset number update failed.");
    }

    if (data.asset) {
      selectedChildren.set(String(data.asset.id), data.asset);
      renderSelectedChildren();
    }

    setStatus("Asset number updated.", true);
    refreshChildSearchResults();
  } catch (err) {
    setStatus(err.message || "Asset number update failed.", false);
  }
}

async function loadParentAssetCount(parentAssetId) {
  try {
    const count = await getAssignedChildrenCount(parentAssetId);
    const badge = $("parentAssetCountBadge");

    if (badge) {
      badge.textContent = `${count} device${count === 1 ? "" : "s"}`;
    }
  } catch (err) {
    const badge = $("parentAssetCountBadge");
    if (badge) badge.textContent = "Count unavailable";
  }
}

async function viewParentAssets() {
  if (!selectedParent) {
    setStatus("Select a parent asset first.", false);
    return;
  }

  pendingParentAssetCheckins.clear();

  try {
    const resp = await fetch(`/checkout-assets/api/assets/${encodeURIComponent(selectedParent.id)}/children`, {
      headers: { "Accept": "application/json" }
    });

    const data = await resp.json();

    if (!resp.ok || data.ok === false) {
      throw new Error(data.error || "Unable to load parent assets.");
    }

    const rows = (data.assets || []).map(asset => `
      <tr>
        <td class="mono">${escapeHtml(asset.asset_tag || "")}</td>
        <td class="mono">${escapeHtml(asset.serial || "")}</td>
        <td>${escapeHtml(asset.model_name || "")}</td>
        <td>${escapeHtml(asset.status_name || "")}</td>
        <td>
          <button class="btn-mini btn-checkin parent-asset-checkin" type="button" data-id="${asset.id}">
            Check In
          </button>
        </td>
        <td>
          ${asset.asset_url ? `<a class="snipe-link" href="${asset.asset_url}" target="_blank" rel="noopener">Open ↗</a>` : "—"}
        </td>
      </tr>
    `).join("");

    openConfirmModal({
      title: `Assets in ${selectedParent.asset_tag || selectedParent.name || "Parent Asset"}`,
      messageHtml: `
        <p class="confirm-copy">
          ${data.count || 0} asset(s) currently assigned to this parent.
          Click <strong>Check In</strong> to stage changes, then click <strong>Save</strong>.
        </p>

        <div class="recent-wrap">
          <table class="table parent-assets-modal-table">
            <thead>
              <tr>
                <th>Asset Tag</th>
                <th>Serial</th>
                <th>Model</th>
                <th>Status</th>
                <th>Check In</th>
                <th>Open</th>
              </tr>
            </thead>
            <tbody>
              ${rows || `<tr><td colspan="6" class="muted">No assets currently assigned.</td></tr>`}
            </tbody>
          </table>
        </div>
      `,
      buttonText: "Save",
      wide: true,
      hideCancel: false,
      action: saveParentAssetCheckins
    });

    document.querySelectorAll(".parent-asset-checkin").forEach(btn => {
      btn.addEventListener("click", () => toggleParentAssetCheckin(btn.dataset.id));
    });
  } catch (err) {
    setStatus(err.message || "Unable to load parent assets.", false);
  }
}

let pendingParentAssetCheckins = new Set();

function toggleParentAssetCheckin(assetId) {
  const key = String(assetId);

  if (pendingParentAssetCheckins.has(key)) {
    pendingParentAssetCheckins.delete(key);
  } else {
    pendingParentAssetCheckins.add(key);
  }

  document.querySelectorAll(".parent-asset-checkin").forEach(btn => {
    const id = String(btn.dataset.id);
    const isPending = pendingParentAssetCheckins.has(id);

    btn.classList.toggle("is-pending", isPending);
    btn.textContent = isPending ? "Undo" : "Check In";

    const row = btn.closest("tr");
    row?.classList.toggle("pending-checkin-row", isPending);
  });
}

async function saveParentAssetCheckins() {
  const assetIds = Array.from(pendingParentAssetCheckins);

  if (!assetIds.length) {
    closeConfirmModal();
    return;
  }

  const delayMs = Number($("delayMs")?.value || 350);
  const saveBtn = $("confirmActionBtn");

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
  }

  let successCount = 0;
  let errorCount = 0;

  for (const assetId of assetIds) {
    try {
      const resp = await fetch(`/checkout-assets/api/assets/${encodeURIComponent(assetId)}/checkin`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify({ delay_ms: delayMs })
      });

      const data = await resp.json();

      if (!resp.ok || data.ok === false) {
        throw new Error(data.error || "Check-in failed.");
      }

      prependRecent(data);
      successCount += 1;
    } catch (err) {
      errorCount += 1;
    }
  }

  pendingParentAssetCheckins.clear();
  closeConfirmModal();

  if (selectedParent) {
    loadParentAssetCount(selectedParent.id);
  }

  refreshChildSearchResults();

  if (errorCount) {
    setStatus(`Saved with ${successCount} check-in(s) and ${errorCount} error(s).`, false);
  } else {
    setStatus(`Checked in ${successCount} asset(s).`, true);
  }
}