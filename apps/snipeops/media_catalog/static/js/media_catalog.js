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
let dashboardCache = null;
let studentCheckoutLookup = null;
let studentCheckoutsCache = [];
let studentCheckoutStatusFilter = "active";
let studentCheckoutSearchQuery = "";
let pendingReturnCheckout = null;

const sheetDevices = new Map();
const cartMetadataSaveQueues = new Map();

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

    if (el) {
        el.textContent = Number.isFinite(Number(count))
            ? String(count)
            : "—";
    }

    updateRemoveAllDevicesButton(
        Number.isFinite(Number(count))
            ? Number(count)
            : sheetDevices.size
    );
}

function updateRemoveAllDevicesButton(count = sheetDevices.size) {
    const button = $("removeAllDevicesBtn");
    if (!button) return;

    const deviceCount = Number(count) || 0;

    button.disabled = !selectedCart || deviceCount < 1;
    button.textContent = deviceCount > 0
        ? `Remove All Devices (${deviceCount})`
        : "Remove All Devices";
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
        const err = new Error(data.error || data.message || fallbackMessage);
        Object.assign(err, data);
        throw err;
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
    bindDashboard();
    bindCartSearch();
    bindFindCartToggle();
    bindRefreshMyCarts();
    bindDeviceAdd();
    bindRemoveAllDevices();
    bindSyncButton();
    bindConfirmModal();
    bindDeviceDetailModal();
    bindMoveDeviceModal();
    bindAssignOwnerModal();
    bindMediaTabs();
    bindOwnershipManagement();
    bindExportButtons();
    bindRecentActivityFilter();
    bindStudentCheckoutModal();
    bindStudentCheckoutsPage();
    bindReturnStudentCheckoutModal();
    hydrateActivityTimes();
    initManagedDeviceTotals();

    renderSheetEmpty("Select a cart to load assigned devices.");
    setDeviceCount("—");
    hideSelectedCartPanel(false);

    try {
        await loadCurrentUser();
        await loadDashboard();
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

function bindDashboard() {
    $("refreshDashboardBtn")?.addEventListener("click", loadDashboard);

    document.querySelectorAll("[data-open-checkout-status]").forEach(btn => {
        btn.addEventListener("click", () => {
            openStudentCheckoutsTab(btn.dataset.openCheckoutStatus || "active");
        });
    });

    document.querySelectorAll("[data-dashboard-view-all-carts]").forEach(btn => {
        btn.addEventListener("click", openCartManagementTab);
    });
}

async function loadDashboard() {
    const summaryEl = $("dashboardSummary");
    const cartsEl = $("dashboardMyCarts");
    const attentionEl = $("dashboardAttention");
    const activityEl = $("dashboardRecentCheckouts");

    if (!summaryEl && !cartsEl && !attentionEl && !activityEl) return;

    if (summaryEl) {
        summaryEl.innerHTML = `<div class="muted">Loading dashboard...</div>`;
    }

    try {
        const data = await apiGet("/api/dashboard", "Unable to load Media Catalog dashboard.");
        dashboardCache = data;
        renderDashboard(data);
    } catch (err) {
        if (summaryEl) {
            summaryEl.innerHTML = `<div class="muted">${escapeHtml(err.message || "Unable to load dashboard.")}</div>`;
        }
        if (attentionEl) attentionEl.innerHTML = "";
        if (cartsEl) cartsEl.innerHTML = "";
        if (activityEl) activityEl.innerHTML = "";
    }
}

function openCartManagementTab() {
    document.querySelector('[data-tab="cart-management"]')?.click();
}

function dashboardMetricIcon(name) {
    const icons = {
        carts: `
            <rect x="3" y="5" width="18" height="12" rx="2"></rect>
            <path d="M7 17v2"></path>
            <path d="M17 17v2"></path>
            <path d="M7 9h10"></path>
        `,
        devices: `
            <rect x="5" y="3" width="14" height="18" rx="2"></rect>
            <path d="M9 7h6"></path>
            <path d="M12 17h.01"></path>
        `,
        active: `
            <path d="M9 11l3 3L22 4"></path>
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
        `,
        overdue: `
            <circle cx="12" cy="12" r="9"></circle>
            <path d="M12 7v5l3 2"></path>
        `,
    };

    return `
        <span class="dashboard-metric-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">
                ${icons[name] || icons.carts}
            </svg>
        </span>
    `;
}

function renderDashboard(data) {
    const summary = data.summary || {};
    const summaryEl = $("dashboardSummary");
    const cartsEl = $("dashboardMyCarts");
    const attentionEl = $("dashboardAttention");
    const activityEl = $("dashboardRecentCheckouts");

    if (summaryEl) {
        const activeCheckoutCard = window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS
            ? `
                <button class="dashboard-metric-card" type="button" data-dashboard-checkout-status="active">
                    ${dashboardMetricIcon("active")}
                    <span class="dashboard-metric-value">${escapeHtml(summary.active_checkout_count || 0)}</span>
                    <strong>Active Checkouts</strong>
                    <small>Devices currently with students</small>
                </button>
            `
            : `
                <div class="dashboard-metric-card">
                    ${dashboardMetricIcon("active")}
                    <span class="dashboard-metric-value">${escapeHtml(summary.active_checkout_count || 0)}</span>
                    <strong>Active Checkouts</strong>
                    <small>Devices currently with students</small>
                </div>
            `;

        const overdueCheckoutCard = window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS
            ? `
                <button class="dashboard-metric-card overdue" type="button" data-dashboard-checkout-status="overdue">
                    ${dashboardMetricIcon("overdue")}
                    <span class="dashboard-metric-value">${escapeHtml(summary.overdue_checkout_count || 0)}</span>
                    <strong>Overdue</strong>
                    <small>Past the Return By date</small>
                </button>
            `
            : `
                <div class="dashboard-metric-card overdue">
                    ${dashboardMetricIcon("overdue")}
                    <span class="dashboard-metric-value">${escapeHtml(summary.overdue_checkout_count || 0)}</span>
                    <strong>Overdue</strong>
                    <small>Past the Return By date</small>
                </div>
            `;

        summaryEl.innerHTML = `
            <button class="dashboard-metric-card" type="button" data-dashboard-target="cart-management">
                ${dashboardMetricIcon("carts")}
                <span class="dashboard-metric-value">${escapeHtml(summary.cart_count || 0)}</span>
                <strong>My Carts</strong>
                <small>Assigned or managed in your scope</small>
            </button>

            <button class="dashboard-metric-card" type="button" data-dashboard-target="cart-management">
                ${dashboardMetricIcon("devices")}
                <span class="dashboard-metric-value">${escapeHtml(summary.device_count || 0)}</span>
                <strong>Devices</strong>
                <small>Total devices in scoped carts</small>
            </button>

            ${activeCheckoutCard}
            ${overdueCheckoutCard}
        `;

        summaryEl.querySelectorAll("[data-dashboard-target]").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelector(`[data-tab="${btn.dataset.dashboardTarget}"]`)?.click();
            });
        });

        summaryEl.querySelectorAll("[data-dashboard-checkout-status]").forEach(btn => {
            btn.addEventListener("click", () => {
                openStudentCheckoutsTab(btn.dataset.dashboardCheckoutStatus || "active");
            });
        });
    }

    if (cartsEl) {
        renderDashboardCarts(data.carts || []);
    }

    if (attentionEl) {
        renderDashboardAttention(data);
    }

    if (activityEl) {
        renderDashboardRecentCheckouts(data.recent_student_checkouts || []);
    }
}

function renderDashboardAttention(data) {
    const el = $("dashboardAttention");
    if (!el) return;

    const summary = data.summary || {};
    const attention = data.attention || {};
    const overdueCount = Number(summary.overdue_checkout_count || 0);
    const overdueCarts = attention.overdue_carts || [];
    const items = [];

    if (overdueCount > 0) {
        items.push(`
            <button class="dashboard-attention-item priority" type="button" data-attention-checkout-status="overdue">
                <span>${escapeHtml(overdueCount)}</span>
                <div>
                    <strong>Overdue Student Checkouts</strong>
                    <p>${escapeHtml(overdueCount)} device${overdueCount === 1 ? "" : "s"} past the Return By date</p>
                </div>
            </button>
        `);
    }

    overdueCarts.slice(0, 5).forEach(cart => {
        const checkoutSummary = cart.student_checkout_summary || {};
        const ownership = cart.ownership || {};
        const overdue = Number(checkoutSummary.overdue_count || 0);
        const teacher = ownership.teacher_name || ownership.owner_display_name || ownership.owner_email || "Unassigned";
        const room = ownership.room_number ? `Room ${ownership.room_number}` : "No room";

        if (!overdue) return;

        items.push(`
            <button class="dashboard-attention-item" type="button" data-attention-open-cart="${escapeHtml(cart.id)}">
                <span>${escapeHtml(overdue)}</span>
                <div>
                    <strong>${escapeHtml(cart.asset_tag ? `Cart ${cart.asset_tag}` : cart.name || "Cart")}</strong>
                    <p>${escapeHtml(teacher)} - ${escapeHtml(room)}</p>
                </div>
            </button>
        `);
    });

    if (!items.length) {
        el.innerHTML = `
            <div class="dashboard-empty-state">
                <strong>No checkout items need attention</strong>
                <p class="muted">Overdue Student Checkouts will surface here when they occur.</p>
            </div>
        `;
        return;
    }

    el.innerHTML = items.join("");

    el.querySelectorAll("[data-attention-checkout-status]").forEach(btn => {
        btn.addEventListener("click", () => {
            openStudentCheckoutsTab(btn.dataset.attentionCheckoutStatus || "overdue");
        });
    });

    el.querySelectorAll("[data-attention-open-cart]").forEach(btn => {
        btn.addEventListener("click", () => {
            const carts = data.carts || [];
            const cart = carts.find(item => String(item.id) === String(btn.dataset.attentionOpenCart));
            openCartManagementTab();
            if (cart) selectCart(cart);
        });
    });
}

