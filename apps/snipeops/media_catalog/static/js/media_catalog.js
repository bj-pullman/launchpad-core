document.addEventListener("DOMContentLoaded", initMediaCatalog);

const MEDIA_CATALOG_BASE = "/snipeops/media-catalog";

let currentUser = null;
let selectedCart = null;
let pendingAction = null;
let pendingMoveDevice = null;
let moveModalDevice = null;
let assignOwnerCart = null;
let myCartsCache = [];
let myCartsPage = 1;
let myCartsPageSize = 25;
let myCartsSearchQuery = "";
let ownershipOwnersCache = [];
let ownershipSelectedUser = null;
let locationOptionsCache = null;

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
    bindAssignOwnerModal();
    bindMediaTabs();
    bindOwnershipManagement();
    bindExportButtons();

    renderSheetEmpty("Select a cart to load assigned devices.");
    setDeviceCount("—");
    hideSelectedCartPanel(false);

    try {
        await loadCurrentUser();
        await loadMyCarts();
        preloadLocationOptions();
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

    if (!selectedCart) {
        el.innerHTML = `<div class="muted">Loading your carts...</div>`;
    }

    try {
        const data = await apiGet("/api/my-carts", "Unable to load your carts.");
        myCartsCache = data.carts || [];

        renderMyCartsTable(myCartsCache);

        if (selectedCart) {
            collapseMyCartsTable();
        }
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
        renderCartCards("cartResults", data.carts || [], { showOwnershipButton: true });
        setStatus(`Found ${(data.carts || []).length} cart(s).`, true);
    } catch (err) {
        resultsEl.innerHTML = `<div class="muted">${escapeHtml(err.message || "Cart search failed.")}</div>`;
        setStatus(err.message || "Cart search failed.", false);
    }
}

function renderMyCartsTable(carts) {
    const el = $("myCarts");
    if (!el) return;

    myCartsCache = carts || [];

    if (!myCartsCache.length) {
        el.innerHTML = `<div class="muted">No carts found.</div>`;
        return;
    }

    el.innerHTML = `
        <div id="myCartsExpandedView">
            <div class="media-table-tools">
                <input
                    id="myCartsFilter"
                    class="media-input"
                    placeholder="Search carts, teacher, room, or owner..."
                    value="${escapeHtml(myCartsSearchQuery)}"
                >

                <div class="media-pagination">
                    <label>
                        Rows
                        <select id="myCartsPageSize" class="media-select">
                            <option value="25" ${myCartsPageSize === 25 ? "selected" : ""}>25</option>
                            <option value="50" ${myCartsPageSize === 50 ? "selected" : ""}>50</option>
                            <option value="100" ${myCartsPageSize === 100 ? "selected" : ""}>100</option>
                        </select>
                    </label>

                    <button id="myCartsPrevPage" class="mini-btn" type="button">Prev</button>
                    <span id="myCartsPageLabel" class="muted">Page 1 of 1</span>
                    <button id="myCartsNextPage" class="mini-btn" type="button">Next</button>
                </div>
            </div>

            <div class="sheet-wrap my-carts-sheet-wrap">
                <table class="media-sheet my-carts-table">
                    <thead>
                        <tr>
                            <th>Move</th>
                            <th>Index</th>
                            <th>Cart</th>
                            <th>Teacher Name</th>
                            <th>Room Number</th>
                            <th>Location</th>
                            <th>Devices</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="myCartsBody"></tbody>
                </table>
            </div>

            <div id="myCartsEmptyState" class="media-empty-state hidden">
                No carts match your search.
            </div>
        </div>

        <div id="myCartsCollapsedView" class="active-cart-summary hidden">
            <div>
                <p class="media-eyebrow">Active Cart</p>
                <strong id="activeCartSummaryTitle">No cart selected</strong>
                <p id="activeCartSummarySubtitle" class="muted">The cart list is collapsed while you are adding devices.</p>
            </div>

            <div class="media-section-actions">
                <button id="expandMyCartsBtn" class="media-btn ghost" type="button">Expand My Carts</button>
                <button id="deselectCartBtn" class="media-btn ghost" type="button">Deselect Cart</button>
            </div>
        </div>
    `;

    $("myCartsFilter")?.addEventListener("input", event => {
        myCartsSearchQuery = event.target.value.toLowerCase().trim();
        myCartsPage = 1;
        drawCurrentMyCartsPage();
    });

    $("myCartsPageSize")?.addEventListener("change", event => {
        myCartsPageSize = Number.parseInt(event.target.value, 10) || 25;
        myCartsPage = 1;
        drawCurrentMyCartsPage();
    });

    $("myCartsPrevPage")?.addEventListener("click", () => {
        myCartsPage = Math.max(1, myCartsPage - 1);
        drawCurrentMyCartsPage();
    });

    $("myCartsNextPage")?.addEventListener("click", () => {
        const filtered = getFilteredMyCarts();
        const totalPages = Math.max(1, Math.ceil(filtered.length / myCartsPageSize));
        myCartsPage = Math.min(totalPages, myCartsPage + 1);
        drawCurrentMyCartsPage();
    });

    $("expandMyCartsBtn")?.addEventListener("click", expandMyCartsTable);
    $("deselectCartBtn")?.addEventListener("click", () => hideSelectedCartPanel(true));

    drawCurrentMyCartsPage();

    if (selectedCart) {
        collapseMyCartsTable();
    }
}

