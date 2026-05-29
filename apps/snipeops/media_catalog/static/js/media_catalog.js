document.addEventListener("DOMContentLoaded", initMediaCatalog);

const MEDIA_CATALOG_BASE = "/snipeops/media-catalog";

let currentUser = null;
let selectedCart = null;
let pendingAction = null;
let pendingMoveDevice = null;
let moveModalDevice = null;

const sheetDevices = new Map();

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

function setDeviceCount(count) {
    const el = $("deviceCount");
    if (!el) return;
    el.textContent = Number.isFinite(Number(count)) ? String(count) : "—";
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

function assetLabel(asset) {
    const tag = asset.asset_tag ? `#${asset.asset_tag}` : "No tag";
    const name = asset.name || asset.model_name || "Unnamed asset";
    return `${tag} • ${name}`;
}

function cartDisplayName(cart) {
    const tag = cart.asset_tag ? `#${cart.asset_tag}` : "No tag";
    const name = cart.name || "Unnamed cart";
    return `${tag} • ${name}`;
}

async function readJsonResponse(resp, fallbackMessage) {
    const text = await resp.text();

    let data;
    try {
        data = JSON.parse(text);
    } catch {
        throw new Error(`${fallbackMessage} Server returned non-JSON response. Status ${resp.status}.`);
    }

    if (!resp.ok || data.ok === false) {
        throw new Error(data.error || data.message || fallbackMessage);
    }

    return data;
}

async function apiGet(path, fallbackMessage) {
    const resp = await fetch(`${MEDIA_CATALOG_BASE}${path}`, {
        headers: { "Accept": "application/json" }
    });

    return readJsonResponse(resp, fallbackMessage);
}

async function apiPost(path, body, fallbackMessage) {
    const resp = await fetch(`${MEDIA_CATALOG_BASE}${path}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        body: JSON.stringify(body || {})
    });

    return readJsonResponse(resp, fallbackMessage);
}

async function initMediaCatalog() {
    bindCartSearch();
    bindFindCartToggle();
    bindRefreshMyCarts();
    bindDeviceAdd();
    bindSyncButton();
    bindConfirmModal();
    bindDeviceDetailModal();
    bindMoveDeviceModal();

    renderSheetEmpty("Select a cart to load assigned devices.");
    setDeviceCount("—");
    hideSelectedCartPanel();

    try {
        await loadCurrentUser();
        await loadMyCarts();
        setStatus("Media Catalog loaded.", true);
    } catch (err) {
        setStatus(err.message || "Media Catalog failed to load.", false);
    }
}

async function loadCurrentUser() {
    const data = await apiGet("/api/me", "Unable to load current user.");
    currentUser = data.user || null;
}

function bindFindCartToggle() {
    $("toggleFindCartBtn")?.addEventListener("click", () => {
        const panel = $("findCartPanel");
        if (!panel) return;

        panel.classList.toggle("hidden");

        if (!panel.classList.contains("hidden")) {
            $("cartSearch")?.focus();
        }
    });
}

function bindRefreshMyCarts() {
    $("refreshMyCartsBtn")?.addEventListener("click", loadMyCarts);
}

async function loadMyCarts() {
    const el = $("myCarts");
    if (!el) return;

    el.innerHTML = `<div class="muted">Loading your carts...</div>`;

    try {
        const data = await apiGet("/api/my-carts", "Unable to load your carts.");
        renderCartList("myCarts", data.carts || [], { showOwnershipButton: false });
    } catch (err) {
        el.innerHTML = `<div class="muted">${escapeHtml(err.message || "Unable to load your carts.")}</div>`;
    }
}

function bindCartSearch() {
    const input = $("cartSearch");
    const btn = $("cartSearchBtn");

    if (!input || !btn) return;

    const run = debounce(searchCarts, 250);

    input.addEventListener("input", run);

    input.addEventListener("keydown", e => {
        if (e.key === "Enter") {
            e.preventDefault();
            searchCarts();
        }
    });

    btn.addEventListener("click", searchCarts);
}

async function searchCarts() {
    const input = $("cartSearch");
    const resultsEl = $("cartResults");
    const query = (input?.value || "").trim();

    if (!resultsEl) return;

    if (query.length < 2) {
        resultsEl.innerHTML = "";
        return;
    }

    resultsEl.innerHTML = `<div class="muted">Searching carts...</div>`;
    setStatus(`Searching carts for "${query}"...`, true);

    try {
        const data = await apiGet(`/api/carts?q=${encodeURIComponent(query)}`, "Cart search failed.");
        renderCartList("cartResults", data.carts || [], { showOwnershipButton: true });
        setStatus(`Found ${(data.carts || []).length} cart(s).`, true);
    } catch (err) {
        resultsEl.innerHTML = `<div class="muted">${escapeHtml(err.message || "Cart search failed.")}</div>`;
        setStatus(err.message || "Cart search failed.", false);
    }
}

function renderCartList(containerId, carts, options = {}) {
    const el = $(containerId);
    if (!el) return;

    const showOwnershipButton = options.showOwnershipButton !== false;

    if (!carts.length) {
        el.innerHTML = `<div class="muted">No carts found.</div>`;
        return;
    }

    el.innerHTML = carts.map(cart => {
        const ownership = cart.ownership || null;
        const ownerDisplay = ownership?.owner_display_name || "Unknown user";
        const ownerEmail = ownership?.owner_email || "";
        const ownerName = ownerEmail ? `${ownerDisplay} (${ownerEmail})` : ownerDisplay;
        const ownedByCurrentUser = currentUser && ownership && Number(ownership.owner_user_id) === Number(currentUser.id);

        let ownershipText = "Unassigned";
        if (ownedByCurrentUser) {
            ownershipText = "Owned by: You";
        } else if (ownerName) {
            ownershipText = `Owned by: ${ownerName}`;
        }

        const ownershipButton = showOwnershipButton
            ? `<button class="mini-btn take-ownership" type="button" data-cart-id="${escapeHtml(cart.id)}">${ownedByCurrentUser ? "Refresh Ownership" : "Take Ownership"}</button>`
            : "";

        return `
      <div class="cart-card ${selectedCart && String(selectedCart.id) === String(cart.id) ? "selected" : ""}" data-cart-id="${escapeHtml(cart.id)}">
        <button class="cart-main" type="button" data-open-cart-id="${escapeHtml(cart.id)}">
          <strong>${escapeHtml(cartDisplayName(cart))}</strong>
          <div class="muted">
            ${escapeHtml(cart.model_name || "")}
            ${cart.location_name ? " • " + escapeHtml(cart.location_name) : ""}
          </div>
          <div class="muted">${escapeHtml(ownershipText)}</div>
        </button>

        <div class="cart-actions">
          ${ownershipButton}
          ${cart.asset_url ? `<a class="snipe-link" href="${escapeHtml(cart.asset_url)}" target="_blank" rel="noopener">Snipe-IT</a>` : ""}
        </div>
      </div>
    `;
    }).join("");

    el.querySelectorAll("[data-open-cart-id]").forEach(btn => {
        btn.addEventListener("click", () => {
            const cart = carts.find(c => String(c.id) === String(btn.dataset.openCartId));
            if (!cart) return;

            if (pendingMoveDevice) {
                requestMoveDeviceToCart(pendingMoveDevice, cart);
                return;
            }

            if (selectedCart && String(selectedCart.id) === String(cart.id)) {
                hideSelectedCartPanel();
                setStatus("Cart unselected.", true);
                return;
            }

            selectCart(cart);
        });
    });

    el.querySelectorAll(".take-ownership").forEach(btn => {
        btn.addEventListener("click", () => {
            const cart = carts.find(c => String(c.id) === String(btn.dataset.cartId));
            if (cart) requestTakeOwnership(cart);
        });
    });
}

async function selectCart(cart) {
    showSelectedCartPanel();
    selectedCart = cart;
    sheetDevices.clear();
    setDeviceCount("—");

    const title = $("cartTitle");
    const subtitle = $("cartSubtitle");

    if (title) {
        title.textContent = cart.asset_tag
            ? `Cart ${cart.asset_tag}`
            : cart.name || "Selected Cart";
    }

    if (subtitle) {
        const owner = cart.ownership?.owner_display_name || cart.ownership?.owner_email || "Unassigned";
        subtitle.textContent = `${cart.name || ""}${cart.location_name ? " • " + cart.location_name : ""} • Owner: ${owner}`;
    }

    renderSheetEmpty("Loading assigned devices...");
    setStatus("Loading cart devices...", true);

    try {
        const data = await apiGet(`/api/carts/${cart.id}/devices`, "Unable to load cart devices.");

        selectedCart = data.cart || cart;
        sheetDevices.clear();

        (data.devices || []).forEach(device => {
            sheetDevices.set(String(device.id), device);
        });

        renderSheet();
        setDeviceCount(sheetDevices.size);
        setStatus(`Loaded ${sheetDevices.size} device(s) in this cart.`, true);
        await loadMyCarts();
        $("deviceInput")?.focus();
    } catch (err) {
        renderSheetEmpty(err.message || "Unable to load cart devices.");
        setDeviceCount("—");
        setStatus(err.message || "Unable to load cart devices.", false);
    }
}

function requestTakeOwnership(cart) {
    const ownership = cart.ownership || null;

    const ownerDisplay = ownership?.owner_display_name || "Unknown";
    const ownerEmail = ownership?.owner_email || "Not recorded";
    const cartLabel = `${cart.asset_tag ? "#" + cart.asset_tag : "No tag"} • ${cart.name || "Unnamed cart"}`;

    if (
        ownership &&
        currentUser &&
        Number(ownership.owner_user_id) !== Number(currentUser.id)
    ) {
        openConfirmModal({
            title: "Take Ownership?",
            messageHtml: `
                <p class="confirm-copy">
                    This cart is currently assigned to another Media Specialist.
                </p>

                <div class="ownership-detail-card">
                    <div class="ownership-detail-heading">Current Owner</div>

                    <div class="ownership-detail-row">
                        <div class="ownership-detail-label">Display Name</div>
                        <div class="ownership-detail-value">${escapeHtml(ownerDisplay)}</div>
                    </div>

                    <div class="ownership-detail-row">
                        <div class="ownership-detail-label">Username</div>
                        <div class="ownership-detail-value">${escapeHtml(ownerEmail)}</div>
                    </div>

                    <div class="ownership-detail-row">
                        <div class="ownership-detail-label">Cart</div>
                        <div class="ownership-detail-value">${escapeHtml(cartLabel)}</div>
                    </div>
                </div>

                <p class="confirm-copy confirm-warning">
                    Taking ownership will transfer this cart to your Media Catalog.
                    The previous owner will lose ownership of this cart.
                </p>
            `,
            buttonText: "Take Ownership",
            action: async () => claimCart(cart)
        });

        return;
    }

    openConfirmModal({
        title: "Take Ownership?",
        messageHtml: `
            <p class="confirm-copy">
                This cart currently has no assigned Media Specialist.
            </p>

            <div class="ownership-detail-card">
                <div class="ownership-detail-heading">Cart</div>

                <div class="ownership-detail-row">
                    <div class="ownership-detail-label">Asset</div>
                    <div class="ownership-detail-value">${escapeHtml(cartLabel)}</div>
                </div>
            </div>

            <p class="confirm-copy confirm-warning">
                Do you want to take ownership of this cart?
            </p>
        `,
        buttonText: "Take Ownership",
        action: async () => claimCart(cart)
    });
}

async function claimCart(cart) {
    setStatus("Updating cart ownership...", true);

    try {
        const data = await apiPost(`/api/carts/${cart.id}/claim`, {}, "Unable to claim cart.");

        prependRecent(
            "claimed_cart",
            null,
            data.cart || cart,
            true,
            data.message || "Cart ownership updated."
        );

        await loadMyCarts();

        const cartResults = $("cartResults");
        if (cartResults) {
            cartResults.innerHTML = "";
        }

        const cartSearch = $("cartSearch");
        if (cartSearch) {
            cartSearch.value = "";
        }

        setStatus(data.message || "Cart ownership updated.", true);

        if (data.cart) {
            await selectCart(data.cart);
        }
    } catch (err) {
        setStatus(err.message || "Unable to claim cart.", false);
    }
}

function bindDeviceAdd() {
    const input = $("deviceInput");
    const btn = $("deviceAddBtn");

    if (!input || !btn) return;

    const run = async () => {
        const query = input.value.trim();

        if (!selectedCart) {
            setStatus("Select a cart before adding a device.", false);
            return;
        }

        if (!query) {
            setStatus("Scan or type an asset tag or serial number first.", false);
            return;
        }

        setStatus(`Looking up device "${query}"...`, true);

        try {
            const data = await apiGet(`/api/search?q=${encodeURIComponent(query)}`, "Device lookup failed.");
            const results = data.results || [];

            if (!results.length) {
                setStatus("No matching device found.", false);
                return;
            }

            if (results.length > 1) {
                openDeviceChoice(results);
                setStatus("Multiple devices found. Choose the correct device.", false);
                return;
            }

            await requestAddDevice(results[0], false);
        } catch (err) {
            setStatus(err.message || "Device lookup failed.", false);
        }
    };

    input.addEventListener("keydown", e => {
        if (e.key === "Enter") {
            e.preventDefault();
            run();
        }
    });

    btn.addEventListener("click", run);
}

function openDeviceChoice(devices) {
    const message = [
        "Multiple devices matched your entry. Use a more specific asset tag or serial number.",
        "",
        ...devices.slice(0, 8).map(d => `${d.asset_tag || "No tag"} • ${d.serial || "No serial"} • ${d.name || d.model_name || ""}`)
    ].join("\n");

    openConfirmModal({
        title: "Multiple Matches",
        message,
        buttonText: "OK",
        action: async () => { }
    });
}

async function requestAddDevice(device, force) {
    if (!selectedCart) {
        setStatus("Select a cart first.", false);
        return;
    }

    if (String(device.id) === String(selectedCart.id)) {
        setStatus("You cannot add a cart to itself.", false);
        return;
    }

    const assignedId = device.assigned_id ? String(device.assigned_id) : "";
    const cartId = String(selectedCart.id);
    const assignedName = device.assigned_name || "";

    if (!force && assignedName && assignedId !== cartId) {
        openConfirmModal({
            title: "Move Device?",
            message: `This device is currently assigned to ${assignedName}. Move it to ${selectedCart.asset_tag || selectedCart.name}?`,
            buttonText: "Move Device",
            action: async () => addDeviceToCart(device, true)
        });
        return;
    }

    await addDeviceToCart(device, force);
}

async function addDeviceToCart(device, force) {
    setStatus("Assigning device to cart...", true);

    try {
        const data = await apiPost(
            "/api/add-to-cart",
            {
                cart_id: selectedCart.id,
                device_id: device.id,
                force: force
            },
            "Unable to add device to cart."
        );

        if (data.needs_confirmation) {
            openConfirmModal({
                title: "Move Device?",
                message: data.message || "This device is assigned elsewhere. Move it to this cart?",
                buttonText: "Move Device",
                action: async () => addDeviceToCart(device, true)
            });
            return;
        }

        const deviceInput = $("deviceInput");
        if (deviceInput) {
            deviceInput.value = "";
        }

        await selectCart(selectedCart);
        prependRecent("add_to_cart", device, selectedCart, true, data.message || "Device assigned to cart.");
        setStatus("Device assigned to cart.", true);
    } catch (err) {
        setStatus(err.message || "Unable to add device to cart.", false);
    }
}

function requestRemoveDevice(deviceId) {
    const device = sheetDevices.get(String(deviceId));
    if (!device) return;

    openConfirmModal({
        title: "Remove Device?",
        message: `Remove ${device.asset_tag || device.serial || device.name || "this device"} from this cart? It will be checked in and returned to Ready to Deploy according to Snipe-IT check-in behavior.`,
        buttonText: "Remove Device",
        action: async () => removeFromCart(device)
    });
}

async function removeFromCart(device) {
    setStatus("Removing device from cart...", true);

    try {
        const data = await apiPost(
            "/api/remove-from-cart",
            { device_id: device.id },
            "Unable to remove device from cart."
        );

        const removedFromCart = selectedCart;

        sheetDevices.delete(String(device.id));
        renderSheet();
        setDeviceCount(sheetDevices.size);

        prependRecent("remove_from_cart", device, removedFromCart, true, data.message || "Device removed from cart.");
        setStatus(`Device removed. ${sheetDevices.size} device(s) remain in this cart.`, true);

    } catch (err) {
        setStatus(err.message || "Unable to remove device from cart.", false);
    }
}

function renderSheetEmpty(message) {
    const tbody = $("sheetBody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="7" class="muted">${escapeHtml(message)}</td></tr>`;
}

function renderSheet() {
    const tbody = $("sheetBody");
    if (!tbody) return;

    const devices = Array.from(sheetDevices.values());

    if (!devices.length) {
        renderSheetEmpty("No devices are currently assigned to this cart.");
        setDeviceCount(0);
        return;
    }

    tbody.innerHTML = devices.map((device, index) => `
    <tr class="device-row" data-device-id="${escapeHtml(device.id)}">
      <td class="row-index">${index + 1}</td>
      <td>
        <button class="mini-btn remove" type="button" data-remove-id="${escapeHtml(device.id)}">
          Remove
        </button>
      </td>
      <td class="mono">${escapeHtml(device.asset_tag || "")}</td>
      <td class="mono">${escapeHtml(device.serial || "")}</td>
      <td>${escapeHtml(device.model_name || "")}</td>
      <td>${escapeHtml(device.location_name || "")}</td>
      <td>
        ${device.asset_url ? `<a class="snipe-link" href="${escapeHtml(device.asset_url)}" target="_blank" rel="noopener">Open</a>` : "—"}
      </td>
    </tr>
  `).join("");

    tbody.querySelectorAll("[data-remove-id]").forEach(btn => {
        btn.addEventListener("click", event => {
            event.stopPropagation();
            requestRemoveDevice(btn.dataset.removeId);
        });
    });

    tbody.querySelectorAll(".device-row").forEach(row => {
        row.addEventListener("click", event => {
            if (event.target.closest("a") || event.target.closest("button")) return;

            const device = sheetDevices.get(String(row.dataset.deviceId));
            if (device) {
                openDeviceDetailModal(device);
            }
        });
    });

    setDeviceCount(devices.length);
}

function bindSyncButton() {
    $("syncSnipeBtn")?.addEventListener("click", async () => {
        const btn = $("syncSnipeBtn");

        if (btn) {
            btn.disabled = true;
            btn.classList.add("is-syncing");
            btn.innerHTML = `
                <span class="btn-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 12a9 9 0 0 0-15.2-6.5L3 8" />
                    <path d="M3 3v5h5" />
                    <path d="M3 12a9 9 0 0 0 15.2 6.5L21 16" />
                    <path d="M21 21v-5h-5" />
                    </svg>
                </span>
                <span>Syncing...</span>
            `;
        }

        setStatus("Syncing Snipe-IT catalog...", true);

        try {
            await apiPost("/api/sync-snipe", {}, "Snipe-IT sync failed.");
            await loadMyCarts();

            if (selectedCart) {
                await selectCart(selectedCart);
            }

            setStatus("Snipe-IT sync complete.", true);
        } catch (err) {
            setStatus(err.message || "Snipe-IT sync failed.", false);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.classList.remove("is-syncing");
                btn.innerHTML = `
                    <span class="btn-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 12a9 9 0 0 0-15.2-6.5L3 8" />
                        <path d="M3 3v5h5" />
                        <path d="M3 12a9 9 0 0 0 15.2 6.5L21 16" />
                        <path d="M21 21v-5h-5" />
                        </svg>
                    </span>
                    <span>Sync Snipe-IT</span>
                `;
            }
        }
    });
}

function bindConfirmModal() {
    $("cancelConfirmBtn")?.addEventListener("click", closeConfirmModal);

    $("confirmActionBtn")?.addEventListener("click", async () => {
        if (!pendingAction) {
            closeConfirmModal();
            return;
        }

        const action = pendingAction.action;
        closeConfirmModal();

        if (typeof action === "function") {
            await action();
        }
    });
}

function openConfirmModal({ title, message, messageHtml, buttonText, action }) {
    pendingAction = { action };

    const titleEl = $("confirmTitle");
    const messageEl = $("confirmMessage");
    const buttonEl = $("confirmActionBtn");
    const modalEl = $("confirmModal");

    if (titleEl) titleEl.textContent = title || "Confirm";

    if (messageEl) {
        if (messageHtml) {
            messageEl.innerHTML = messageHtml;
        } else {
            messageEl.textContent = message || "Continue?";
        }
    }

    if (buttonEl) buttonEl.textContent = buttonText || "Continue";
    if (modalEl) modalEl.classList.remove("hidden");
}

function closeConfirmModal() {
    pendingAction = null;
    $("confirmModal")?.classList.add("hidden");
}

function bindDeviceDetailModal() {
    $("closeDeviceDetailBtn")?.addEventListener("click", closeDeviceDetailModal);

    $("deviceDetailModal")?.addEventListener("click", event => {
        if (event.target.id === "deviceDetailModal") {
            closeDeviceDetailModal();
        }
    });
}

function openDeviceDetailModal(device) {
    const title = $("deviceDetailTitle");
    const body = $("deviceDetailBody");
    const modal = $("deviceDetailModal");

    if (!title || !body || !modal) return;

    title.textContent = device.asset_tag
        ? `Asset ${device.asset_tag}`
        : device.name || device.serial || "Device";

    const detailRows = [
        ["Asset Tag", device.asset_tag || "—"],
        ["Serial", device.serial || "—"],
        ["Name", device.name || "—"],
        ["Model", device.model_name || "—"],
        ["Status", device.status_name || "—"],
        ["Assigned To", device.assigned_name || "—"],
        ["Location", device.location_name || "—"],
        ["Snipe-IT", device.asset_url ? `<a class="snipe-link" href="${escapeHtml(device.asset_url)}" target="_blank" rel="noopener">Open Device</a>` : "—"]
    ];

    body.innerHTML = `
    <div class="device-detail-grid">
      ${detailRows.map(([label, value]) => `
        <div class="detail-item">
          <span class="detail-label">${escapeHtml(label)}</span>
          <span class="detail-value">${label === "Snipe-IT" ? value : escapeHtml(value)}</span>
        </div>
      `).join("")}
    </div>

    <div class="device-detail-actions">
      <button class="media-btn ghost" type="button" id="detailMoveBtn">Move Device</button>
      <button class="media-btn danger" type="button" id="detailRemoveBtn">Remove from Cart</button>
    </div>
  `;

    $("detailRemoveBtn")?.addEventListener("click", () => {
        closeDeviceDetailModal();
        requestRemoveDevice(device.id);
    });

    $("detailMoveBtn")?.addEventListener("click", () => {
    closeDeviceDetailModal();
    openMoveDeviceModal(device);
    });

    modal.classList.remove("hidden");
}

function closeDeviceDetailModal() {
    $("deviceDetailModal")?.classList.add("hidden");
}

function prependRecent(action, device, cart, ok, message) {
    const tbody = $("recentBody");
    if (!tbody) return;

    const tr = document.createElement("tr");
    tr.className = ok ? "ok" : "bad";

    tr.innerHTML = `
    <td class="mono">${escapeHtml(new Date().toISOString())}</td>
    <td>${escapeHtml(friendlyAction(action))}</td>
    <td>${escapeHtml(currentUser?.display_name || currentUser?.email || "—")}</td>
    <td class="mono">${escapeHtml(device?.asset_tag || device?.name || device?.id || "—")}</td>
    <td class="mono">${escapeHtml(device?.serial || "—")}</td>
    <td class="mono">${escapeHtml(cart?.asset_tag || cart?.name || cart?.id || "—")}</td>
    <td>${ok ? "Success" : "Error"}</td>
    <td class="muted">${escapeHtml(message || "")}</td>
    `;

    tbody.prepend(tr);
}

function showSelectedCartPanel() {
    $("selectedCartPanel")?.classList.remove("hidden");
}

function hideSelectedCartPanel() {
    $("selectedCartPanel")?.classList.add("hidden");
    selectedCart = null;
    pendingMoveDevice = null;
    sheetDevices.clear();
    setDeviceCount("—");
    renderSheetEmpty("Select a cart to load assigned devices.");

    if ($("cartTitle")) $("cartTitle").textContent = "Select a Cart";
    if ($("cartSubtitle")) $("cartSubtitle").textContent = "Choose a cart from My Carts or Find Cart to load assigned devices.";

    loadMyCarts();
}

function requestMoveDeviceToCart(device, destinationCart) {
    if (!device || !destinationCart) return;

    openConfirmModal({
        title: "Move Device?",
        message: `Move asset ${device.asset_tag || device.serial || device.id} to ${destinationCart.asset_tag || destinationCart.name}?`,
        buttonText: "Move Device",
        action: async () => {
            const previousCart = selectedCart;

            selectedCart = destinationCart;
            await addDeviceToCart(device, true);

            pendingMoveDevice = null;

            if (previousCart && String(previousCart.id) !== String(destinationCart.id)) {
                await selectCart(destinationCart);
            }
        }
    });
}

function bindMoveDeviceModal() {
  $("closeMoveDeviceBtn")?.addEventListener("click", closeMoveDeviceModal);
  $("moveCartSearchBtn")?.addEventListener("click", searchMoveDestinationCarts);

  $("moveCartSearch")?.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchMoveDestinationCarts();
    }
  });

  $("moveDeviceModal")?.addEventListener("click", event => {
    if (event.target.id === "moveDeviceModal") {
      closeMoveDeviceModal();
    }
  });
}