function renderDashboardCarts(carts) {
    const el = $("dashboardMyCarts");
    if (!el) return;

    if (!carts.length) {
        el.innerHTML = `
            <div class="dashboard-empty-state">
                <strong>No carts in your current scope</strong>
                <p class="muted">Claim or assign a cart from Cart Management to build this overview.</p>
            </div>
        `;
        return;
    }

    const visibleCarts = carts.slice(0, 8);

    el.innerHTML = `
        <div class="dashboard-cart-table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Cart</th>
                        <th>Teacher / Owner</th>
                        <th>Room</th>
                        <th>Devices</th>
                        <th>Active</th>
                        <th>Overdue</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    ${visibleCarts.map(cart => {
        const ownership = cart.ownership || {};
        const summary = cart.student_checkout_summary || {};
        const teacher = ownership.teacher_name || ownership.owner_display_name || ownership.owner_email || "Unassigned";
        const room = ownership.room_number || "-";
        const overdue = Number(summary.overdue_count || 0);
        const active = Number(summary.active_count || 0);

        return `
            <tr data-dashboard-cart-id="${escapeHtml(cart.id)}">
                <td>
                    <button class="link-button" type="button" data-dashboard-open-cart="${escapeHtml(cart.id)}">
                        ${escapeHtml(cart.asset_tag ? `Cart ${cart.asset_tag}` : cart.name || "Cart")}
                    </button>
                    <div class="muted">${escapeHtml(cart.name || cart.model_name || "")}</div>
                </td>
                <td>${escapeHtml(teacher)}</td>
                <td>${escapeHtml(room)}</td>
                <td>${escapeHtml(cart.device_count || 0)}</td>
                <td>${escapeHtml(active)}</td>
                <td class="${overdue ? "checkout-overdue-text" : "muted"}">${escapeHtml(overdue)}</td>
                <td>
                    ${window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS ? `
                        <button class="mini-btn" type="button" data-dashboard-open-checkouts="${escapeHtml(cart.asset_tag || cart.name || "")}">
                            Checkouts
                        </button>
                    ` : `
                        <button class="mini-btn" type="button" data-dashboard-open-cart="${escapeHtml(cart.id)}">
                            Open
                        </button>
                    `}
                </td>
            </tr>
        `;
                    }).join("")}
                </tbody>
            </table>
        </div>

        <div class="dashboard-table-footer">
            <span class="muted">Showing ${escapeHtml(visibleCarts.length)} of ${escapeHtml(carts.length)} cart${carts.length === 1 ? "" : "s"}.</span>
        </div>
    `;

    el.querySelectorAll("[data-dashboard-open-cart]").forEach(btn => {
        btn.addEventListener("click", () => {
            const cart = carts.find(item => String(item.id) === String(btn.dataset.dashboardOpenCart));
            if (!cart) return;
            openCartManagementTab();
            selectCart(cart);
        });
    });

    el.querySelectorAll("[data-dashboard-open-checkouts]").forEach(btn => {
        btn.addEventListener("click", () => {
            openStudentCheckoutsTab("all", btn.dataset.dashboardOpenCheckouts || "");
        });
    });
}

function renderDashboardRecentCheckouts(checkouts) {
    const el = $("dashboardRecentCheckouts");
    if (!el) return;

    if (!checkouts.length) {
        el.innerHTML = `
            <div class="dashboard-empty-state">
                <strong>No recent Student Checkout activity</strong>
                <p class="muted">Checkout and return records will appear here once devices move through student custody.</p>
            </div>
        `;
        return;
    }

    el.innerHTML = checkouts.slice(0, 8).map(checkout => {
        const returned = Boolean(checkout.returned_at);
        const action = returned ? "Returned" : "Checked out";
        const when = returned ? checkout.returned_at : checkout.checked_out_at;

        return `
        <article class="dashboard-activity-item">
            <div>
                <strong>${escapeHtml(action)} ${escapeHtml(checkout.device_asset_tag || checkout.device_serial || "Device")}</strong>
                <p>
                    ${escapeHtml(checkout.student_name || "Student")}
                    - ${escapeHtml(checkout.original_cart_asset_tag || checkout.original_cart_name || "Cart")}
                </p>
                <span class="muted">${escapeHtml(formatActivityDateTime(when))}</span>
            </div>
            ${renderCheckoutStatusBadge(checkout)}
        </article>
        `;
    }).join("");
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

    setManagedDeviceSummaryValue(
        "myManagedDeviceTotal",
        "..."
    );

    try {
        const data = await apiGet(
            "/api/my-carts",
            "Unable to load your carts."
        );

        myCartsCache = data.carts || [];

        renderMyCartsTable(myCartsCache);

        setManagedDeviceSummaryValue(
            "myManagedDeviceTotal",
            Number(data.total_devices_managed || 0)
        );

        if (selectedCart) {
            collapseMyCartsTable();
        }
    } catch (err) {
        el.innerHTML = `
            <div class="muted">
                ${escapeHtml(err.message || "Unable to load your carts.")}
            </div>
        `;

        setManagedDeviceSummaryValue(
            "myManagedDeviceTotal",
            "Error"
        );
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

function bindOwnershipCartSearch() {
    const input = $("ownershipCartSearch");
    const btn = $("ownershipCartSearchBtn");

    if (!input || !btn) return;

    const run = debounce(searchOwnershipCarts, 250);

    input.addEventListener("input", run);

    input.addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            searchOwnershipCarts();
        }
    });

    btn.addEventListener("click", searchOwnershipCarts);
}