function bindMyCartTableEvents(carts) {
    document.querySelectorAll("#myCartsBody .my-cart-row").forEach(row => {
        row.addEventListener("click", event => {
            if (
                event.target.closest("button") ||
                event.target.closest("a") ||
                event.target.closest("input") ||
                event.target.closest(".inline-edit-control") ||
                event.target.closest(".drag-handle")
            ) {
                return;
            }

            const cart = carts.find(c => String(c.id) === String(row.dataset.cartId));
            if (cart) selectCart(cart);
        });
    });

    document.querySelectorAll("#myCartsBody [data-open-cart-id]").forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const cart = carts.find(c => String(c.id) === String(btn.dataset.openCartId));
            if (!cart) return;

            selectCart(cart);
        });
    });

    document.querySelectorAll("#myCartsBody [data-cart-details-id]").forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const cart = carts.find(c => String(c.id) === String(btn.dataset.cartDetailsId));
            if (!cart) return;

            openCartDetails(cart);
        });
    });

    document.querySelectorAll("#myCartsBody .inline-edit-btn").forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const wrapper = btn.closest(".inline-edit-control");
            if (!wrapper) return;

            activateInlineEdit(wrapper, carts);
        });
    });

    document.querySelectorAll("#myCartsBody .cart-index-input").forEach(input => {
        input.addEventListener("change", async () => {
            await reorderCart(input.dataset.cartId, input.value);
        });

        input.addEventListener("click", event => {
            event.stopPropagation();
        });
    });

    bindDragReorder();
}

async function reorderCart(cartId, newIndex) {
    const parsedIndex = Number.parseInt(newIndex, 10);

    if (!cartId || !Number.isFinite(parsedIndex) || parsedIndex < 1) {
        setStatus("Enter a valid cart index.", false);
        await loadMyCarts();
        return;
    }

    try {
        const data = await apiPost(
            "/api/my-carts/reorder",
            {
                cart_id: cartId,
                new_index: parsedIndex,
            },
            "Unable to reorder carts."
        );

        myCartsCache = data.carts || [];
        renderMyCartsTable(myCartsCache);

        if (selectedCart) {
            collapseMyCartsTable();
        }

        setStatus("Cart order updated.", true);
    } catch (err) {
        setStatus(err.message || "Unable to reorder carts.", false);
        await loadMyCarts();
    }
}

function bindDragReorder() {
    const tbody = $("myCartsBody");
    if (!tbody) return;

    let draggingRow = null;

    tbody.querySelectorAll("tr[draggable='true']").forEach(row => {
        row.addEventListener("dragstart", () => {
            draggingRow = row;
            row.classList.add("dragging");
        });

        row.addEventListener("dragend", async () => {
            if (!draggingRow) return;

            draggingRow.classList.remove("dragging");

            const rows = Array.from(tbody.querySelectorAll("tr"));
            const cartId = draggingRow.dataset.cartId;
            const newIndex = rows.indexOf(draggingRow) + 1;

            draggingRow = null;

            await reorderCart(cartId, newIndex);
        });

        row.addEventListener("dragover", event => {
            event.preventDefault();

            const afterElement = getDragAfterElement(tbody, event.clientY);

            if (!draggingRow) return;

            if (afterElement == null) {
                tbody.appendChild(draggingRow);
            } else {
                tbody.insertBefore(draggingRow, afterElement);
            }
        });
    });
}

function getDragAfterElement(container, y) {
    const draggableElements = [
        ...container.querySelectorAll("tr[draggable='true']:not(.dragging)")
    ];

    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;

        if (offset < 0 && offset > closest.offset) {
            return {
                offset,
                element: child,
            };
        }

        return closest;
    }, {
        offset: Number.NEGATIVE_INFINITY,
        element: null,
    }).element;
}