function openMoveDeviceModal(device) {
  moveModalDevice = device;

  $("moveDeviceTitle").textContent = `Move ${device.asset_tag || device.serial || "Device"}`;
  $("moveDeviceSubtitle").textContent = "Search for the destination cart to move this device into.";

  if ($("moveCartSearch")) {
    $("moveCartSearch").value = "";
  }

  if ($("moveCartResults")) {
    $("moveCartResults").innerHTML = "";
  }

  $("moveDeviceModal")?.classList.remove("hidden");
  setTimeout(() => $("moveCartSearch")?.focus(), 50);
}

function closeMoveDeviceModal() {
  moveModalDevice = null;
  $("moveDeviceModal")?.classList.add("hidden");
}

async function searchMoveDestinationCarts() {
  const query = ($("moveCartSearch")?.value || "").trim();
  const resultsEl = $("moveCartResults");

  if (!resultsEl) return;

  if (query.length < 2) {
    resultsEl.innerHTML = `<div class="muted">Type at least 2 characters.</div>`;
    return;
  }

  resultsEl.innerHTML = `<div class="muted">Searching destination carts...</div>`;

  try {
    const data = await apiGet(`/api/carts?q=${encodeURIComponent(query)}`, "Cart search failed.");
    renderMoveDestinationCarts(data.carts || []);
  } catch (err) {
    resultsEl.innerHTML = `<div class="muted">${escapeHtml(err.message || "Cart search failed.")}</div>`;
  }
}