async function searchOwnershipCarts() {
    const input = $("ownershipCartSearch");
    const resultsEl = $("ownershipCartResults");
    const query = (input?.value || "").trim();

    if (!resultsEl) return;

    if (query.length < 2) {
        resultsEl.innerHTML = "";
        return;
    }

    resultsEl.innerHTML = `<div class="muted">Searching carts...</div>`;
    setStatus(`Searching carts for "${query}"...`, true);

    try {
        const data = await apiGet(
            `/api/carts?q=${encodeURIComponent(query)}`,
            "Cart search failed."
        );

        renderCartCards(
            "ownershipCartResults",
            data.carts || [],
            { showOwnershipButton: true }
        );

        setStatus(`Found ${(data.carts || []).length} cart(s).`, true);
    } catch (err) {
        resultsEl.innerHTML =
            `<div class="muted">${escapeHtml(err.message || "Cart search failed.")}</div>`;
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

                    <button
                        id="myCartsPrevPage"
                        class="mini-btn"
                        type="button"
                    >
                        Prev
                    </button>

                    <span id="myCartsPageLabel" class="muted">
                        Page 1 of 1
                    </span>

                    <button
                        id="myCartsNextPage"
                        class="mini-btn"
                        type="button"
                    >
                        Next
                    </button>
                </div>
            </div>

            <div class="sheet-wrap my-carts-sheet-wrap">
                <table class="media-sheet my-carts-table">
                    <thead>
                        <tr>
                            <th>Move</th>
                            <th>Cart</th>
                            <th>Teacher Name</th>
                            <th>Room Number</th>
                            <th>Location</th>
                            <th>Devices</th>
                            <th>Student Checkouts</th>
                            <th>Actions</th>
                        </tr>
                    </thead>

                    <tbody id="myCartsBody"></tbody>
                </table>
            </div>

            <div
                id="myCartsEmptyState"
                class="media-empty-state hidden"
            >
                No carts match your search.
            </div>
        </div>

        <div
            id="myCartsCollapsedView"
            class="active-cart-summary hidden"
        >
            <div>
                <p class="media-eyebrow">Active Cart</p>

                <strong id="activeCartSummaryTitle">
                    No cart selected
                </strong>

                <p
                    id="activeCartSummarySubtitle"
                    class="muted"
                >
                    The cart list is collapsed while you are adding devices.
                </p>
            </div>

            <div class="media-section-actions">
                <button
                    id="expandMyCartsBtn"
                    class="media-btn primary-action"
                    type="button"
                >
                    Expand My Carts
                </button>

                <button
                    id="deselectCartBtn"
                    class="media-btn danger"
                    type="button"
                >
                    Deselect Cart
                </button>
            </div>
        </div>
    `;

    $("myCartsFilter")?.addEventListener("input", event => {
        myCartsSearchQuery =
            event.target.value.toLowerCase().trim();

        myCartsPage = 1;
        drawCurrentMyCartsPage();
    });

    $("myCartsPageSize")?.addEventListener("change", event => {
        myCartsPageSize =
            Number.parseInt(event.target.value, 10) || 25;

        myCartsPage = 1;
        drawCurrentMyCartsPage();
    });

    $("myCartsPrevPage")?.addEventListener("click", () => {
        myCartsPage = Math.max(
            1,
            myCartsPage - 1
        );

        drawCurrentMyCartsPage();
    });

    $("myCartsNextPage")?.addEventListener("click", () => {
        const filtered = getFilteredMyCarts();

        const totalPages = Math.max(
            1,
            Math.ceil(
                filtered.length / myCartsPageSize
            )
        );

        myCartsPage = Math.min(
            totalPages,
            myCartsPage + 1
        );

        drawCurrentMyCartsPage();
    });

    $("expandMyCartsBtn")?.addEventListener(
        "click",
        expandMyCartsTable
    );

    $("deselectCartBtn")?.addEventListener(
        "click",
        () => hideSelectedCartPanel(true)
    );

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

    document.querySelectorAll(
        "#myCartsBody [data-unassign-cart-id]"
    ).forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const cart = carts.find(
                item =>
                    String(item.id) ===
                    String(btn.dataset.unassignCartId)
            );

            if (cart) {
                requestUnassignCart(cart, {
                    source: "cart-management"
                });
            }
        });
    });

    document.querySelectorAll("#myCartsBody [data-cart-checkouts-id]").forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const cart = carts.find(item => String(item.id) === String(btn.dataset.cartCheckoutsId));
            if (cart) openCartCheckoutDetails(cart);
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
        setStatus("", true);
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

function requestUnassignCart(cart, options = {}) {
    if (!cart) return;

    const ownership = cart.ownership || {};
    const ownerName =
        ownership.owner_display_name ||
        ownership.owner_email ||
        options.owner?.owner_display_name ||
        options.owner?.owner_email ||
        "the current owner";

    const cartLabel = cartDisplayName(cart);

    openConfirmModal({
        title: "Unassign Cart?",
        messageHtml: `
            <p class="confirm-copy">
                Remove this cart from the Media Catalog owner?
            </p>

            <div class="ownership-detail-card">
                <div class="ownership-detail-heading">
                    Unassign Cart
                </div>

                <div class="ownership-detail-row">
                    <div class="ownership-detail-label">Cart</div>
                    <div class="ownership-detail-value">
                        ${escapeHtml(cartLabel)}
                    </div>
                </div>

                <div class="ownership-detail-row">
                    <div class="ownership-detail-label">
                        Current Owner
                    </div>
                    <div class="ownership-detail-value">
                        ${escapeHtml(ownerName)}
                    </div>
                </div>
            </div>

            <p class="confirm-copy confirm-warning">
                This removes the cart from the owner's Media Catalog.
                Devices currently inside the cart will remain assigned
                to the cart in Snipe-IT.
            </p>
        `,
        buttonText: "Unassign Cart",
        action: async () => unassignCart(cart, options)
    });
}


async function unassignCart(cart, options = {}) {
    if (!cart) return;

    setStatus("Unassigning cart...", true);

    try {
        const data = await apiPost(
            `/api/carts/${cart.id}/unassign`,
            {},
            "Unable to unassign cart."
        );

        const wasSelected =
            selectedCart &&
            String(selectedCart.id) === String(cart.id);

        prependRecent(
            "unassigned_cart",
            null,
            data.cart || cart,
            true,
            data.message || "Cart unassigned."
        );

        if (wasSelected) {
            hideSelectedCartPanel(false);
        }

        await refreshMediaCatalogViews();

        if (
            options.source === "ownership-management" &&
            ownershipSelectedUser
        ) {
            const selectedOwnerId =
                ownershipSelectedUser.owner_user_id;

            await loadOwnershipOwners();

                const stillExists = ownershipOwnersCache.find(
                    owner =>
                        String(owner.owner_user_id) ===
                        String(selectedOwnerId)
                );

            if (stillExists) {
                ownershipSelectedUser = stillExists;
                await loadOwnershipUserCarts(stillExists);
            } else {
                ownershipSelectedUser = null;

                const ownerCarts = $("ownershipUserCarts");
                if (ownerCarts) {
                    ownerCarts.innerHTML = `
                        <div class="muted">
                            The selected user no longer has any
                            assigned carts.
                        </div>
                    `;
                }
            }
        }

        setStatus(
            data.message || "Cart unassigned.",
            true
        );

    } catch (err) {
        setStatus(
            err.message || "Unable to unassign cart.",
            false
        );
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

async function requestAddDevice(device) {
    if (!selectedCart) {
        setStatus("Select a cart first.", false);
        return;
    }

    if (String(device.id) === String(selectedCart.id)) {
        setStatus("You cannot add a cart to itself.", false);
        return;
    }

    /*
     * The server handles existing assignments as a move:
     * check in from the original cart, then check out to the selected cart.
     */
    await addDeviceToCart(device);
}


function getActiveMediaCatalogTab() {
    return document.querySelector(".media-catalog-tabs .settings-tab.active")?.dataset.tab || "";
}

function setStudentCheckoutListState(status = "active", query = "") {
    studentCheckoutStatusFilter = status || "active";
    studentCheckoutSearchQuery = query || "";

    const search = $("studentCheckoutSearch");
    if (search) {
        search.value = studentCheckoutSearchQuery;
    }

    updateStudentCheckoutFilterButtons();
}

async function refreshMediaCatalogViews() {
    const refreshTasks = [
        loadDashboard(),
        loadMyCarts()
    ];

    if ($("ownershipOwners")) {
        refreshTasks.push(loadOwnershipOwners());
    }

    if ($("ownershipUserCarts") && ownershipSelectedUser) {
        refreshTasks.push(loadOwnershipUserCarts(ownershipSelectedUser));
    }

    if ($("studentCheckoutsBody") && window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS) {
        refreshTasks.push(loadStudentCheckouts());
    }

    await Promise.allSettled(refreshTasks);
}

async function refreshStudentCheckoutDependentViews(options = {}) {
    const activeTab = getActiveMediaCatalogTab();

    if (
        options.afterCreate &&
        activeTab === "student-checkouts"
    ) {
        setStudentCheckoutListState("active", "");
    }

    await refreshMediaCatalogViews();
}


async function addDeviceToCart(device) {
    if (!selectedCart) {
        setStatus("Select a cart first.", false);
        return;
    }

    const destinationCart = selectedCart;

    setStatus("Assigning device to cart...", true);

    try {
        const data = await apiPost(
            "/api/add-to-cart",
            {
                cart_id: destinationCart.id,
                device_id: device.id
            },
            "Unable to add device to cart."
        );

        const deviceInput = $("deviceInput");

        if (deviceInput) {
            deviceInput.value = "";
            deviceInput.focus();
        }

        await refreshMediaCatalogViews();

        selectedCart = data.cart || destinationCart;
        await selectCart(selectedCart);

        prependRecent(
            data.moved ? "moved_to_cart" : "add_to_cart",
            data.device || device,
            selectedCart,
            true,
            data.message || "Device assigned to cart."
        );

        setStatus(
            data.message || "Device assigned to cart.",
            true
        );
    } catch (err) {
        /*
         * Reload the active view even after failure. A check-in may have
         * succeeded before a destination checkout failed.
         */
        await refreshMediaCatalogViews();

        if (selectedCart) {
            await selectCart(selectedCart);
        }

        prependRecent(
            "add_failed",
            device,
            destinationCart,
            false,
            err.message || "Unable to add device to cart."
        );

        setStatus(
            err.message || "Unable to add device to cart.",
            false
        );
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
    if (!device) return;

    const removedFromCart = selectedCart;

    setStatus("Removing device from cart...", true);

    try {
        const data = await apiPost(
            "/api/remove-from-cart",
            {
                device_id: device.id
            },
            "Unable to remove device from cart."
        );

        sheetDevices.delete(String(device.id));
        renderSheet();
        setDeviceCount(sheetDevices.size);

        await refreshMediaCatalogViews();

        if (removedFromCart) {
            selectedCart = removedFromCart;
            await selectCart(removedFromCart);
        }

        prependRecent(
            "remove_from_cart",
            data.device || device,
            removedFromCart,
            true,
            data.message || "Device removed from cart."
        );

        setStatus(
            data.message ||
            `Device removed. ${sheetDevices.size} device(s) remain in this cart.`,
            true
        );
    } catch (err) {
        await refreshMediaCatalogViews();

        if (selectedCart) {
            await selectCart(selectedCart);
        }

        prependRecent(
            "remove_failed",
            device,
            removedFromCart,
            false,
            err.message || "Unable to remove device from cart."
        );

        setStatus(
            err.message || "Unable to remove device from cart.",
            false
        );
    }
}

function bindRemoveAllDevices() {
    $("removeAllDevicesBtn")?.addEventListener(
        "click",
        requestRemoveAllDevices
    );
}


function requestRemoveAllDevices() {
    if (!selectedCart) {
        setStatus(
            "Select a cart before removing devices.",
            false
        );
        return;
    }

    const deviceCount = sheetDevices.size;

    if (deviceCount < 1) {
        setStatus(
            "This cart does not have any assigned devices.",
            false
        );
        return;
    }

    const cartLabel = cartDisplayName(selectedCart);

    openConfirmModal({
        title: "Remove All Devices?",
        messageHtml: `
            <p class="confirm-copy">
                You are about to remove every device from this cart.
            </p>

            <div class="ownership-detail-card">
                <div class="ownership-detail-heading">
                    Destructive Action
                </div>

                <div class="ownership-detail-row">
                    <div class="ownership-detail-label">Cart</div>
                    <div class="ownership-detail-value">
                        ${escapeHtml(cartLabel)}
                    </div>
                </div>

                <div class="ownership-detail-row">
                    <div class="ownership-detail-label">
                        Devices
                    </div>
                    <div class="ownership-detail-value">
                        ${escapeHtml(deviceCount)}
                    </div>
                </div>
            </div>

            <p class="confirm-copy confirm-warning">
                Each device will be checked into Snipe-IT and removed
                from this cart. This action cannot be undone as one
                operation.
            </p>
        `,
        buttonText: "Remove All Devices",
        action: removeAllDevicesFromSelectedCart
    });
}


async function removeAllDevicesFromSelectedCart() {
    if (!selectedCart) return;

    const cart = selectedCart;
    const button = $("removeAllDevicesBtn");

    if (button) {
        button.disabled = true;
        button.textContent = "Removing Devices...";
    }

    setStatus(
        "Removing all devices from the cart...",
        true
    );

    try {
        const data = await apiPost(
            `/api/carts/${cart.id}/remove-all-devices`,
            {},
            "Unable to remove all devices."
        );

        prependRecent(
            data.complete_success
                ? "removed_all_devices"
                : data.partial_success
                    ? "remove_all_devices_partial"
                    : "remove_all_devices_failed",
            null,
            data.cart || cart,
            Boolean(data.complete_success),
            data.message || "Remove All Devices completed."
        );

        await refreshMediaCatalogViews();

        if (
            selectedCart &&
            String(selectedCart.id) === String(cart.id)
        ) {
            await selectCart(data.cart || cart);
        }

        if (Number(data.failed_count || 0) > 0) {
            const failureSummary = (data.failures || [])
                .slice(0, 5)
                .map(failure => {
                    const identifier =
                        failure.asset_tag ||
                        failure.serial ||
                        failure.device_id ||
                        "Unknown device";

                    return `
                        <div class="ownership-detail-row">
                            <div class="ownership-detail-label">
                                ${escapeHtml(identifier)}
                            </div>
                            <div class="ownership-detail-value">
                                ${escapeHtml(
                                    failure.error ||
                                    "Removal failed."
                                )}
                            </div>
                        </div>
                    `;
                })
                .join("");

            openConfirmModal({
                title: data.partial_success
                    ? "Some Devices Were Not Removed"
                    : "Devices Could Not Be Removed",
                messageHtml: `
                    <p class="confirm-copy">
                        ${escapeHtml(data.message || "")}
                    </p>

                    <div class="ownership-detail-card">
                        <div class="ownership-detail-heading">
                            Removal Results
                        </div>

                        <div class="ownership-detail-row">
                            <div class="ownership-detail-label">
                                Removed
                            </div>
                            <div class="ownership-detail-value">
                                ${escapeHtml(
                                    data.removed_count || 0
                                )}
                            </div>
                        </div>

                        <div class="ownership-detail-row">
                            <div class="ownership-detail-label">
                                Failed
                            </div>
                            <div class="ownership-detail-value">
                                ${escapeHtml(
                                    data.failed_count || 0
                                )}
                            </div>
                        </div>

                        ${failureSummary}
                    </div>
                `,
                buttonText: "Close",
                action: async () => {}
            });

            setStatus(
                data.message ||
                "Some devices could not be removed.",
                false
            );
        } else {
            setStatus(
                data.message ||
                "All devices were removed from the cart.",
                true
            );
        }

    } catch (err) {
        await refreshMediaCatalogViews();

        if (
            selectedCart &&
            String(selectedCart.id) === String(cart.id)
        ) {
            await selectCart(cart);
        }

        setStatus(
            err.message ||
            "Unable to remove all devices.",
            false
        );

    } finally {
        updateRemoveAllDevicesButton(sheetDevices.size);
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
        <td>
            <time
                class="activity-time"
                data-utc="${escapeHtml(new Date().toISOString())}"
            >
                ${escapeHtml(formatActivityDateTime(new Date().toISOString()))}
            </time>
        </td>
        <td>${escapeHtml(friendlyAction(action))}</td>
        <td>${escapeHtml(currentUser?.display_name || currentUser?.email || "—")}</td>
        <td class="mono">${escapeHtml(device?.asset_tag || device?.name || device?.id || "—")}</td>
        <td class="mono">${escapeHtml(device?.serial || "—")}</td>
        <td class="mono">${escapeHtml(cart?.asset_tag || cart?.name || cart?.id || "—")}</td>
        <td class="result-cell">${ok ? "Success" : "Error"}</td>
        <td class="muted">${escapeHtml(message || "")}</td>
    `;

    tbody.prepend(tr);
    hydrateActivityTimes(tr);
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
                device_id: device.id
            },
            "Unable to move device."
        );

        await refreshMediaCatalogViews();

        selectedCart = data.cart || destinationCart;
        await selectCart(selectedCart);

        prependRecent(
            "moved_to_cart",
            data.device || device,
            selectedCart,
            true,
            data.message || "Device moved to destination cart."
        );

        setStatus(
            data.message || "Device moved to destination cart.",
            true
        );
    } catch (err) {
        await refreshMediaCatalogViews();

        /*
         * Reload the source cart because the device may have been checked
         * in successfully before the destination checkout failed.
         */
        if (sourceCart) {
            selectedCart = sourceCart;
            await selectCart(sourceCart);
        }

        prependRecent(
            "move_failed",
            device,
            destinationCart,
            false,
            err.message || "Unable to move device."
        );

        setStatus(
            err.message || "Unable to move device.",
            false
        );
    }
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
        unassigned_cart: "Unassigned Cart",
        removed_all_devices: "Removed All Devices",
        remove_all_devices_partial: "Remove All Devices - Partial",
        remove_all_devices_failed: "Remove All Devices Failed",
        updated_cart_metadata: "Updated Cart Fields",
        reordered_cart: "Reordered Cart",
        admin_updated_cart_metadata: "Admin Updated Cart Fields",
        updated_cart_location: "Updated Cart Location",
    };

    return labels[action] ||
        String(action || "")
            .replaceAll("_", " ")
            .replace(/\b\w/g, c => c.toUpperCase());
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