function renderCartCards(containerId, carts, options = {}) {
    const el = $(containerId);
    if (!el) return;

    const showOwnershipButton = options.showOwnershipButton !== false;
    const canManageOwnership = Boolean(window.MEDIA_CATALOG_CAN_MANAGE_OWNERSHIP);

    if (!carts.length) {
        el.innerHTML = `<div class="muted">No carts found.</div>`;
        return;
    }

    el.innerHTML = carts.map(cart => {
        const ownership = cart.ownership || null;
        const ownerDisplay = ownership?.owner_display_name || "Unknown user";
        const ownerEmail = ownership?.owner_email || "";
        const ownerName = ownerEmail ? `${ownerDisplay} (${ownerEmail})` : ownerDisplay;
        const ownedByCurrentUser =
            currentUser &&
            ownership &&
            Number(ownership.owner_user_id) === Number(currentUser.id);

        let ownershipText = "Unassigned";
        if (ownedByCurrentUser) {
            ownershipText = "Owned by: You";
        } else if (ownership && ownerName) {
            ownershipText = `Owned by: ${ownerName}`;
        }

        const ownershipButton = showOwnershipButton
            ? `<button class="mini-btn take-ownership" type="button" data-cart-id="${escapeHtml(cart.id)}">${ownedByCurrentUser ? "Refresh Ownership" : "Take Ownership"}</button>`
            : "";

        const assignOwnerButton = canManageOwnership
            ? `<button class="mini-btn assign-owner" type="button" data-cart-id="${escapeHtml(cart.id)}">Assign Owner</button>`
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
                    <div class="cart-action-group">
                        ${ownershipButton}
                        ${assignOwnerButton}
                    </div>
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
                hideSelectedCartPanel(true);
                setStatus("Cart unselected.", true);
                return;
            }

            selectCart(cart);
        });
    });

    el.querySelectorAll(".take-ownership").forEach(btn => {
        btn.addEventListener("click", event => {
            event.stopPropagation();
            const cart = carts.find(c => String(c.id) === String(btn.dataset.cartId));
            if (cart) requestTakeOwnership(cart);
        });
    });

    el.querySelectorAll(".assign-owner").forEach(btn => {
        btn.addEventListener("click", event => {
            event.stopPropagation();
            const cart = carts.find(c => String(c.id) === String(btn.dataset.cartId));
            if (cart) openAssignOwnerModal(cart);
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
        const ownership = cart.ownership || {};
        const owner = ownership.media_specialist_owner
            || ownership.owner_display_name
            || ownership.owner_email
            || "Unassigned";

        const teacher = ownership.teacher_name ? ` • Teacher: ${ownership.teacher_name}` : "";
        const room = ownership.room_number ? ` • Room: ${ownership.room_number}` : "";

        subtitle.innerHTML = renderSelectedCartMeta(cart);
    }

    renderSheetEmpty("Loading assigned devices...");
    setStatus("Loading cart devices...", true);
    collapseMyCartsTable();

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
        updateActiveCartSummary();
        $("deviceInput")?.focus();
    } catch (err) {
        renderSheetEmpty(err.message || "Unable to load cart devices.");
        setDeviceCount("—");
        setStatus(err.message || "Unable to load cart devices.", false);
    }
}

function showSelectedCartPanel() {
    $("selectedCartPanel")?.classList.remove("hidden");
}

function hideSelectedCartPanel(reloadCarts = true) {
    $("selectedCartPanel")?.classList.add("hidden");

    selectedCart = null;
    pendingMoveDevice = null;
    sheetDevices.clear();
    setDeviceCount("—");
    renderSheetEmpty("Select a cart to load assigned devices.");

    if ($("cartTitle")) $("cartTitle").textContent = "Select a Cart";
    if ($("cartSubtitle")) $("cartSubtitle").textContent = "Choose a cart from My Carts to add devices.";

    expandMyCartsTable();

    if (reloadCarts) {
        loadMyCarts();
    }
}

function collapseMyCartsTable() {
    const expanded = $("myCartsExpandedView");
    const collapsed = $("myCartsCollapsedView");

    if (expanded) expanded.classList.add("hidden");
    if (collapsed) collapsed.classList.remove("hidden");

    updateActiveCartSummary();
}

function expandMyCartsTable() {
    const expanded = $("myCartsExpandedView");
    const collapsed = $("myCartsCollapsedView");

    if (expanded) expanded.classList.remove("hidden");
    if (collapsed) collapsed.classList.add("hidden");
}

function updateActiveCartSummary() {
    if (!selectedCart) return;

    const title = $("activeCartSummaryTitle");
    const subtitle = $("activeCartSummarySubtitle");
    const ownership = selectedCart.ownership || {};

    if (title) {
        title.textContent = selectedCart.asset_tag
            ? `Cart ${selectedCart.asset_tag}`
            : selectedCart.name || "Selected Cart";
    }

    if (subtitle) {
        const owner = ownership.media_specialist_owner
            || ownership.owner_display_name
            || ownership.owner_email
            || "Unassigned";

        const teacher = ownership.teacher_name ? ` • Teacher: ${ownership.teacher_name}` : "";
        const room = ownership.room_number ? ` • Room: ${ownership.room_number}` : "";

        subtitle.textContent = `${selectedCart.name || ""} • Owner: ${owner}${teacher}${room}`;
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
        prependRecent("add_failed", device, selectedCart, false, err.message || "Unable to add device to cart.");
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
        prependRecent("remove_failed", device, selectedCart, false, err.message || "Unable to remove device from cart.");
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
        <td class="result-cell">${ok ? "Success" : "Error"}</td>
        <td class="muted">${escapeHtml(message || "")}</td>
    `;

    tbody.prepend(tr);
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
        prependRecent("move_failed", device, destinationCart, false, err.message || "Unable to move device.");
        setStatus(err.message || "Unable to move device.", false);
    }
}

function friendlyAction(action) {
    const labels = {
        add_to_cart: "Added to Cart",
        added_to_cart: "Added to Cart",
        remove_from_cart: "Removed from Cart",
        removed_from_cart: "Removed from Cart",
        remove_failed: "Remove Failed",
        moved_to_cart: "Moved to Cart",
        claimed_cart: "Claimed Cart",
        move_failed: "Move Failed",
        add_failed: "Add Failed",
        assigned_cart_owner: "Assigned Cart Owner",
        updated_cart_metadata: "Updated Cart Fields",
        reordered_cart: "Reordered Cart",
        admin_updated_cart_metadata: "Admin Updated Cart Fields",
        updated_cart_location: "Updated Cart Location",
    };

    return labels[action] || String(action || "").replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());
}

function bindAssignOwnerModal() {
    $("closeAssignOwnerBtn")?.addEventListener("click", closeAssignOwnerModal);
    $("ownerSearchBtn")?.addEventListener("click", searchOwnerUsers);

    $("ownerSearch")?.addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            searchOwnerUsers();
        }
    });

    $("assignOwnerModal")?.addEventListener("click", event => {
        if (event.target.id === "assignOwnerModal") {
            closeAssignOwnerModal();
        }
    });
}

function openAssignOwnerModal(cart) {
    assignOwnerCart = cart;

    $("assignOwnerTitle").textContent = `Assign Owner`;
    $("assignOwnerSubtitle").textContent = `${cart.asset_tag ? "#" + cart.asset_tag : "No tag"} • ${cart.name || "Unnamed cart"}`;

    if ($("ownerSearch")) {
        $("ownerSearch").value = "";
    }

    if ($("ownerResults")) {
        $("ownerResults").innerHTML = "";
    }

    $("assignOwnerModal")?.classList.remove("hidden");
    setTimeout(() => $("ownerSearch")?.focus(), 50);
}

function closeAssignOwnerModal() {
    assignOwnerCart = null;
    $("assignOwnerModal")?.classList.add("hidden");
}

async function searchOwnerUsers() {
    const query = ($("ownerSearch")?.value || "").trim();
    const resultsEl = $("ownerResults");

    if (!resultsEl) return;

    if (query.length < 2) {
        resultsEl.innerHTML = `<div class="muted">Type at least 2 characters.</div>`;
        return;
    }

    resultsEl.innerHTML = `<div class="muted">Searching users...</div>`;

    try {
        const data = await apiGet(`/api/users/search?q=${encodeURIComponent(query)}`, "User search failed.");
        renderOwnerUserResults(data.users || []);
    } catch (err) {
        resultsEl.innerHTML = `<div class="muted">${escapeHtml(err.message || "User search failed.")}</div>`;
    }
}

function renderOwnerUserResults(users) {
    const el = $("ownerResults");
    if (!el) return;

    if (!users.length) {
        el.innerHTML = `<div class="muted">No active users found.</div>`;
        return;
    }

    el.innerHTML = users.map(user => `
        <button class="owner-result-card" type="button" data-user-id="${escapeHtml(user.id)}">
            <strong>${escapeHtml(user.display_name || user.email || "Unnamed User")}</strong>
            <span>${escapeHtml(user.email || "")}</span>
            <span class="muted">
                ${escapeHtml(user.department || "")}
                ${user.office_location ? " • " + escapeHtml(user.office_location) : ""}
            </span>
        </button>
    `).join("");

    el.querySelectorAll(".owner-result-card").forEach(btn => {
        btn.addEventListener("click", () => {
            const user = users.find(u => String(u.id) === String(btn.dataset.userId));
            if (!user || !assignOwnerCart) return;

            const cart = assignOwnerCart;

            closeAssignOwnerModal();

            window.setTimeout(() => {
                openConfirmModal({
                    title: "Assign Cart Owner?",
                    messageHtml: `
                        <p class="confirm-copy">
                            Assign this cart to the selected user.
                        </p>

                        <div class="ownership-detail-card">
                            <div class="ownership-detail-heading">Assignment Details</div>

                            <div class="ownership-detail-row">
                                <div class="ownership-detail-label">Cart</div>
                                <div class="ownership-detail-value">${escapeHtml(cart.asset_tag ? "#" + cart.asset_tag + " • " + (cart.name || "") : cart.name || "Unnamed cart")}</div>
                            </div>

                            <div class="ownership-detail-row">
                                <div class="ownership-detail-label">Owner</div>
                                <div class="ownership-detail-value">${escapeHtml(user.display_name || user.email || "Unnamed User")}</div>
                            </div>

                            <div class="ownership-detail-row">
                                <div class="ownership-detail-label">Username</div>
                                <div class="ownership-detail-value">${escapeHtml(user.email || "Not recorded")}</div>
                            </div>
                        </div>
                    `,
                    buttonText: "Assign Owner",
                    action: async () => assignCartOwner(cart, user)
                });
            }, 75);
        });
    });
}

async function assignCartOwner(cart, user) {
    setStatus("Assigning cart owner...", true);

    try {
        const data = await apiPost(
            `/api/carts/${cart.id}/assign-owner`,
            { owner_user_id: user.id },
            "Unable to assign owner."
        );

        prependRecent(
            "assigned_cart_owner",
            null,
            data.cart || cart,
            true,
            data.message || "Cart owner assigned."
        );

        await loadMyCarts();

        if (ownershipSelectedUser) {
            await loadOwnershipOwners();
            await loadOwnershipUserCarts(ownershipSelectedUser);
}

        const cartResults = $("cartResults");
        if (cartResults) {
            cartResults.innerHTML = "";
        }

        setStatus(data.message || "Cart owner assigned.", true);

        if (selectedCart && String(selectedCart.id) === String(cart.id) && data.cart) {
            await selectCart(data.cart);
        }
    } catch (err) {
        setStatus(err.message || "Unable to assign owner.", false);
    }
}

function openCartDetails(cart) {
    const ownership = cart.ownership || {};

    openConfirmModal({
        title: "Cart Details",
        messageHtml: `
            <div class="ownership-detail-card">
                <div class="ownership-detail-heading">Cart Information</div>

                <div class="ownership-detail-row">
                    <div class="ownership-detail-label">Cart</div>
                    <div class="ownership-detail-value">${escapeHtml(cartDisplayName(cart))}</div>
                </div>

                <div class="ownership-detail-row">
                    <div class="ownership-detail-label">Media Specialist</div>
                    <div class="ownership-detail-value">${escapeHtml(ownership.owner_display_name || ownership.owner_email || "Unassigned")}</div>
                </div>

                <div class="ownership-detail-row">
                    <div class="ownership-detail-label">Teacher</div>
                    <div class="ownership-detail-value">${escapeHtml(ownership.teacher_name || "—")}</div>
                </div>

                <div class="ownership-detail-row">
                    <div class="ownership-detail-label">Room</div>
                    <div class="ownership-detail-value">${escapeHtml(ownership.room_number || "—")}</div>
                </div>
            </div>
        `,
        buttonText: "Close",
        action: async () => {}
    });
}

function bindMediaTabs() {
    document.querySelectorAll(".settings-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            const target = tab.dataset.tab;

            document.querySelectorAll(".settings-tab").forEach(item => {
                item.classList.toggle("active", item === tab);
            });

            document.querySelectorAll(".settings-tab-panel").forEach(panel => {
                panel.classList.toggle("active", panel.dataset.panel === target);
            });
        });
    });
}

function bindExportButtons() {
    document.addEventListener("click", event => {
        const exportMyCartsBtn = event.target.closest("#exportMyCartsBtn");
        const exportSelectedCartBtn = event.target.closest("#exportSelectedCartBtn");
        const exportAllAssignedCartsBtn = event.target.closest("#exportAllAssignedCartsBtn");

        if (exportMyCartsBtn) {
            event.preventDefault();
            window.location.href = `${MEDIA_CATALOG_BASE}/export/my-carts.pdf`;
            return;
        }

        if (exportSelectedCartBtn) {
            event.preventDefault();

            if (!selectedCart || !selectedCart.id) {
                setStatus("Select a cart before exporting.", false);
                return;
            }

            window.location.href =
                `${MEDIA_CATALOG_BASE}/export/cart/${encodeURIComponent(selectedCart.id)}.pdf`;
            return;
        }

        if (exportAllAssignedCartsBtn) {
            event.preventDefault();
            window.location.href =
                `${MEDIA_CATALOG_BASE}/export/all-assigned-carts.pdf`;
        }
    });
}


function bindOwnershipManagement() {
    if (!window.MEDIA_CATALOG_CAN_VIEW_OWNERSHIP) return;

    $("refreshOwnershipBtn")?.addEventListener("click", loadOwnershipOwners);

    document.querySelectorAll('[data-tab="ownership-management"]').forEach(tab => {
        tab.addEventListener("click", loadOwnershipOwners);
    });
}


async function loadOwnershipOwners() {
    const el = $("ownershipOwners");
    const cartsEl = $("ownershipUserCarts");

    if (!el) return;

    el.innerHTML = `<div class="muted">Loading assigned cart owners...</div>`;

    if (cartsEl && !ownershipSelectedUser) {
        cartsEl.innerHTML = "";
    }

    try {
        const data = await apiGet("/api/ownership/owners", "Unable to load assigned cart owners.");
        ownershipOwnersCache = data.owners || [];
        renderOwnershipOwners(ownershipOwnersCache);
        setStatus(`Loaded ${ownershipOwnersCache.length} assigned cart owner(s).`, true);
    } catch (err) {
        el.innerHTML = `<div class="muted">${escapeHtml(err.message || "Unable to load assigned cart owners.")}</div>`;
        setStatus(err.message || "Unable to load assigned cart owners.", false);
    }
}


function renderOwnershipOwners(owners) {
    const el = $("ownershipOwners");
    if (!el) return;

    if (!owners.length) {
        el.innerHTML = `<div class="muted">No assigned cart owners found.</div>`;
        return;
    }

    el.innerHTML = `
        <div class="sheet-wrap compact">
            <table class="media-sheet ownership-table">
                <thead>
                        <th>User</th>
                        <th>Email</th>
                        <th>Carts</th>
                        <th>Last Updated</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${owners.map(owner => `
                        <tr class="ownership-owner-row"
                            data-owner-id="${escapeHtml(owner.owner_user_id)}">
                            <td>${escapeHtml(owner.owner_display_name || owner.owner_email || "Unknown User")}</td>
                            <td>
                                <span class="email-pill">
                                    ${escapeHtml(owner.owner_email || "No email")}
                                </span>
                            </td>
                            <td>
                                <span class="cart-count-pill">
                                    ${escapeHtml(owner.cart_count || 0)}
                                </span>
                            </td>
                            <td>${escapeHtml(formatFriendlyDateTime(owner.last_updated_at))}</td>
                            <td>
                                <button class="mini-btn" type="button" data-view-owner-id="${escapeHtml(owner.owner_user_id)}">
                                    View Carts
                                </button>
                                <a class="mini-btn" href="${MEDIA_CATALOG_BASE}/export/user/${encodeURIComponent(owner.owner_user_id)}/carts.pdf">
                                    Export
                                </a>
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>
    `;

    el.querySelectorAll(".ownership-owner-row").forEach(row => {
        row.addEventListener("click", event => {
            if (
                event.target.closest("button") ||
                event.target.closest("a")
            ) {
                return;
            }

            const owner = owners.find(
                item => String(item.owner_user_id) === String(row.dataset.ownerId)
            );

            if (!owner) return;

            el.querySelectorAll(".ownership-owner-row").forEach(item => {
                item.classList.remove("active");
            });

            row.classList.add("active");
            loadOwnershipUserCarts(owner);
        });
    });

    el.querySelectorAll("[data-view-owner-id]").forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const owner = owners.find(
                item => String(item.owner_user_id) === String(btn.dataset.viewOwnerId)
            );

            if (!owner) return;

            el.querySelectorAll(".ownership-owner-row").forEach(item => {
                item.classList.toggle(
                    "active",
                    String(item.dataset.ownerId) === String(owner.owner_user_id)
                );
            });

            loadOwnershipUserCarts(owner);
        });
    });
}