function renderMoveDestinationCarts(carts) {
  const el = $("moveCartResults");
  if (!el) return;

  if (!carts.length) {
    el.innerHTML = `<div class="muted">No destination carts found.</div>`;
    return;
  }

  el.innerHTML = carts.map(cart => `
    <div class="cart-card">
      <button class="cart-main" type="button" data-move-cart-id="${escapeHtml(cart.id)}">
        <strong>${escapeHtml(cartDisplayName(cart))}</strong>
        <div class="muted">
          ${escapeHtml(cart.model_name || "")}
          ${cart.location_name ? " • " + escapeHtml(cart.location_name) : ""}
        </div>
      </button>
      <div class="cart-actions">
        ${cart.asset_url ? `<a class="snipe-link" href="${escapeHtml(cart.asset_url)}" target="_blank" rel="noopener">Snipe-IT</a>` : ""}
      </div>
    </div>
  `).join("");

  el.querySelectorAll("[data-move-cart-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const destinationCart = carts.find(c => String(c.id) === String(btn.dataset.moveCartId));
      if (!destinationCart || !moveModalDevice) return;

      const deviceToMove = moveModalDevice;
      closeMoveDeviceModal();

      window.setTimeout(() => {
        openConfirmModal({
          title: "Move Device?",
          message: `Move asset ${deviceToMove.asset_tag || deviceToMove.serial || deviceToMove.id} to ${destinationCart.asset_tag || destinationCart.name}?`,
          buttonText: "Move Device",
          action: async () => moveDeviceToCart(deviceToMove, destinationCart)
        });
      }, 75);
    });
  });
}