function openStudentCheckoutsTab(status = "active", query = "") {
    if (!window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS) {
        setStatus("You do not have permission to manage Student Checkouts.", false);
        return;
    }

    setStudentCheckoutListState(status || "active", query || "");

    const tab = document.querySelector('[data-tab="student-checkouts"]');
    if (tab) {
        tab.click();
    }
    loadStudentCheckouts();
}

function bindStudentCheckoutsPage() {
    if (!window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS) return;

    $("refreshStudentCheckoutsBtn")?.addEventListener("click", loadStudentCheckouts);
    $("openStudentCheckoutFromPageBtn")?.addEventListener("click", openStudentCheckoutModal);

    document.querySelectorAll("[data-checkout-status-filter]").forEach(btn => {
        btn.addEventListener("click", () => {
            studentCheckoutStatusFilter = btn.dataset.checkoutStatusFilter || "active";
            updateStudentCheckoutFilterButtons();
            loadStudentCheckouts();
        });
    });

    const search = $("studentCheckoutSearch");
    if (search) {
        const run = debounce(() => {
            studentCheckoutSearchQuery = search.value.trim();
            loadStudentCheckouts();
        }, 250);

        search.addEventListener("input", run);
        search.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                event.preventDefault();
                studentCheckoutSearchQuery = search.value.trim();
                loadStudentCheckouts();
            }
        });
    }
}

function updateStudentCheckoutFilterButtons() {
    document.querySelectorAll("[data-checkout-status-filter]").forEach(btn => {
        btn.classList.toggle(
            "active",
            btn.dataset.checkoutStatusFilter === studentCheckoutStatusFilter
        );
    });
}

async function loadStudentCheckouts() {
    if (!window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS) return;

    const tbody = $("studentCheckoutsBody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="7" class="muted">Loading Student Checkouts...</td></tr>`;

    try {
        const data = await apiGet(
            `/api/student-checkouts?status=${encodeURIComponent(studentCheckoutStatusFilter)}&q=${encodeURIComponent(studentCheckoutSearchQuery)}`,
            "Unable to load Student Checkouts."
        );

        studentCheckoutsCache = data.checkouts || [];
        renderStudentCheckoutSummary(data.summary || {});
        renderStudentCheckouts(studentCheckoutsCache);
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" class="muted">${escapeHtml(err.message || "Unable to load Student Checkouts.")}</td></tr>`;
    }
}

function renderStudentCheckoutSummary(summary) {
    const el = $("studentCheckoutSummary");
    if (!el) return;

    el.innerHTML = `
        <button class="checkout-summary-pill" type="button" data-checkout-summary-status="active">
            <strong>${escapeHtml(summary.active_checkout_count || 0)}</strong>
            <span>Active</span>
        </button>
        <button class="checkout-summary-pill overdue" type="button" data-checkout-summary-status="overdue">
            <strong>${escapeHtml(summary.overdue_checkout_count || 0)}</strong>
            <span>Overdue</span>
        </button>
    `;

    el.querySelectorAll("[data-checkout-summary-status]").forEach(btn => {
        btn.addEventListener("click", () => {
            studentCheckoutStatusFilter = btn.dataset.checkoutSummaryStatus || "active";
            updateStudentCheckoutFilterButtons();
            loadStudentCheckouts();
        });
    });
}

function renderStudentCheckouts(checkouts) {
    const tbody = $("studentCheckoutsBody");
    const empty = $("studentCheckoutsEmpty");
    if (!tbody) return;

    if (!checkouts.length) {
        tbody.innerHTML = "";
        empty?.classList.remove("hidden");
        return;
    }

    empty?.classList.add("hidden");

    tbody.innerHTML = checkouts.map(checkout => {
        const canReturn = checkout.status !== "returned";

        return `
            <tr data-student-checkout-id="${escapeHtml(checkout.id)}">
                <td>
                    <strong>${escapeHtml(checkout.device_asset_tag || "No tag")}</strong>
                    <div class="muted mono">${escapeHtml(checkout.device_serial || "No serial")}</div>
                    <div class="muted">${escapeHtml(checkout.device_model_name || "")}</div>
                </td>
                <td>
                    <strong>${escapeHtml(checkout.student_name || "")}</strong>
                    <div class="muted">${escapeHtml(checkout.student_id || "No Student ID")}</div>
                </td>
                <td>
                    <strong>${escapeHtml(checkout.original_cart_asset_tag || checkout.original_cart_name || "Cart")}</strong>
                    <div class="muted">${escapeHtml(checkout.original_cart_teacher_name || "")}</div>
                    <div class="muted">${escapeHtml(checkout.original_cart_room_number ? "Room " + checkout.original_cart_room_number : "")}</div>
                </td>
                <td>${escapeHtml(formatActivityDateTime(checkout.checked_out_at))}</td>
                <td>${escapeHtml(checkout.return_by_date || "-")}</td>
                <td>${renderCheckoutStatusBadge(checkout)}</td>
                <td>
                    <div class="cart-action-group">
                        <button class="mini-btn" type="button" data-checkout-details-id="${escapeHtml(checkout.id)}">
                            Details
                        </button>
                        ${canReturn ? `
                            <button class="mini-btn" type="button" data-return-checkout-id="${escapeHtml(checkout.id)}">
                                Return
                            </button>
                        ` : ""}
                    </div>
                </td>
            </tr>
        `;
    }).join("");

    tbody.querySelectorAll("[data-checkout-details-id]").forEach(btn => {
        btn.addEventListener("click", () => {
            const checkout = studentCheckoutsCache.find(item => String(item.id) === String(btn.dataset.checkoutDetailsId));
            if (checkout) openStudentCheckoutDetails(checkout);
        });
    });

    tbody.querySelectorAll("[data-return-checkout-id]").forEach(btn => {
        btn.addEventListener("click", () => {
            const checkout = studentCheckoutsCache.find(item => String(item.id) === String(btn.dataset.returnCheckoutId));
            if (checkout) openReturnStudentCheckoutModal(checkout);
        });
    });
}

function renderCheckoutStatusBadge(checkout) {
    const status = checkout?.status || "active";
    const label = checkout?.status_label || (status === "overdue" ? "Overdue" : status === "returned" ? "Returned" : "Active");
    const overdueText = checkout?.days_overdue
        ? ` (${checkout.days_overdue} day${Number(checkout.days_overdue) === 1 ? "" : "s"})`
        : "";

    return `<span class="student-status-badge ${escapeHtml(status)}">${escapeHtml(label + overdueText)}</span>`;
}

function renderCartCheckoutSummary(cart) {
    const summary = cart.student_checkout_summary || {};
    const active = Number(summary.active_count || 0);
    const overdue = Number(summary.overdue_count || 0);

    return `
        <div class="cart-checkout-summary">
            <span>${escapeHtml(active)} checkout${active === 1 ? "" : "s"}</span>
            <span class="${overdue ? "checkout-overdue-text" : "muted"}">${escapeHtml(overdue)} overdue</span>
        </div>
    `;
}

function openCartCheckoutDetails(cart) {
    const summary = cart.student_checkout_summary || {};
    const checkouts = summary.checkouts || [];
    const title = cart.asset_tag ? `Cart ${cart.asset_tag} Student Checkouts` : "Cart Student Checkouts";

    if (!checkouts.length) {
        openConfirmModal({
            title,
            message: "No active Student Checkouts are recorded for this cart.",
            buttonText: "Close",
            action: async () => {}
        });
        return;
    }

    const rows = checkouts.map(checkout => `
        <div class="checkout-detail-row">
            <div>
                <strong>${escapeHtml(checkout.device_asset_tag || checkout.device_serial || "Device")}</strong>
                <span class="muted">${escapeHtml(checkout.student_name || "Student")}</span>
            </div>
            <div>
                <span class="muted">Due ${escapeHtml(checkout.return_by_date || "-")}</span>
                ${renderCheckoutStatusBadge(checkout)}
            </div>
        </div>
    `).join("");

    openConfirmModal({
        title,
        messageHtml: `
            <div class="checkout-detail-list">${rows}</div>
            ${window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS ? `
                <p class="confirm-copy">
                    Open Student Checkouts and search this cart to return devices or review history.
                </p>
            ` : ""}
        `,
        buttonText: "Close",
        action: async () => {}
    });
}

function studentCheckoutDetailRows(checkout) {
    return [
        ["Asset Tag", checkout.device_asset_tag || "-"],
        ["Serial Number", checkout.device_serial || "-"],
        ["Model", checkout.device_model_name || "-"],
        ["Student", checkout.student_name || "-"],
        ["Student ID", checkout.student_id || "-"],
        ["Original Cart", checkout.original_cart_asset_tag || checkout.original_cart_name || "-"],
        ["Teacher / Owner", checkout.original_cart_teacher_name || checkout.original_owner_display_name || "-"],
        ["Room", checkout.original_cart_room_number || "-"],
        ["Checkout Date", formatActivityDateTime(checkout.checked_out_at)],
        ["Return By", checkout.return_by_date || "-"],
        ["Returned", checkout.returned_at ? formatActivityDateTime(checkout.returned_at) : "-"],
        ["Checked Out By", checkout.checkout_actor_display_name || checkout.checkout_actor_email || "-"],
        ["Returned By", checkout.return_actor_display_name || checkout.return_actor_email || "-"],
        ["Status", checkout.status_label || "-"],
    ];
}

function renderDetailCard(rows) {
    return `
        <div class="device-detail-grid">
            ${rows.map(([label, value]) => `
                <div class="detail-item">
                    <span class="detail-label">${escapeHtml(label)}</span>
                    <span class="detail-value">${escapeHtml(value || "-")}</span>
                </div>
            `).join("")}
        </div>
    `;
}

function openStudentCheckoutDetails(checkout) {
    openConfirmModal({
        title: "Student Checkout Details",
        messageHtml: renderDetailCard(studentCheckoutDetailRows(checkout)),
        buttonText: "Close",
        action: async () => {}
    });
}

function bindStudentCheckoutModal() {
    if (!window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS) return;

    $("openStudentCheckoutBtn")?.addEventListener("click", openStudentCheckoutModal);
    $("closeStudentCheckoutBtn")?.addEventListener("click", closeStudentCheckoutModal);
    $("cancelStudentCheckoutBtn")?.addEventListener("click", closeStudentCheckoutModal);
    $("lookupStudentCheckoutDeviceBtn")?.addEventListener("click", lookupStudentCheckoutDevice);
    $("completeStudentCheckoutBtn")?.addEventListener("click", completeStudentCheckout);

    $("studentCheckoutIdentifier")?.addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            lookupStudentCheckoutDevice();
        }
    });

    $("studentCheckoutName")?.addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            completeStudentCheckout();
        }
    });

    $("studentCheckoutModal")?.addEventListener("click", event => {
        if (event.target.id === "studentCheckoutModal") {
            closeStudentCheckoutModal();
        }
    });
}