async function loadOwnershipUserCarts(owner) {
    const el = $("ownershipUserCarts");
    if (!el) return;

    ownershipSelectedUser = owner;

    el.innerHTML = `<div class="muted">Loading carts for ${escapeHtml(owner.owner_display_name || owner.owner_email || "selected user")}...</div>`;

    try {
        const data = await apiGet(
            `/api/ownership/users/${encodeURIComponent(owner.owner_user_id)}/carts`,
            "Unable to load user carts."
        );

        renderOwnershipUserCarts(owner, data.carts || []);
    } catch (err) {
        el.innerHTML = `<div class="muted">${escapeHtml(err.message || "Unable to load user carts.")}</div>`;
        setStatus(err.message || "Unable to load user carts.", false);
    }
}


function renderOwnershipUserCarts(owner, carts) {
    const el = $("ownershipUserCarts");
    if (!el) return;

    const ownerName = owner.owner_display_name || owner.owner_email || "Selected User";

    if (!carts.length) {
        el.innerHTML = `
            <section class="media-subpanel">
                <h3>${escapeHtml(ownerName)} Carts</h3>
                <div class="muted">No carts assigned to this user.</div>
            </section>
        `;
        return;
    }

    el.innerHTML = `
        <section class="media-subpanel">
            <div class="media-section-head">
                <div>
                    <h3>${escapeHtml(ownerName)} Carts</h3>
                    <p class="muted">${escapeHtml(carts.length)} assigned cart(s).</p>
                </div>

                <div class="media-section-actions">
                    <a class="media-btn ghost" href="${MEDIA_CATALOG_BASE}/export/user/${encodeURIComponent(owner.owner_user_id)}/carts.pdf">
                        Export User Carts
                    </a>
                </div>
            </div>

            <div class="sheet-wrap compact">
                <table class="media-sheet ownership-carts-table">
                    <thead>
                        <tr>
                            <th>Cart</th>
                            <th>Teacher</th>
                            <th>Room</th>
                            <th>Location</th>
                            <th>Devices</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="ownershipUserCartsBody">
                        ${carts.map(cart => {
                            const ownership = cart.ownership || {};
                            return `
                                <tr data-admin-cart-id="${escapeHtml(cart.id)}">
                                    <td>
                                        <button class="link-button" type="button" data-admin-open-cart-id="${escapeHtml(cart.id)}">
                                            ${escapeHtml(cartDisplayName(cart))}
                                        </button>
                                        <div class="muted">${escapeHtml(cart.model_name || "")}</div>
                                    </td>
                                    <td>${renderAdminInlineEditField(cart.id, "teacher_name", ownership.teacher_name || "—")}</td>
                                    <td>${renderAdminInlineEditField(cart.id, "room_number", ownership.room_number || "—")}</td>
                                    <td>${renderLocationEditField(cart)}</td>
                                    <td>
                                        <span class="device-count-badge" data-admin-device-count-cart-id="${escapeHtml(cart.id)}">...</span>
                                    </td>
                                    <td>
                                        <button class="mini-btn" type="button" data-admin-assign-owner-id="${escapeHtml(cart.id)}">
                                            Assign Owner
                                        </button>
                                        <a class="mini-btn" href="${MEDIA_CATALOG_BASE}/export/cart/${encodeURIComponent(cart.id)}.pdf">
                                            Export
                                        </a>
                                        ${cart.asset_url ? `<a class="mini-btn" href="${escapeHtml(cart.asset_url)}" target="_blank" rel="noopener">Snipe-IT</a>` : ""}
                                    </td>
                                </tr>
                            `;
                        }).join("")}
                    </tbody>
                </table>
            </div>
        </section>
    `;

    bindOwnershipUserCartEvents(carts);
    loadAdminVisibleCartDeviceCounts(carts);
}