async function moveDeviceToCart(device, destinationCart) {
  if (!device || !destinationCart) return;

  const sourceCart = selectedCart;

  setStatus("Moving device to destination cart...", true);

  try {
    const data = await apiPost(
      "/api/add-to-cart",
      {
        cart_id: destinationCart.id,
        device_id: device.id,
        force: true
      },
      "Unable to move device."
    );

    if (sourceCart && String(sourceCart.id) !== String(destinationCart.id)) {
      sheetDevices.delete(String(device.id));
      renderSheet();
      setDeviceCount(sheetDevices.size);
    }

    prependRecent(
      "moved_to_cart",
      device,
      destinationCart,
      true,
      data.message || "Device moved to destination cart."
    );

    selectedCart = destinationCart;
    await selectCart(destinationCart);

    setStatus("Device moved to destination cart.", true);
  } catch (err) {
    setStatus(err.message || "Unable to move device.", false);
  }
}

function friendlyAction(action) {
  const labels = {
    add_to_cart: "Added to Cart",
    added_to_cart: "Added to Cart",
    remove_from_cart: "Removed from Cart",
    removed_from_cart: "Removed from Cart",
    moved_to_cart: "Moved to Cart",
    claimed_cart: "Claimed Cart",
    move_failed: "Move Failed",
    add_failed: "Add Failed"
  };

  return labels[action] || String(action || "").replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());
}