function openStudentCheckoutModal() {
    if (!window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS) {
        setStatus("You do not have permission to manage Student Checkouts.", false);
        return;
    }

    resetStudentCheckoutModal();
    $("studentCheckoutModal")?.classList.remove("hidden");
    setTimeout(() => $("studentCheckoutIdentifier")?.focus(), 50);
}

function closeStudentCheckoutModal() {
    $("studentCheckoutModal")?.classList.add("hidden");
}

function resetStudentCheckoutModal() {
    studentCheckoutLookup = null;

    if ($("studentCheckoutIdentifier")) $("studentCheckoutIdentifier").value = "";
    if ($("studentCheckoutName")) $("studentCheckoutName").value = "";
    if ($("studentCheckoutId")) $("studentCheckoutId").value = "";
    if ($("studentCheckoutReturnBy")) $("studentCheckoutReturnBy").value = "";
    if ($("studentCheckoutLookupResult")) {
        $("studentCheckoutLookupResult").innerHTML = `<div class="muted">Locate a device to begin checkout.</div>`;
    }

    setStudentCheckoutModalStatus("", true, true);
    updateStudentCheckoutSubmitState();
}

function setStudentCheckoutModalStatus(message, ok = true, hidden = false) {
    const el = $("studentCheckoutModalStatus");
    if (!el) return;

    el.textContent = message || "";
    el.classList.toggle("hidden", hidden || !message);
    el.classList.toggle("ok", Boolean(ok));
    el.classList.toggle("bad", !ok);
}

function updateStudentCheckoutSubmitState() {
    const btn = $("completeStudentCheckoutBtn");
    if (!btn) return;

    const lookupReady =
        studentCheckoutLookup &&
        studentCheckoutLookup.eligible &&
        !studentCheckoutLookup.active_checkout &&
        studentCheckoutLookup.device;

    btn.disabled = !lookupReady;
}

async function lookupStudentCheckoutDevice() {
    const input = $("studentCheckoutIdentifier");
    const query = (input?.value || "").trim();
    const resultEl = $("studentCheckoutLookupResult");

    if (!query) {
        setStudentCheckoutModalStatus("Scan or type an Asset Tag or Serial Number.", false);
        return;
    }

    studentCheckoutLookup = null;
    updateStudentCheckoutSubmitState();

    if (resultEl) {
        resultEl.innerHTML = `<div class="muted">Locating device...</div>`;
    }

    setStudentCheckoutModalStatus("Locating device...", true);

    try {
        const data = await apiGet(
            `/api/student-checkouts/lookup?q=${encodeURIComponent(query)}`,
            "Device lookup failed."
        );

        studentCheckoutLookup = data;
        renderStudentCheckoutLookup(data);
        setStudentCheckoutModalStatus("", true, true);
        updateStudentCheckoutSubmitState();
    } catch (err) {
        if (resultEl) {
            resultEl.innerHTML = `<div class="checkout-warning">${escapeHtml(err.message || "Device lookup failed.")}</div>`;
        }
        setStudentCheckoutModalStatus(err.message || "Device lookup failed.", false);
        updateStudentCheckoutSubmitState();
    }
}

function renderStudentCheckoutLookup(data) {
    const resultEl = $("studentCheckoutLookupResult");
    if (!resultEl) return;

    const device = data.device || {};
    const cart = data.cart || {};
    const ownership = data.ownership || {};
    const active = data.active_checkout || null;
    const canCheckout = data.eligible && !active;

    if ($("studentCheckoutReturnBy") && data.default_return_by_date) {
        $("studentCheckoutReturnBy").value = data.default_return_by_date;
    }

    const activeMessage = active
        ? `This device is currently checked out to ${active.student_name || "another student"} and must be returned before it can be checked out again.`
        : "";

    resultEl.innerHTML = `
        <div class="checkout-lookup-card ${canCheckout ? "ok" : "bad"}">
            <div class="checkout-lookup-main">
                <strong>${escapeHtml(device.asset_tag || device.serial || "Device")}</strong>
                <span>${escapeHtml(device.model_name || device.name || "")}</span>
                <span class="mono">${escapeHtml(device.serial || "")}</span>
            </div>

            <div class="checkout-lookup-context">
                <span><strong>Cart</strong> ${escapeHtml(cart.asset_tag || cart.name || "-")}</span>
                <span><strong>Teacher</strong> ${escapeHtml(ownership.teacher_name || ownership.owner_display_name || "-")}</span>
                <span><strong>Room</strong> ${escapeHtml(ownership.room_number || "-")}</span>
                <span><strong>Status</strong> ${escapeHtml(device.status_name || "-")}</span>
            </div>

            ${activeMessage ? `<div class="checkout-warning">${escapeHtml(activeMessage)}</div>` : ""}
            ${!data.eligible ? `<div class="checkout-warning">${escapeHtml(data.eligibility_message || "This device is not eligible for Student Checkout.")}</div>` : ""}
        </div>
    `;
}

async function completeStudentCheckout() {
    if (!studentCheckoutLookup?.device) {
        setStudentCheckoutModalStatus("Locate an eligible device before completing checkout.", false);
        return;
    }

    const studentName = ($("studentCheckoutName")?.value || "").trim();
    const studentId = ($("studentCheckoutId")?.value || "").trim();
    const returnByDate = ($("studentCheckoutReturnBy")?.value || "").trim();
    const identifier = ($("studentCheckoutIdentifier")?.value || "").trim();

    if (!studentName) {
        setStudentCheckoutModalStatus("Student Name is required.", false);
        $("studentCheckoutName")?.focus();
        return;
    }

    const btn = $("completeStudentCheckoutBtn");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "Completing...";
    }

    setStudentCheckoutModalStatus("Completing Student Checkout...", true);

    try {
        const data = await apiPost(
            "/api/student-checkouts",
            {
                identifier,
                device_id: studentCheckoutLookup.device.id,
                student_name: studentName,
                student_id: studentId,
                return_by_date: returnByDate,
            },
            "Unable to create Student Checkout."
        );

        closeStudentCheckoutModal();
        resetStudentCheckoutModal();
        await refreshStudentCheckoutDependentViews({ afterCreate: true });
        setStatus(data.message || "Student Checkout created.", true);
    } catch (err) {
        if (err.existing_checkout) {
            studentCheckoutLookup.active_checkout = err.existing_checkout;
            renderStudentCheckoutLookup(studentCheckoutLookup);
        }

        setStudentCheckoutModalStatus(err.message || "Unable to create Student Checkout.", false);
    } finally {
        if (btn) {
            btn.textContent = "Complete Checkout";
            updateStudentCheckoutSubmitState();
        }
    }
}

function bindReturnStudentCheckoutModal() {
    if (!window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS) return;

    $("closeReturnStudentCheckoutBtn")?.addEventListener("click", closeReturnStudentCheckoutModal);
    $("cancelReturnStudentCheckoutBtn")?.addEventListener("click", closeReturnStudentCheckoutModal);
    $("confirmReturnStudentCheckoutBtn")?.addEventListener("click", confirmReturnStudentCheckout);

    $("returnStudentCheckoutModal")?.addEventListener("click", event => {
        if (event.target.id === "returnStudentCheckoutModal") {
            closeReturnStudentCheckoutModal();
        }
    });
}