function bindOwnershipUserCartEvents(carts) {
    document.querySelectorAll("[data-admin-open-cart-id]").forEach(btn => {
        btn.addEventListener("click", () => {
            const cart = carts.find(item => String(item.id) === String(btn.dataset.adminOpenCartId));
            if (cart) {
                selectCart(cart);
                document.querySelector('[data-tab="cart-management"]')?.click();
            }
        });
    });

    bindLocationEditButtons(carts, "#ownershipUserCartsBody [data-location-cart-id]");

    document.querySelectorAll("[data-admin-assign-owner-id]").forEach(btn => {
        btn.addEventListener("click", () => {
            const cart = carts.find(item => String(item.id) === String(btn.dataset.adminAssignOwnerId));
            if (cart) openAssignOwnerModal(cart);
        });
    });

    document.querySelectorAll("#ownershipUserCartsBody .inline-edit-btn").forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const wrapper = btn.closest(".inline-edit-control");
            if (!wrapper) return;

            activateAdminInlineEdit(wrapper, carts);
        });
    });
}


async function loadAdminVisibleCartDeviceCounts(carts) {
    await Promise.allSettled(carts.map(async cart => {
        const cell = document.querySelector(`[data-admin-device-count-cart-id="${CSS.escape(String(cart.id))}"]`);
        if (!cell) return;

        try {
            const data = await apiGet(`/api/carts/${cart.id}/devices`, "Unable to load device count.");
            cell.textContent = String((data.devices || []).length);
        } catch {
            cell.textContent = "—";
        }
    }));
}


