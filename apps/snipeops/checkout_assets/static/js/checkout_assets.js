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
    <div class="selected-parent-badge">✓ Parent Asset Selected</div>
    <div class="selected-title">${escapeHtml(assetLabel(selectedParent))}</div>
    <div class="muted small">
      ${escapeHtml(selectedParent.model_name || "")}
      ${selectedParent.location_name ? " • " + escapeHtml(selectedParent.location_name) : ""}
      ${selectedParent.asset_url ? ` • <a class="snipe-link" href="${selectedParent.asset_url}" target="_blank" rel="noopener">Open in Snipe-IT ↗</a>` : ""}
    </div>
    <div class="selected-parent-actions">
      <button id="changeParentBtn" class="btn btn-ghost" type="button">Change Parent Asset</button>
      <button id="checkinAllChildrenBtn" class="btn btn-danger" type="button">Check All Assets In</button>
    </div>
  `;
  $("changeParentBtn")?.addEventListener("click", clearParentSelection);
  $("checkinAllChildrenBtn")?.addEventListener("click", checkinAllChildrenForParent);
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
    tbody.innerHTML = `<tr><td colspan="8" class="muted">No child assets selected.</td></tr>`;
    return;
  }

  tbody.innerHTML = assets.map(asset => `
    <tr>
      <td>
        <button class="btn-mini remove-child" type="button" data-id="${asset.id}">Remove</button>
      </td>
      <td class="mono">${escapeHtml(asset.asset_tag || "")}</td>
      <td class="mono">${escapeHtml(asset.serial || "")}</td>
      <td>${escapeHtml(asset.name || "")}</td>
      <td>${escapeHtml(asset.model_name || "")}</td>
      <td>${escapeHtml(asset.status_name || "")}</td>
      <td>${escapeHtml(asset.assigned_name || "—")}</td>
      <td>
        ${asset.asset_url ? `<a class="snipe-link" href="${asset.asset_url}" target="_blank" rel="noopener">Open ↗</a>` : "—"}
      </td>
    </tr>
  `).join("");

  tbody.querySelectorAll(".remove-child").forEach(btn => {
    btn.addEventListener("click", () => removeChild(btn.dataset.id));
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

function prependRecent(result) {
  const tbody = $("recentBody");
  if (!tbody) return;

  const child = result.child_asset || {};
  const parent = result.parent_asset || selectedParent || {};

  const tr = document.createElement("tr");
  tr.className = result.ok ? "ok" : "bad";
  tr.innerHTML = `
    <td class="mono">${escapeHtml(result.created_at || new Date().toISOString())}</td>
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

function openConfirmModal({ title, messageHtml, buttonText, action }) {
  pendingConfirmAction = action;

  $("confirmTitle").textContent = title || "Confirm";
  $("confirmMessage").innerHTML = messageHtml || "";
  $("confirmActionBtn").textContent = buttonText || "Continue";
  $("confirmModal")?.classList.remove("hidden");
}

function closeConfirmModal() {
  pendingConfirmAction = null;
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