function openReturnStudentCheckoutModal(checkout) {
    pendingReturnCheckout = checkout;

    const title = $("returnStudentCheckoutTitle");
    const body = $("returnStudentCheckoutBody");

    if (title) {
        title.textContent = `Return ${checkout.device_asset_tag || checkout.device_serial || "Device"}`;
    }

    if (body) {
        body.innerHTML = renderDetailCard(studentCheckoutDetailRows(checkout));
    }

    setReturnStudentCheckoutStatus("", true, true);
    $("returnStudentCheckoutModal")?.classList.remove("hidden");
}

function closeReturnStudentCheckoutModal() {
    pendingReturnCheckout = null;
    $("returnStudentCheckoutModal")?.classList.add("hidden");
}

function setReturnStudentCheckoutStatus(message, ok = true, hidden = false) {
    const el = $("returnStudentCheckoutStatus");
    if (!el) return;

    el.textContent = message || "";
    el.classList.toggle("hidden", hidden || !message);
    el.classList.toggle("ok", Boolean(ok));
    el.classList.toggle("bad", !ok);
}

async function confirmReturnStudentCheckout() {
    const checkout = pendingReturnCheckout;
    if (!checkout) return;

    const btn = $("confirmReturnStudentCheckoutBtn");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "Returning...";
    }

    setReturnStudentCheckoutStatus("Returning device...", true);

    try {
        const data = await apiPost(
            `/api/student-checkouts/${checkout.id}/return`,
            {},
            "Unable to return device."
        );

        closeReturnStudentCheckoutModal();
        await refreshStudentCheckoutDependentViews({ afterReturn: true });
        setStatus(data.message || "Device returned.", true);
    } catch (err) {
        setReturnStudentCheckoutStatus(err.message || "Unable to return device.", false);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "Return Device";
        }
    }
}

function bindMediaTabs() {
    const defaultTab = "dashboard";

    const tabs = Array.from(
        document.querySelectorAll(
            ".media-catalog-tabs .settings-tab"
        )
    );

    const panels = Array.from(
        document.querySelectorAll(
            ".media-catalog-tab-stack .settings-tab-panel"
        )
    );

    if (!tabs.length || !panels.length) return;

    function tabExists(tabName) {
        return (
            tabs.some(tab => tab.dataset.tab === tabName) &&
            panels.some(panel => panel.dataset.panel === tabName)
        );
    }

    function getTabFromHash() {
        const hashTab = window.location.hash
            .replace(/^#/, "")
            .trim();

        return tabExists(hashTab)
            ? hashTab
            : defaultTab;
    }

    function loadTabContent(tabName) {
        if (tabName === "dashboard") {
            loadDashboard();
        }

        if (
            tabName === "student-checkouts" &&
            window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS
        ) {
            loadStudentCheckouts();
        }

        if (
            tabName === "ownership-management" &&
            window.MEDIA_CATALOG_CAN_VIEW_OWNERSHIP
        ) {
            loadOwnershipOwners();
        }
    }

    function activateMediaTab(
        tabName,
        {
            updateUrl = true,
            loadContent = true
        } = {}
    ) {
        const target = tabExists(tabName)
            ? tabName
            : defaultTab;

        tabs.forEach(tab => {
            const isActive =
                tab.dataset.tab === target;

            tab.classList.toggle("active", isActive);

            tab.setAttribute(
                "aria-selected",
                isActive ? "true" : "false"
            );

            tab.setAttribute(
                "tabindex",
                isActive ? "0" : "-1"
            );
        });

        panels.forEach(panel => {
            const isActive =
                panel.dataset.panel === target;

            panel.classList.toggle("active", isActive);
            panel.hidden = !isActive;
        });

        if (updateUrl) {
            const nextUrl =
                target === defaultTab
                    ? `${window.location.pathname}${window.location.search}`
                    : `${window.location.pathname}${window.location.search}#${target}`;

            /*
             * replaceState avoids adding a new browser-history
             * entry every time the user changes tabs.
             */
            window.history.replaceState(
                null,
                "",
                nextUrl
            );
        }

        if (loadContent) {
            loadTabContent(target);
        }
    }

    tabs.forEach((tab, index) => {
        tab.setAttribute("role", "tab");

        tab.addEventListener("click", () => {
            activateMediaTab(tab.dataset.tab);
        });

        tab.addEventListener("keydown", event => {
            if (
                ![
                    "ArrowLeft",
                    "ArrowRight",
                    "Home",
                    "End"
                ].includes(event.key)
            ) {
                return;
            }

            event.preventDefault();

            let nextIndex = index;

            if (event.key === "ArrowRight") {
                nextIndex =
                    (index + 1) % tabs.length;
            }

            if (event.key === "ArrowLeft") {
                nextIndex =
                    (index - 1 + tabs.length) %
                    tabs.length;
            }

            if (event.key === "Home") {
                nextIndex = 0;
            }

            if (event.key === "End") {
                nextIndex = tabs.length - 1;
            }

            const nextTab = tabs[nextIndex];

            activateMediaTab(
                nextTab.dataset.tab
            );

            nextTab.focus();
        });
    });

    panels.forEach(panel => {
        panel.setAttribute(
            "role",
            "tabpanel"
        );
    });

    /*
     * A browser refresh retains the hash.
     * A new visit through the Media Catalog menu normally has
     * no hash and therefore opens Dashboard.
     */
    activateMediaTab(
        getTabFromHash(),
        {
            updateUrl: false,
            loadContent: true
        }
    );
}

function closeOwnershipExportMenu() {
    document.querySelectorAll(".media-export-menu").forEach(menu => {
        menu.classList.add("hidden");
    });

    document.querySelectorAll("[data-export-menu-button]").forEach(button => {
        button.setAttribute("aria-expanded", "false");
    });

    $("ownershipExportMenuBtn")?.setAttribute("aria-expanded", "false");
}


function toggleExportMenu(button) {
    const wrapper = button.closest(".media-export-menu-wrap");
    const menu = wrapper?.querySelector(".media-export-menu");

    if (!menu) return;

    const willOpen = menu.classList.contains("hidden");

    closeOwnershipExportMenu();

    menu.classList.toggle("hidden", !willOpen);
    button.setAttribute("aria-expanded", willOpen ? "true" : "false");
}


function bindExportButtons() {
    document.addEventListener("click", event => {
        const exportMyCartsBtn = event.target.closest("#exportMyCartsBtn");
        const exportSelectedCartBtn = event.target.closest("#exportSelectedCartBtn");
        const exportMenuButton = event.target.closest("[data-export-menu-button], #ownershipExportMenuBtn");
        const ownershipExportItem = event.target.closest("[data-ownership-export]");
        const userExportItem = event.target.closest("[data-user-export]");
        const cartExportItem = event.target.closest("[data-cart-export]");

        if (exportMyCartsBtn) {
            event.preventDefault();
            closeOwnershipExportMenu();
            window.location.href = `${MEDIA_CATALOG_BASE}/export/my-carts.pdf`;
            return;
        }

        if (exportSelectedCartBtn) {
            event.preventDefault();
            closeOwnershipExportMenu();

            if (!selectedCart || !selectedCart.id) {
                setStatus("Select a cart before exporting.", false);
                return;
            }

            window.location.href =
                `${MEDIA_CATALOG_BASE}/export/cart/${encodeURIComponent(selectedCart.id)}.pdf`;
            return;
        }

        if (exportMenuButton) {
            event.preventDefault();
            event.stopPropagation();
            toggleExportMenu(exportMenuButton);
            return;
        }

        if (ownershipExportItem) {
            event.preventDefault();
            event.stopPropagation();

            const exportType = ownershipExportItem.dataset.ownershipExport || "";
            closeOwnershipExportMenu();

            if (exportType === "pdf") {
                window.location.href =
                    `${MEDIA_CATALOG_BASE}/export/all-assigned-carts.pdf`;
                return;
            }

            if (exportType === "csv-carts") {
                window.location.href =
                    `${MEDIA_CATALOG_BASE}/export/all-assigned-carts.csv?mode=carts`;
                return;
            }

            if (exportType === "csv-assets") {
                window.location.href =
                    `${MEDIA_CATALOG_BASE}/export/all-assigned-carts.csv?mode=assets`;
                return;
            }
        }

        if (userExportItem) {
            event.preventDefault();
            event.stopPropagation();

            const exportType = userExportItem.dataset.userExport || "";
            const userId = userExportItem.dataset.userId || "";

            if (!userId) {
                setStatus("Select a user before exporting.", false);
                closeOwnershipExportMenu();
                return;
            }

            closeOwnershipExportMenu();

            if (exportType === "pdf") {
                window.location.href =
                    `${MEDIA_CATALOG_BASE}/export/user/${encodeURIComponent(userId)}/carts.pdf`;
                return;
            }

            if (exportType === "csv-carts") {
                window.location.href =
                    `${MEDIA_CATALOG_BASE}/export/user/${encodeURIComponent(userId)}/carts.csv?mode=carts`;
                return;
            }

            if (exportType === "csv-assets") {
                window.location.href =
                    `${MEDIA_CATALOG_BASE}/export/user/${encodeURIComponent(userId)}/carts.csv?mode=assets`;
                return;
            }
        }

        if (cartExportItem) {
            event.preventDefault();
            event.stopPropagation();

            const exportType = cartExportItem.dataset.cartExport || "";
            const cartId = cartExportItem.dataset.cartId || "";

            if (!cartId) {
                setStatus("Select a cart before exporting.", false);
                closeOwnershipExportMenu();
                return;
            }

            closeOwnershipExportMenu();

            if (exportType === "pdf") {
                window.location.href =
                    `${MEDIA_CATALOG_BASE}/export/cart/${encodeURIComponent(cartId)}.pdf`;
                return;
            }

            if (exportType === "csv-assets") {
                window.location.href =
                    `${MEDIA_CATALOG_BASE}/export/cart/${encodeURIComponent(cartId)}.csv?mode=assets`;
                return;
            }
        }

        if (!event.target.closest(".media-export-menu-wrap")) {
            closeOwnershipExportMenu();
        }
    });
}


function bindOwnershipManagement() {
    if (!window.MEDIA_CATALOG_CAN_VIEW_OWNERSHIP) {
        return;
    }

    $("refreshOwnershipBtn")?.addEventListener("click", loadOwnershipOwners);

    $("toggleOwnershipFindCartBtn")?.addEventListener("click", () => {
        const panel = $("ownershipFindCartPanel");
        if (!panel) return;

        panel.classList.toggle("hidden");

        if (!panel.classList.contains("hidden")) {
            $("ownershipCartSearch")?.focus();
        }
    });

    bindOwnershipCartSearch();
}

function bindRecentActivityFilter() {
    const filter = $("recentResultFilter");
    const body = $("recentBody");
    const emptyState = $("recentActivityEmpty");

    if (!filter || !body) {
        return;
    }

    function applyRecentActivityFilter() {
        const selectedResult = filter.value;
        const rows = Array.from(
            body.querySelectorAll("tr[data-result]")
        );

        let visibleCount = 0;

        rows.forEach(row => {
            const rowResult = row.dataset.result;
            const shouldShow =
                selectedResult === "all" ||
                rowResult === selectedResult;

            row.classList.toggle("hidden", !shouldShow);

            if (shouldShow) {
                visibleCount += 1;
            }
        });

        if (emptyState) {
            emptyState.classList.toggle(
                "hidden",
                visibleCount !== 0
            );
        }
    }

    filter.addEventListener(
        "change",
        applyRecentActivityFilter
    );

    applyRecentActivityFilter();
}


async function loadOwnershipOwners() {
    const el = $("ownershipOwners");
    const cartsEl = $("ownershipUserCarts");

    if (!el) return;

    el.innerHTML = `
        <div class="muted">
            Loading assigned cart owners...
        </div>
    `;

    setManagedDeviceSummaryValue(
        "allManagedDeviceTotal",
        "..."
    );

    if (cartsEl && !ownershipSelectedUser) {
        cartsEl.innerHTML = "";
    }

    try {
        const data = await apiGet(
            "/api/ownership/owners",
            "Unable to load assigned cart owners."
        );

        ownershipOwnersCache = data.owners || [];

        renderOwnershipOwners(
            ownershipOwnersCache
        );

        setManagedDeviceSummaryValue(
            "allManagedDeviceTotal",
            Number(data.total_devices_managed || 0)
        );

        setStatus(
            `Loaded ${ownershipOwnersCache.length} assigned cart owner(s).`,
            true
        );
    } catch (err) {
        el.innerHTML = `
            <div class="muted">
                ${escapeHtml(
                    err.message ||
                    "Unable to load assigned cart owners."
                )}
            </div>
        `;

        setManagedDeviceSummaryValue(
            "allManagedDeviceTotal",
            "Error"
        );

        setStatus(
            err.message ||
            "Unable to load assigned cart owners.",
            false
        );
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
                    <tr>
                        <th>User</th>
                        <th>Email</th>
                        <th>Carts</th>
                        <th>Total Devices Managed</th>
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
                            <td>
                                <span class="managed-device-count-pill">
                                    ${escapeHtml(owner.total_devices_managed || 0)}
                                </span>
                            </td>
                            <td>${escapeHtml(formatFriendlyDateTime(owner.last_updated_at))}</td>
                            <td>
                                <button class="mini-btn" type="button" data-view-owner-id="${escapeHtml(owner.owner_user_id)}">
                                    View Carts
                                </button>
                                    <div class="media-export-menu-wrap">
                                        <button
                                            class="mini-btn"
                                            type="button"
                                            data-export-menu-button
                                            aria-expanded="false"
                                        >
                                            Export
                                        </button>

                                        <div class="media-export-menu hidden">
                                            <button
                                                class="media-export-menu-item"
                                                type="button"
                                                data-user-export="pdf"
                                                data-user-id="${escapeHtml(owner.owner_user_id)}"
                                            >
                                                PDF
                                            </button>

                                            <button
                                                class="media-export-menu-item"
                                                type="button"
                                                data-user-export="csv-carts"
                                                data-user-id="${escapeHtml(owner.owner_user_id)}"
                                            >
                                                CSV - Carts Only
                                            </button>

                                            <button
                                                class="media-export-menu-item"
                                                type="button"
                                                data-user-export="csv-assets"
                                                data-user-id="${escapeHtml(owner.owner_user_id)}"
                                            >
                                                CSV - Assets in Carts
                                            </button>
                                        </div>
                                    </div>
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
                            <th>Student Checkouts</th>
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
                                        <span class="device-count-badge">
                                            ${escapeHtml(cart.device_count || 0)}
                                        </span>
                                    </td>
                                    <td>
                                        ${renderCartCheckoutSummary(cart)}
                                    </td>
                                    <td>
                                    <button
                                        class="mini-btn"
                                        type="button"
                                        data-admin-assign-owner-id="${escapeHtml(cart.id)}"
                                    >
                                        Assign Owner
                                    </button>

                                    <button
                                        class="mini-btn remove"
                                        type="button"
                                        data-admin-unassign-cart-id="${escapeHtml(cart.id)}"
                                    >
                                        Unassign Cart
                                    </button>

                                    <div class="media-export-menu-wrap">
                                        <button
                                            class="mini-btn"
                                            type="button"
                                            data-export-menu-button
                                            aria-expanded="false"
                                        >
                                            Export
                                        </button>

                                        <div class="media-export-menu hidden">
                                            <button
                                                class="media-export-menu-item"
                                                type="button"
                                                data-cart-export="pdf"
                                                data-cart-id="${escapeHtml(cart.id)}"
                                            >
                                                PDF
                                            </button>

                                            <button
                                                class="media-export-menu-item"
                                                type="button"
                                                data-cart-export="csv-assets"
                                                data-cart-id="${escapeHtml(cart.id)}"
                                            >
                                                CSV - Assets in Cart
                                            </button>
                                        </div>
                                    </div>
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

    document.querySelectorAll(
        "[data-admin-unassign-cart-id]"
    ).forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const cart = carts.find(
                item =>
                    String(item.id) ===
                    String(btn.dataset.adminUnassignCartId)
            );

            if (cart) {
                requestUnassignCart(cart, {
                    source: "ownership-management",
                    owner: ownershipSelectedUser
                });
            }
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

    document.querySelectorAll("#ownershipUserCartsBody [data-cart-checkouts-id]").forEach(btn => {
        btn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const cart = carts.find(item => String(item.id) === String(btn.dataset.cartCheckoutsId));
            if (cart) openCartCheckoutDetails(cart);
        });
    });
}