function renderAdminInlineEditField(cartId, field, value) {
    const canManage = Boolean(window.MEDIA_CATALOG_CAN_MANAGE_OWNERSHIP);

    if (!canManage) {
        return `<span>${escapeHtml(value || "—")}</span>`;
    }

    return renderInlineEditField(cartId, field, value);
}


function activateAdminInlineEdit(wrapper, carts) {
    const input = wrapper.querySelector(".inline-cart-field");
    if (!input) return;

    wrapper.classList.add("is-editing");
    input.classList.remove("hidden");
    input.classList.add("inline-edit-active");

    input.focus();
    input.select();

    const finish = async () => {
        await saveAdminInlineEdit(input, wrapper, carts);
    };

    input.addEventListener("keydown", async event => {
        if (event.key === "Enter") {
            event.preventDefault();
            await finish();
        }

        if (event.key === "Escape") {
            event.preventDefault();
            cancelInlineEdit(wrapper);
        }
    }, { once: false });

    input.addEventListener("blur", finish, { once: true });
}


async function saveAdminInlineEdit(input, wrapper, carts) {
    if (!input || input.dataset.saving === "1") return;

    const row = input.closest("tr");
    const cartId = input.dataset.cartId;
    const cart = carts.find(c => String(c.id) === String(cartId));

    if (!row || !cart) {
        cancelInlineEdit(wrapper);
        return;
    }

    input.dataset.saving = "1";

    const body = {
        teacher_name: row.querySelector('[data-field="teacher_name"]')?.value || "",
        room_number: row.querySelector('[data-field="room_number"]')?.value || "",
    };

    try {
        const data = await apiPost(
            `/api/admin/carts/${cart.id}/metadata`,
            body,
            "Unable to update cart fields."
        );

        const updatedCart = data.cart || null;

        if (updatedCart && ownershipSelectedUser) {
            await loadOwnershipUserCarts(ownershipSelectedUser);
        }

        setStatus("Cart fields updated.", true);
    } catch (err) {
        setStatus(err.message || "Unable to update cart fields.", false);

        if (ownershipSelectedUser) {
            await loadOwnershipUserCarts(ownershipSelectedUser);
        }
    } finally {
        delete input.dataset.saving;
        cancelInlineEdit(wrapper);
    }
}