function renderAdminInlineEditField(cartId, field, value) {
    const canManage = Boolean(window.MEDIA_CATALOG_CAN_MANAGE_OWNERSHIP);

    if (!canManage) {
        return `<span>${escapeHtml(value || "—")}</span>`;
    }

    return renderInlineEditField(cartId, field, value);
}


function activateAdminInlineEdit(
    wrapper,
    carts
) {
    const input = wrapper.querySelector(
        ".inline-cart-field"
    );

    if (!input) return;

    if (
        wrapper.classList.contains(
            "is-editing"
        )
    ) {
        input.focus();
        input.select();
        return;
    }

    wrapper.classList.add("is-editing");

    input.hidden = false;
    input.classList.remove("hidden");
    input.classList.add(
        "inline-edit-active"
    );

    input.focus();
    input.select();

    let submitted = false;

    const submit = async () => {
        if (submitted) return;

        submitted = true;

        const cartId = input.dataset.cartId;
        const field = input.dataset.field;
        const value = input.value;

        applyOptimisticCartMetadata(
            cartId,
            field,
            value,
            carts
        );

        cancelInlineEdit(wrapper);

        const valueEl = wrapper.querySelector(
            ".inline-edit-value"
        );

        if (valueEl) {
            valueEl.textContent =
                value.trim() || "—";
        }

        setStatus(
            "Saving cart fields...",
            true
        );

        try {
            await queueCartMetadataSave(
                cartId,
                carts,
                {
                    admin: true
                }
            );

        } catch (err) {
            setStatus(
                err.message ||
                "Unable to update cart fields.",
                false
            );

            if (ownershipSelectedUser) {
                await loadOwnershipUserCarts(
                    ownershipSelectedUser
                );
            }
        }
    };

    input.addEventListener(
        "keydown",
        async event => {
            if (event.key === "Enter") {
                event.preventDefault();
                event.stopPropagation();

                await submit();
                return;
            }

            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();

                cancelInlineEdit(wrapper);
            }
        }
    );

    input.addEventListener(
        "blur",
        async () => {
            await submit();
        },
        {
            once: true
        }
    );
}

function getCartFromState(cartId, carts = []) {
    return (
        carts.find(item => String(item.id) === String(cartId)) ||
        myCartsCache.find(item => String(item.id) === String(cartId)) ||
        (
            selectedCart &&
            String(selectedCart.id) === String(cartId)
                ? selectedCart
                : null
        )
    );
}


function applyOptimisticCartMetadata(
    cartId,
    field,
    value,
    carts = []
) {
    const normalizedValue = String(value || "").trim();

    const updateCart = cart => {
        if (!cart || String(cart.id) !== String(cartId)) {
            return cart;
        }

        return {
            ...cart,
            ownership: {
                ...(cart.ownership || {}),
                [field]: normalizedValue,
            },
        };
    };

    const cartIndex = carts.findIndex(
        item => String(item.id) === String(cartId)
    );

    if (cartIndex >= 0) {
        carts[cartIndex] = updateCart(carts[cartIndex]);
    }

    myCartsCache = myCartsCache.map(updateCart);

    if (
        selectedCart &&
        String(selectedCart.id) === String(cartId)
    ) {
        selectedCart = updateCart(selectedCart);

        const subtitle = $("cartSubtitle");

        if (subtitle) {
            subtitle.innerHTML =
                renderSelectedCartMeta(selectedCart);
        }

        updateActiveCartSummary();
    }
}