function drawMyCartsRows(rows) {
    const tbody = $("myCartsBody");
    if (!tbody) return;

    tbody.innerHTML = rows.map((cart, index) => {
        const ownership = cart.ownership || {};
        const displayOrder = ownership.display_order || ((myCartsPage - 1) * myCartsPageSize) + index + 1;

        return `
            <tr class="my-cart-row" draggable="true" data-cart-id="${escapeHtml(cart.id)}">
                <td class="drag-handle" title="Drag to reorder">☰</td>
                <td>
                    <input class="cart-index-input" type="number" min="1" value="${escapeHtml(displayOrder)}" data-cart-id="${escapeHtml(cart.id)}">
                </td>
                <td>
                    <button class="link-button" type="button" data-open-cart-id="${escapeHtml(cart.id)}">
                        ${escapeHtml(cartDisplayName(cart))}
                    </button>
                    <div class="muted">${escapeHtml(cart.model_name || "")}</div>
                </td>
                <td>
                    ${renderInlineEditField(cart.id, "teacher_name", ownership.teacher_name || "—")}
                </td>
                <td>
                    ${renderInlineEditField(cart.id, "room_number", ownership.room_number || "—")}
                </td>
                <td>
                    ${renderLocationEditField(cart)}
                </td>
                <td>
                    <span
                        class="device-count-badge"
                        data-device-count-cart-id="${escapeHtml(cart.id)}"
                    >
                        ...
                    </span>
                </td>
                <td><button class="mini-btn" type="button" data-cart-details-id="${escapeHtml(cart.id)}">Details</button></td>
            </tr>
        `;
    }).join("");

    bindMyCartTableEvents(rows);
    bindLocationEditButtons(rows);
    loadVisibleCartDeviceCounts(rows);
}

async function loadVisibleCartDeviceCounts(carts) {
    await Promise.allSettled(carts.map(async cart => {
        const cell = document.querySelector(`[data-device-count-cart-id="${CSS.escape(String(cart.id))}"]`);
        if (!cell) return;

        try {
            const data = await apiGet(`/api/carts/${cart.id}/devices`, "Unable to load device count.");
            cell.textContent = String((data.devices || []).length);
        } catch {
            cell.textContent = "—";
        }
    }));
}

function getFilteredMyCarts() {
    if (!myCartsSearchQuery) return myCartsCache;

    return myCartsCache.filter(cart => {
        const ownership = cart.ownership || {};
        const haystack = [
            cart.asset_tag,
            cart.name,
            cart.model_name,
            cart.location_name,
            ownership.owner_display_name,
            ownership.owner_email,
            ownership.teacher_name,
            ownership.room_number,
        ].join(" ").toLowerCase();

        return haystack.includes(myCartsSearchQuery);
    });
}

function drawCurrentMyCartsPage() {
    const filtered = getFilteredMyCarts();
    const empty = $("myCartsEmptyState");
    const tbody = $("myCartsBody");

    if (!tbody) return;

    if (!filtered.length) {
        tbody.innerHTML = "";
        if (empty) empty.classList.remove("hidden");
        updateMyCartsPagination(0);
        return;
    }

    if (empty) empty.classList.add("hidden");

    const totalPages = Math.max(1, Math.ceil(filtered.length / myCartsPageSize));
    myCartsPage = Math.min(myCartsPage, totalPages);

    const start = (myCartsPage - 1) * myCartsPageSize;
    const rows = filtered.slice(start, start + myCartsPageSize);

    drawMyCartsRows(rows);
    updateMyCartsPagination(filtered.length);
}

function updateMyCartsPagination(totalRows) {
    const totalPages = Math.max(1, Math.ceil(totalRows / myCartsPageSize));

    if ($("myCartsPageLabel")) {
        $("myCartsPageLabel").textContent = `Page ${myCartsPage} of ${totalPages}`;
    }

    if ($("myCartsPrevPage")) {
        $("myCartsPrevPage").disabled = myCartsPage <= 1;
    }

    if ($("myCartsNextPage")) {
        $("myCartsNextPage").disabled = myCartsPage >= totalPages || totalRows === 0;
    }
}

function renderSelectedCartMeta(cart) {
    const ownership = cart.ownership || {};

    const items = [
        ["Cart", cart.asset_tag || cart.name || "—"],
        ["Location", cart.location_name || "—"],
        ["Owner", ownership.owner_display_name || ownership.owner_email || "Unassigned"],
        ["Teacher", ownership.teacher_name || "—"],
        ["Room", ownership.room_number || "—"],
    ];

    return `
        <div class="selected-cart-meta">
            ${items.map(([label, value]) => `
                <span class="selected-cart-chip">
                    <strong>${escapeHtml(label)}</strong>
                    ${escapeHtml(value)}
                </span>
            `).join("")}
        </div>
    `;
}

function renderInlineEditField(cartId, field, value) {
    return `
        <div class="inline-edit-control" data-field-wrap="${escapeHtml(field)}" data-cart-id="${escapeHtml(cartId)}">
            <span class="inline-edit-value">${escapeHtml(value || "—")}</span>
            <input
                class="inline-cart-field hidden"
                data-field="${escapeHtml(field)}"
                data-cart-id="${escapeHtml(cartId)}"
                value="${escapeHtml(value === "—" ? "" : value)}"
            >
            <button class="inline-edit-btn" type="button" title="Edit">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M12 20h9"/>
                    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>
                </svg>
            </button>
        </div>
    `;
}

function activateInlineEdit(wrapper, carts) {
    const input = wrapper.querySelector(".inline-cart-field");
    if (!input) return;

    wrapper.classList.add("is-editing");
    input.classList.remove("hidden");
    input.classList.add("inline-edit-active");

    input.focus();
    input.select();

    const finish = async () => {
        await saveInlineEdit(input, wrapper, carts);
    };

    input.addEventListener("keydown", async event => {
        if (event.key === "Enter") {
            event.preventDefault();
            await finish();
        }

        if (event.key === "Escape") {
            event.preventDefault();
            cancelInlineEdit(wrapper);
        }
    }, { once: false });

    input.addEventListener("blur", finish, { once: true });
}

function cancelInlineEdit(wrapper) {
    const input = wrapper.querySelector(".inline-cart-field");
    wrapper.classList.remove("is-editing");

    if (input) {
        input.classList.add("hidden");
        input.classList.remove("inline-edit-active");
    }
}

async function saveInlineEdit(input, wrapper, carts) {
    if (!input || input.dataset.saving === "1") return;

    const row = input.closest("tr");
    const cartId = input.dataset.cartId;
    const cart = carts.find(c => String(c.id) === String(cartId));

    if (!row || !cart) {
        cancelInlineEdit(wrapper);
        return;
    }

    input.dataset.saving = "1";

    const body = {
        teacher_name: row.querySelector('[data-field="teacher_name"]')?.value || "",
        room_number: row.querySelector('[data-field="room_number"]')?.value || "",
    };

    try {
        const data = await apiPost(
            `/api/carts/${cart.id}/metadata`,
            body,
            "Unable to update cart fields."
        );

        const updatedCart = data.cart || null;

        if (updatedCart) {
            myCartsCache = myCartsCache.map(item =>
                String(item.id) === String(updatedCart.id) ? updatedCart : item
            );
        }

        const valueEl = wrapper.querySelector(".inline-edit-value");
        if (valueEl) {
            valueEl.textContent = input.value.trim() || "—";
        }

        setStatus("Cart fields updated.", true);
    } catch (err) {
        setStatus(err.message || "Unable to update cart fields.", false);
        await loadMyCarts();
    } finally {
        delete input.dataset.saving;
        cancelInlineEdit(wrapper);
    }
}

function renderLocationEditField(cart) {
    return `
        <div class="inline-edit-control location-edit-control" data-cart-id="${escapeHtml(cart.id)}">
            <span class="inline-edit-value">${escapeHtml(cart.location_name || "—")}</span>
            <button class="inline-edit-btn location-edit-btn"
                    type="button"
                    data-location-cart-id="${escapeHtml(cart.id)}"
                    title="Update Location">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
                     stroke="currentColor" stroke-width="2.2"
                     stroke-linecap="round" stroke-linejoin="round"
                     aria-hidden="true">
                    <path d="M12 20h9"/>
                    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>
                </svg>
            </button>
        </div>
    `;
}

function bindLocationEditButtons(carts, selector = "[data-location-cart-id]") {
    document.querySelectorAll(selector).forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const cart = carts.find(item => String(item.id) === String(btn.dataset.locationCartId));
            if (!cart) return;

            openLocationPicker(cart);
        });
    });
}

async function getLocationOptions() {
    if (locationOptionsCache) {
        return locationOptionsCache;
    }

    const data = await apiGet("/api/locations", "Unable to load Snipe-IT locations.");
    locationOptionsCache = data.locations || [];
    return locationOptionsCache;
}

async function openLocationPicker(cart) {
    setStatus("Loading locations...", true);

    try {
        const locations = await getLocationOptions();

        if (!locations.length) {
            setStatus("No Snipe-IT locations found.", false);
            return;
        }

        const options = locations.map(location => `
            <option value="${escapeHtml(location.id)}">
                ${escapeHtml(location.name)}
            </option>
        `).join("");

        openConfirmModal({
            title: "Update Cart Location",
            messageHtml: `
                <p class="confirm-copy">
                    Update location for <strong>${escapeHtml(cart.asset_tag || cart.name || "this cart")}</strong>.
                </p>

                <div class="form-card">
                    <label class="media-label" for="cartLocationSelect">Location</label>
                    <select id="cartLocationSelect" class="media-input">
                        <option value="">Select location...</option>
                        ${options}
                    </select>
                </div>

                <p class="muted">
                    This updates the cart asset location in Snipe-IT.
                </p>
            `,
            buttonText: "Update Location",
            action: async () => {
                const locationId = $("cartLocationSelect")?.value || "";
                await updateCartLocation(cart, locationId);
            }
        });

        setStatus("Locations loaded.", true);
    } catch (err) {
        setStatus(err.message || "Unable to load locations.", false);
    }
}


async function updateCartLocation(cart, locationId) {
    if (!locationId) {
        setStatus("Select a location first.", false);
        return;
    }

    setStatus("Updating cart location...", true);

    try {
        const data = await apiPost(
            `/api/carts/${cart.id}/location`,
            { location_id: locationId },
            "Unable to update cart location."
        );

        setStatus(data.message || "Cart location updated.", true);

        await loadMyCarts();

        if (ownershipSelectedUser) {
            await loadOwnershipUserCarts(ownershipSelectedUser);
        }

        if (data.cart) {
            selectedCart = data.cart;
        }

        if (
            selectedCart &&
            String(selectedCart.id) === String(cart.id)
        ) {
            await selectCart(selectedCart);
        }
    } catch (err) {
        setStatus(err.message || "Unable to update cart location.", false);
    }
}

async function preloadLocationOptions() {
    try {
        await getLocationOptions();
    } catch {
        // Do not block Media Catalog load if Snipe-IT locations fail.
    }
}

function formatFriendlyDateTime(value) {
    if (!value) return "—";

    const parsed = new Date(value);

    if (Number.isNaN(parsed.getTime())) {
        return value;
    }

    const options = {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
    };

    if (window.MEDIA_CATALOG_TIMEZONE) {
        options.timeZone = window.MEDIA_CATALOG_TIMEZONE;
        options.timeZoneName = "short";
    }

    try {
        return parsed.toLocaleString(undefined, options);
    } catch {
        return parsed.toLocaleString(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric",
            hour: "numeric",
            minute: "2-digit",
        });
    }
}