function queueCartMetadataSave(
    cartId,
    carts,
    {
        admin = false
    } = {}
) {
    const existingQueue =
        cartMetadataSaveQueues.get(String(cartId)) ||
        Promise.resolve();

    const nextSave = existingQueue
        .catch(() => {
            /*
             * A previous save failing must not permanently
             * break the queue.
             */
        })
        .then(async () => {
            const cart = getCartFromState(
                cartId,
                carts
            );

            if (!cart) {
                throw new Error(
                    "Unable to locate cart while saving metadata."
                );
            }

            const ownership = cart.ownership || {};

            /*
             * IMPORTANT:
             *
             * Build this from current application state,
             * not from potentially stale DOM inputs.
             */
            const body = {
                teacher_name:
                    ownership.teacher_name || "",

                room_number:
                    ownership.room_number || "",
            };

            const endpoint = admin
                ? `/api/admin/carts/${cartId}/metadata`
                : `/api/carts/${cartId}/metadata`;

            const data = await apiPost(
                endpoint,
                body,
                "Unable to update cart fields."
            );

            const serverCart = data.cart || {};

            /*
             * Server response may contain stale nested ownership
             * information if another edit occurred while the
             * request was running.
             *
             * Latest local state wins.
             */
            const currentCart = getCartFromState(
                cartId,
                carts
            ) || cart;

            const confirmedCart = {
                ...currentCart,
                ...serverCart,

                ownership: {
                    ...(serverCart.ownership || {}),
                    ...(currentCart.ownership || {}),
                },
            };

            const index = carts.findIndex(
                item =>
                    String(item.id) ===
                    String(cartId)
            );

            if (index >= 0) {
                carts[index] = confirmedCart;
            }

            myCartsCache = myCartsCache.map(item => {
                if (
                    String(item.id) !==
                    String(cartId)
                ) {
                    return item;
                }

                return {
                    ...item,
                    ...confirmedCart,

                    ownership: {
                        ...(item.ownership || {}),
                        ...(confirmedCart.ownership || {}),
                    },
                };
            });

            if (
                selectedCart &&
                String(selectedCart.id) ===
                String(cartId)
            ) {
                selectedCart = {
                    ...selectedCart,
                    ...confirmedCart,

                    ownership: {
                        ...(selectedCart.ownership || {}),
                        ...(confirmedCart.ownership || {}),
                    },
                };

                const subtitle = $("cartSubtitle");

                if (subtitle) {
                    subtitle.innerHTML =
                        renderSelectedCartMeta(
                            selectedCart
                        );
                }

                updateActiveCartSummary();
            }

            setStatus(
                data.message ||
                "Cart fields updated.",
                true
            );

            return data;
        });

    cartMetadataSaveQueues.set(
        String(cartId),
        nextSave
    );

    nextSave.finally(() => {
        if (
            cartMetadataSaveQueues.get(
                String(cartId)
            ) === nextSave
        ) {
            cartMetadataSaveQueues.delete(
                String(cartId)
            );
        }
    });

    return nextSave;
}

function captureScrollState() {
    return {
        x: window.scrollX || 0,
        y: window.scrollY || 0,
    };
}


function restoreScrollState(state) {
    if (!state) return;

    window.requestAnimationFrame(() => {
        window.scrollTo(state.x, state.y);
    });
}


function mergeCartUpdate(existingCart, updatedCart) {
    if (!updatedCart) return existingCart;

    return {
        ...(existingCart || {}),
        ...updatedCart,
        device_count: updatedCart.device_count ?? existingCart?.device_count ?? 0,
        ownership: {
            ...(existingCart?.ownership || {}),
            ...(updatedCart.ownership || {}),
        },
    };
}


function syncUpdatedCartIntoState(updatedCart, carts, existingCart) {
    if (!updatedCart) return existingCart;

    const merged = mergeCartUpdate(existingCart, updatedCart);

    const rowIndex = carts.findIndex(item => String(item.id) === String(merged.id));
    if (rowIndex >= 0) {
        carts[rowIndex] = merged;
    }

    myCartsCache = myCartsCache.map(item =>
        String(item.id) === String(merged.id)
            ? mergeCartUpdate(item, merged)
            : item
    );

    if (selectedCart && String(selectedCart.id) === String(merged.id)) {
        selectedCart = mergeCartUpdate(selectedCart, merged);

        const subtitle = $("cartSubtitle");
        if (subtitle) {
            subtitle.innerHTML = renderSelectedCartMeta(selectedCart);
        }

        updateActiveCartSummary();
    }

    return merged;
}


function applyUpdatedMetadataToRow(row, updatedCart) {
    if (!row || !updatedCart) return;

    const ownership = updatedCart.ownership || {};

    ["teacher_name", "room_number"].forEach(field => {
        const wrapper = row.querySelector(`.inline-edit-control[data-field-wrap="${field}"]`);
        const input = wrapper?.querySelector(`[data-field="${field}"]`);
        const valueEl = wrapper?.querySelector(".inline-edit-value");
        const value = String(ownership[field] || "").trim();

        if (input) {
            input.value = value;
        }

        if (valueEl) {
            valueEl.textContent = value || "—";
        }
    });
}


function drawMyCartsRows(rows) {
    const tbody = $("myCartsBody");
    if (!tbody) return;

    tbody.innerHTML = rows.map(cart => {
        const ownership = cart.ownership || {};

        return `
            <tr
                class="my-cart-row"
                draggable="true"
                data-cart-id="${escapeHtml(cart.id)}"
            >
                <td
                    class="drag-handle"
                    title="Drag to reorder"
                    aria-label="Drag to reorder"
                >
                    ☰
                </td>

                <td>
                    <button
                        class="link-button"
                        type="button"
                        data-open-cart-id="${escapeHtml(cart.id)}"
                    >
                        ${escapeHtml(cartDisplayName(cart))}
                    </button>

                    <div class="muted">
                        ${escapeHtml(cart.model_name || "")}
                    </div>
                </td>

                <td>
                    ${renderInlineEditField(
                        cart.id,
                        "teacher_name",
                        ownership.teacher_name || "—"
                    )}
                </td>

                <td>
                    ${renderInlineEditField(
                        cart.id,
                        "room_number",
                        ownership.room_number || "—"
                    )}
                </td>

                <td>
                    ${renderLocationEditField(cart)}
                </td>

                <td>
                    <span class="device-count-badge">
                        ${escapeHtml(cart.device_count || 0)}
                    </span>
                </td>

                <td>
                    ${renderCartCheckoutSummary(cart)}
                </td>

                <td>
                    <div class="cart-action-group">
                        <button
                            class="mini-btn"
                            type="button"
                            data-cart-details-id="${escapeHtml(cart.id)}"
                        >
                            Details
                        </button>

                        <button
                            class="mini-btn remove"
                            type="button"
                            data-unassign-cart-id="${escapeHtml(cart.id)}"
                        >
                            Unassign Cart
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");

    bindMyCartTableEvents(rows);
    bindLocationEditButtons(rows);
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
                hidden
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
    const input = wrapper.querySelector(
        ".inline-cart-field"
    );

    if (!input) return;

    if (
        wrapper.classList.contains(
            "is-editing"
        )
    ) {
        input.focus();
        input.select();
        return;
    }

    wrapper.classList.add("is-editing");

    input.hidden = false;
    input.classList.remove("hidden");
    input.classList.add(
        "inline-edit-active"
    );

    input.focus();
    input.select();

    let submitted = false;

    const submit = async () => {
        if (submitted) return;

        submitted = true;

        const cartId = input.dataset.cartId;
        const field = input.dataset.field;
        const value = input.value;

        /*
         * Put the new value into application state BEFORE
         * starting the slow network request.
         */
        applyOptimisticCartMetadata(
            cartId,
            field,
            value,
            carts
        );

        /*
         * Immediately collapse the textbox.
         */
        cancelInlineEdit(wrapper);

        const valueEl = wrapper.querySelector(
            ".inline-edit-value"
        );

        if (valueEl) {
            valueEl.textContent =
                value.trim() || "—";
        }

        setStatus(
            "Saving cart fields...",
            true
        );

        try {
            await queueCartMetadataSave(
                cartId,
                carts,
                {
                    admin: false
                }
            );

        } catch (err) {
            setStatus(
                err.message ||
                "Unable to update cart fields.",
                false
            );

            /*
             * Something actually failed.
             * Reload authoritative server state.
             */
            await loadMyCarts();
        }
    };

    input.addEventListener(
        "keydown",
        async event => {
            if (event.key === "Enter") {
                event.preventDefault();
                event.stopPropagation();

                await submit();
                return;
            }

            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();

                cancelInlineEdit(wrapper);
            }
        }
    );

    input.addEventListener(
        "blur",
        async () => {
            await submit();
        },
        {
            once: true
        }
    );
}

function cancelInlineEdit(wrapper) {
    if (!wrapper) return;

    const input = wrapper.querySelector(".inline-cart-field");

    wrapper.classList.remove("is-editing");

    if (input) {
        input.classList.remove("inline-edit-active");
        input.classList.add("hidden");

        // Native hidden state guarantees the textbox disappears
        // even if another CSS selector has display: block !important.
        input.hidden = true;
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

function formatActivityDateTime(value) {
    if (!value) return "—";

    const parsed = new Date(value);

    if (Number.isNaN(parsed.getTime())) {
        return String(value);
    }

    const options = {
        month: "numeric",
        day: "numeric",
        year: "2-digit",
        hour: "numeric",
        minute: "2-digit",
    };

    if (window.MEDIA_CATALOG_TIMEZONE) {
        options.timeZone = window.MEDIA_CATALOG_TIMEZONE;
        options.timeZoneName = "short";
    }

    try {
        return parsed.toLocaleString(
            undefined,
            options
        );
    } catch {
        delete options.timeZone;
        delete options.timeZoneName;

        return parsed.toLocaleString(
            undefined,
            options
        );
    }
}


function hydrateActivityTimes(root = document) {
    root
        .querySelectorAll(".activity-time[data-utc]")
        .forEach(element => {
            const value = element.dataset.utc;

            element.textContent =
                formatActivityDateTime(value);

            if (value) {
                element.setAttribute(
                    "datetime",
                    value
                );

                element.title = value;
            }
        });
}

function initManagedDeviceTotals() {
    addManagedDeviceTotalBadges();
}


function addManagedDeviceTotalBadges() {
    const myCartsActions = document.querySelector(
        '[data-panel="cart-management"] > .media-panel:first-child .media-section-head .media-section-actions'
    );

    if (myCartsActions && !$("myManagedDeviceTotal")) {
        const badge = document.createElement("div");

        badge.id = "myManagedDeviceTotal";
        badge.className = "managed-device-summary";
        badge.innerHTML = `
            <span>Total Devices Managed</span>
            <strong aria-live="polite">—</strong>
        `;

        myCartsActions.prepend(badge);
    }

    const ownershipActions = document.querySelector(
        '[data-panel="ownership-management"] > .media-panel .media-section-head .media-section-actions'
    );

    if (ownershipActions && !$("allManagedDeviceTotal")) {
        const badge = document.createElement("div");

        badge.id = "allManagedDeviceTotal";
        badge.className = "managed-device-summary";
        badge.innerHTML = `
            <span>Total Devices Managed</span>
            <strong aria-live="polite">—</strong>
        `;

        ownershipActions.prepend(badge);
    }
}


function setManagedDeviceSummaryValue(elementId, value) {
    const element = $(elementId);
    const valueElement = element?.querySelector("strong");

    if (!valueElement) return;

    valueElement.textContent = String(value);
}
