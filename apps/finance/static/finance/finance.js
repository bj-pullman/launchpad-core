document.addEventListener("DOMContentLoaded", function () {
  initFinanceUI();

  initFinanceBulkSelection({
    selectAllId: "finance-records-select-all",
    rowSelector: ".finance-records-row-select",
    bulkBarId: "finance-records-bulk-bar",
    countId: "finance-records-bulk-count",
    hiddenInputIds: [
      "finance-records-bulk-archive-ids",
      "finance-records-bulk-delete-ids",
      "finance-records-bulk-restore-ids",
    ],
  });

  initFinanceBulkSelection({
    selectAllId: "finance-vendors-select-all",
    rowSelector: ".finance-vendors-row-select",
    bulkBarId: "finance-vendors-bulk-bar",
    countId: "finance-vendors-bulk-count",
    hiddenInputIds: [
      "finance-vendors-bulk-archive-ids",
      "finance-vendors-bulk-delete-ids",
      "finance-vendors-bulk-restore-ids",
    ],
  });
});

function initFinanceUI() {
  initVendorFormToggle();
  initClickableRows();
  initStatusChip();
  initConfirmModals();
  initFileUploadLabel();
  initTermCalculation();
  initFinanceBudgetChart();
  initFinanceTransactionBulkSelection();
  initFinanceSettingsModal();
  initializeFinanceImportTypeHelp();
}

function initVendorFormToggle() {
  const toggleBtn = document.getElementById("vendor-form-toggle");
  const cancelBtn = document.getElementById("vendor-form-cancel");
  const panel = document.getElementById("vendor-form-panel");

  if (toggleBtn && panel) {
    toggleBtn.addEventListener("click", function () {
      panel.hidden = false;
      toggleBtn.hidden = true;
      toggleBtn.setAttribute("aria-expanded", "true");

      const firstInput = panel.querySelector("input, textarea, select");
      if (firstInput) {
        firstInput.focus();
      }
    });
  }

  if (cancelBtn && panel && toggleBtn) {
    cancelBtn.addEventListener("click", function () {
      panel.hidden = true;
      toggleBtn.hidden = false;
      toggleBtn.setAttribute("aria-expanded", "false");
    });
  }
}

function initClickableRows() {
  const rows = document.querySelectorAll(".finance-row-link");

  rows.forEach(function (row) {
    row.addEventListener("click", function () {
      const href = row.dataset.href;
      if (href) {
        window.location.href = href;
      }
    });
  });
}

function initStatusChip() {
  const statusSelect = document.getElementById("status");
  const statusChip = document.getElementById("finance-status-chip");

  if (!statusSelect || !statusChip) return;

  function applyStatusChip() {
    const value = statusSelect.value || "";
    const label = statusSelect.options[statusSelect.selectedIndex]?.text || "Status";

    statusChip.textContent = label;
    statusChip.setAttribute("data-status", value);
  }

  statusSelect.addEventListener("change", applyStatusChip);
  applyStatusChip();
}

function initConfirmModals() {
  const modal = document.getElementById("confirm-modal");
  if (!modal) return;

  const messageEl = document.getElementById("confirm-modal-message");
  const confirmBtn = document.getElementById("confirm-modal-confirm");
  const cancelEls = modal.querySelectorAll("[data-confirm-close]");

  let currentForm = null;

  document.querySelectorAll("[data-confirm]").forEach((form) => {
    form.addEventListener("submit", function (e) {
      e.preventDefault();

      currentForm = form;

      const message = form.getAttribute("data-confirm") || "Are you sure?";
      const action = form.getAttribute("data-confirm-action") || "confirm";

      messageEl.textContent = message;

      if (action === "delete") {
        confirmBtn.textContent = "Delete";
        confirmBtn.classList.add("btn-danger");
        confirmBtn.classList.remove("btn-success");
      } else {
        confirmBtn.textContent = "Confirm";
        confirmBtn.classList.remove("btn-danger");
        confirmBtn.classList.add("btn-success");
      }

      modal.hidden = false;
    });
  });

  confirmBtn.addEventListener("click", function () {
    if (currentForm) {
      currentForm.submit();
    }
    modal.hidden = true;
  });

  cancelEls.forEach((el) => {
    el.addEventListener("click", function () {
      modal.hidden = true;
      currentForm = null;
    });
  });
}

function initFileUploadLabel() {
  const input =
    document.getElementById("attachment_files") ||
    document.getElementById("attachment_file") ||
    document.getElementById("import_file");

  const label = document.getElementById("finance-file-name");

  if (!input || !label) return;

  input.addEventListener("change", function () {
    if (input.files && input.files.length > 1) {
      label.textContent = `${input.files.length} files selected`;
    } else if (input.files && input.files.length === 1) {
      label.textContent = input.files[0].name;
    } else {
      label.textContent = "No file selected";
    }
  });
}

function initTermCalculation() {
  const purchaseDate = document.getElementById("purchase_date");
  const startSource = document.getElementById("use_purchase_date_as_start");
  const serviceStartDate = document.getElementById("service_start_date");
  const serviceStartWrap = document.getElementById("service_start_date_wrap");
  const termLength = document.getElementById("term_length");
  const termUnit = document.getElementById("term_unit");
  const expirationDate = document.getElementById("expiration_date");
  const renewalDate = document.getElementById("renewal_date");

  if (
    !purchaseDate ||
    !startSource ||
    !serviceStartDate ||
    !termLength ||
    !termUnit ||
    !expirationDate ||
    !renewalDate
  ) {
    return;
  }

  let renewalManuallyEdited = false;

  renewalDate.addEventListener("input", function () {
    renewalManuallyEdited = true;
  });

  function toggleStartDateVisibility() {
    const usePurchaseDate = startSource.value === "1";
    if (serviceStartWrap) {
      serviceStartWrap.style.display = usePurchaseDate ? "none" : "";
    }
  }

  function addMonths(date, months) {
    const d = new Date(date.getTime());
    const day = d.getDate();

    d.setMonth(d.getMonth() + months);

    if (d.getDate() < day) {
      d.setDate(0);
    }

    d.setDate(d.getDate() - 1);
    return d;
  }

  function addYears(date, years) {
    const d = new Date(date.getTime());
    d.setFullYear(d.getFullYear() + years);
    d.setDate(d.getDate() - 1);
    return d;
  }

  function toIsoDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function calculateDates() {
    const usePurchaseDate = startSource.value === "1";
    const startValue = usePurchaseDate ? purchaseDate.value : serviceStartDate.value;
    const lengthValue = parseInt(termLength.value || "", 10);
    const unitValue = termUnit.value;

    if (!startValue || !lengthValue || !unitValue) {
      return;
    }

    const start = new Date(`${startValue}T00:00:00`);
    if (Number.isNaN(start.getTime())) {
      return;
    }

    let expiration;
    if (unitValue === "months") {
      expiration = addMonths(start, lengthValue);
    } else if (unitValue === "years") {
      expiration = addYears(start, lengthValue);
    } else {
      return;
    }

    const expirationIso = toIsoDate(expiration);
    expirationDate.value = expirationIso;

    if (!renewalManuallyEdited || !renewalDate.value) {
      renewalDate.value = expirationIso;
    }
  }

  toggleStartDateVisibility();

  startSource.addEventListener("change", function () {
    toggleStartDateVisibility();
    calculateDates();
  });

  purchaseDate.addEventListener("input", calculateDates);
  serviceStartDate.addEventListener("input", calculateDates);
  termLength.addEventListener("input", calculateDates);
  termUnit.addEventListener("change", calculateDates);
}

function initFinanceBulkSelection(config) {
  const selectAll = document.getElementById(config.selectAllId);
  const checkboxes = document.querySelectorAll(config.rowSelector);
  const bulkBar = document.getElementById(config.bulkBarId);
  const countText = document.getElementById(config.countId);

  if (!selectAll || !checkboxes.length || !bulkBar || !countText) return;

  function updateBulkBar() {
    const selected = Array.from(checkboxes).filter((cb) => cb.checked);
    const count = selected.length;

    bulkBar.style.display = count > 0 ? "flex" : "none";
    countText.textContent = `${count} selected`;

    const ids = selected.map((cb) => cb.value).join(",");

    config.hiddenInputIds.forEach((inputId) => {
      const input = document.getElementById(inputId);
      if (input) input.value = ids;
    });
  }

  selectAll.addEventListener("change", function () {
    checkboxes.forEach((cb) => {
      cb.checked = selectAll.checked;
    });
    updateBulkBar();
  });

  checkboxes.forEach((cb) => {
    cb.addEventListener("change", updateBulkBar);
    cb.addEventListener("click", function (e) {
      e.stopPropagation();
    });
  });
}

function initFinanceBudgetChart() {
  const dataEl = document.getElementById("finance-budget-dashboard-data");
  const dashboard = document.getElementById("finance-budget-chart-dashboard");
  const toggles = document.querySelectorAll("[data-budget-chart-toggle]");

  if (!dataEl || !dashboard || !window.ApexCharts) {
    return;
  }

  let chartData = {};

  try {
    chartData = JSON.parse(dataEl.textContent || "{}");
  } catch (error) {
    console.error("Failed to parse budget dashboard data.", error);
    return;
  }

  const chartLabels = {
    category: "Category",
    vendor: "Vendor",
    month: "Monthly Trend",
    record_type: "Record Type",
    status: "Status",
  };

  const chartInstances = {};
  const chartPalette = [
    "#2563eb",
    "#0f766e",
    "#7c3aed",
    "#ea580c",
    "#0891b2",
    "#16a34a",
    "#9333ea",
    "#dc2626",
    "#ca8a04",
    "#475569",
  ];

  function formatMoney(value) {
    return Number(value || 0).toLocaleString(undefined, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    });
  }

  function formatCompactMoney(value) {
    const amount = Number(value || 0);

    if (Math.abs(amount) >= 1000000) {
      return `$${(amount / 1000000).toFixed(1)}M`;
    }

    if (Math.abs(amount) >= 1000) {
      return `$${(amount / 1000).toFixed(0)}K`;
    }

    return `$${amount.toFixed(0)}`;
  }

  function getSelectedChartKeys() {
    return Array.from(toggles)
      .filter((toggle) => toggle.checked)
      .map((toggle) => toggle.value)
      .slice(0, 4);
  }

  function syncToggleLimit() {
    const selectedCount = Array.from(toggles).filter((toggle) => toggle.checked).length;

    toggles.forEach((toggle) => {
      toggle.disabled = !toggle.checked && selectedCount >= 4;
    });

    dashboard.dataset.chartCount = String(selectedCount);
  }

  function destroyCharts() {
    Object.keys(chartInstances).forEach((key) => {
      chartInstances[key].destroy();
      delete chartInstances[key];
    });
  }

  function topItems(item, limit = 10) {
    const labels = item.labels || [];
    const values = item.values || [];

    return labels
      .map((label, index) => ({
        label,
        rawValue: Number(values[index] || 0),
        value: Number(values[index] || 0),
      }))
      .sort((a, b) => b.value - a.value)
      .slice(0, limit);

      const maxValue = Math.max(...items.map((x) => x.value), 1);

      items.forEach((item) => {
        const ratio = item.value / maxValue;

        if (ratio < 0.12) {
          item.value = maxValue * 0.12;
        }
      });
  }

  function getChartOptions(key, item) {
    const isMonth = key === "month";
    const isDonut = key === "record_type" || key === "status";
    const items = isMonth
      ? (item.labels || []).map((label, index) => ({
          label,
          value: Number((item.values || [])[index] || 0),
        }))
      : topItems(item, 10);

    const labels = items.map((entry) => entry.label);
    const values = items.map((entry) => entry.value);

    if (isDonut) {
      return {
        colors: chartPalette,
        chart: {
          type: "donut",
          height: 300,
          toolbar: { show: false },
          fontFamily: "inherit",
          parentHeightOffset: 0,
        },
        labels,
        series: values,
        legend: {
          position: "bottom",
          fontSize: "13px",
        },
        dataLabels: {
          enabled: false,
        },
        tooltip: {
          y: {
            formatter: formatMoney,
          },
        },
        stroke: {
          width: 3,
          colors: ["#ffffff"],
        },
        plotOptions: {
          pie: {
            donut: {
              size: "72%",
              labels: {
                show: true,
                name: {
                  show: true,
                  fontSize: "13px",
                  color: "#64748b",
                },
                value: {
                  show: true,
                  fontSize: "18px",
                  fontWeight: 800,
                  color: "#0f172a",
                  formatter: formatMoney,
                },
                total: {
                  show: true,
                  label: "Total",
                  fontSize: "12px",
                  color: "#64748b",
                  formatter: function (w) {
                    const total = w.globals.seriesTotals.reduce((sum, value) => sum + value, 0);
                    return formatMoney(total);
                  },
                },
              },
            },
          },
        },
      };
    }

    if (isMonth) {
      return {
        colors: ["#2563eb"],
        chart: {
          type: "area",
          height: 260,
          toolbar: { show: false },
          fontFamily: "inherit",
        },
        series: [
          {
            name: "Spend",
            data: values,
          },
        ],
        xaxis: {
          categories: labels,
          labels: {
            rotate: -30,
          },
        },
        yaxis: {
          labels: {
            formatter: function (value) {
              return formatMoney(value);
            },
          },
        },
        dataLabels: {
          enabled: false,
        },
        stroke: {
          curve: "smooth",
          width: 3,
        },
        fill: {
          type: "gradient",
          gradient: {
            shadeIntensity: 1,
            opacityFrom: 0.35,
            opacityTo: 0.05,
            stops: [0, 90, 100],
          },
        },
        tooltip: {
          y: {
            formatter: function(value, opts) {
              const raw =
                items?.[opts?.dataPointIndex]?.rawValue ?? value;

              return formatMoney(raw);
            },
          },
        },
        grid: {
          borderColor: "rgba(148, 163, 184, 0.25)",
        },
      };
    }

    return {
      colors: chartPalette,
      chart: {
        type: "bar",
        height: Math.max(350, labels.length * 38),
        toolbar: { show: false },
        fontFamily: "inherit",
        parentHeightOffset: 18,
        redrawOnParentResize: true,
        redrawOnWindowResize: true,
      },
      series: [
        {
          name: "Spend",
          data: values,
        },
      ],
      plotOptions: {
        bar: {
          horizontal: true,
          distributed: key === "vendor" || key === "category",
          borderRadius: 6,
          barHeight: "52%",
          dataLabels: {
            position: "right",
          },
        },
      },
      xaxis: {
        categories: labels,
        tickAmount: 3,
        labels: {
          formatter: formatCompactMoney,
          style: {
            fontSize: "11px",
          },
        },
      },
      yaxis: {
        labels: {
          maxWidth: 150,
          style: {
            fontSize: "11px",
          },
        },
      },
      dataLabels: {
        enabled: false,
      },
      tooltip: {
        y: {
            formatter: function(value, opts) {
              const raw =
                items?.[opts?.dataPointIndex]?.rawValue ?? value;

              return formatMoney(raw);
            },
        },
      },
      grid: {
        borderColor: "rgba(148, 163, 184, 0.22)",
        padding: {
          top: 22,
          left: 8,
          right: 18,
        },
      },
      legend: {
        show: false,
      },
    };
  }

  function renderCharts() {
    destroyCharts();
    dashboard.innerHTML = "";

    const selectedKeys = getSelectedChartKeys();
    dashboard.dataset.chartCount = String(selectedKeys.length);

    if (!selectedKeys.length) {
      dashboard.innerHTML = `
        <div class="finance-empty">
          <h3>No charts selected</h3>
          <p>Select up to 4 budget charts to compare.</p>
        </div>
      `;
      syncToggleLimit();
      return;
    }

    selectedKeys.forEach((key) => {
      const item = chartData[key];

      if (!item || !Array.isArray(item.labels) || !Array.isArray(item.values)) {
        return;
      }

      const panel = document.createElement("div");
      panel.className = "finance-budget-chart-panel";
      panel.dataset.chartKey = key;

      const title = document.createElement("div");
      title.className = "finance-budget-chart-panel-title";
      title.textContent = chartLabels[key] || key;

      const chartTarget = document.createElement("div");
      chartTarget.className = "finance-budget-apex-chart";
      chartTarget.id = `finance-budget-chart-${key}`;

      panel.appendChild(title);
      panel.appendChild(chartTarget);
      dashboard.appendChild(panel);

      const chart = new ApexCharts(chartTarget, getChartOptions(key, item));
      chart.render();

      chartInstances[key] = chart;
    });

    syncToggleLimit();
  }

  toggles.forEach((toggle) => {
    toggle.addEventListener("change", renderCharts);
  });

  renderCharts();
}

function initFinanceTransactionBulkSelection() {
  initFinanceBulkSelection({
    selectAllId: "finance-transactions-select-all",
    rowSelector: ".finance-transactions-row-select",
    bulkBarId: "finance-transactions-bulk-bar",
    countId: "finance-transactions-bulk-count",
    hiddenInputIds: [
      "finance-transactions-bulk-promote-ids",
      "finance-transactions-bulk-ignore-ids",
      "finance-transactions-bulk-review-ids",
    ],
  });
}

function initFinanceSettingsModal() {
  const params = new URLSearchParams(window.location.search);
  const openModalId = params.get("open_modal");
  const openTab = params.get("open_tab");
  const openPanelId = params.get("open_panel");

  const fyStartDate = document.getElementById("fy_start_date");
  const fyEndDate = document.getElementById("fy_end_date");

  if (fyStartDate && fyEndDate) {
    fyStartDate.addEventListener("change", function () {
      if (!fyStartDate.value) {
        return;
      }

      const startDate = new Date(`${fyStartDate.value}T00:00:00`);

      if (Number.isNaN(startDate.getTime())) {
        return;
      }

      const endDate = new Date(startDate.getTime());
      endDate.setFullYear(endDate.getFullYear() + 1);
      endDate.setDate(endDate.getDate() - 1);

      const year = endDate.getFullYear();
      const month = String(endDate.getMonth() + 1).padStart(2, "0");
      const day = String(endDate.getDate()).padStart(2, "0");

      fyEndDate.value = `${year}-${month}-${day}`;
    });
  }

  if (openModalId) {
    const modal = document.getElementById(openModalId);

    if (modal) {
      modal.hidden = false;
      document.body.classList.add("finance-modal-open");

      if (openTab) {
        modal
          .querySelectorAll("[data-finance-settings-tab]")
          .forEach((button) => button.classList.remove("active"));

        modal
          .querySelectorAll("[data-finance-settings-panel]")
          .forEach((panel) => panel.classList.remove("active"));

        const tabButton = modal.querySelector(
          `[data-finance-settings-tab="${openTab}"]`
        );

        const tabPanel = modal.querySelector(
          `[data-finance-settings-panel="${openTab}"]`
        );

        if (tabButton) tabButton.classList.add("active");
        if (tabPanel) tabPanel.classList.add("active");
      }

      if (openPanelId) {
        const checklistPanel = document.getElementById(openPanelId);

        if (checklistPanel) {
          checklistPanel.hidden = false;
        }
      }
    }
  }

  document.addEventListener("click", function (event) {
    const openButton = event.target.closest("[data-finance-modal-open]");

    if (openButton) {
      const modalId = openButton.getAttribute("data-finance-modal-open");
      const modal = document.getElementById(modalId);

      if (modal) {
        modal.hidden = false;
        document.body.classList.add("finance-modal-open");
      }

      return;
    }

    const closeButton = event.target.closest("[data-finance-modal-close]");

    if (closeButton) {
      const modal = closeButton.closest(".finance-modal-backdrop");

      if (modal) {
        modal.hidden = true;
        document.body.classList.remove("finance-modal-open");
      }

      return;
    }

    if (event.target.classList.contains("finance-modal-backdrop")) {
      event.target.hidden = true;
      document.body.classList.remove("finance-modal-open");
      return;
    }

    const tabButton = event.target.closest("[data-finance-settings-tab]");

    if (tabButton) {
      const modal = tabButton.closest(".finance-modal");
      const tabName = tabButton.getAttribute("data-finance-settings-tab");

      modal
        .querySelectorAll("[data-finance-settings-tab]")
        .forEach((button) => button.classList.remove("active"));

      modal
        .querySelectorAll("[data-finance-settings-panel]")
        .forEach((panel) => panel.classList.remove("active"));

      tabButton.classList.add("active");

      const panel = modal.querySelector(
        `[data-finance-settings-panel="${tabName}"]`
      );

      if (panel) {
        panel.classList.add("active");
      }

      return;
    }

    const checklistOpenButton = event.target.closest("[data-finance-checklist-open]");

    if (checklistOpenButton) {
      const panelId = checklistOpenButton.getAttribute("data-finance-checklist-open");
      const panel = document.getElementById(panelId);

      if (panel) {
        panel.hidden = !panel.hidden;

        if (!panel.hidden) {
          setTimeout(function () {
            panel.scrollIntoView({
              behavior: "smooth",
              block: "start",
            });
          }, 100);
        }
      }

      return;
    }

    const checklistCloseButton = event.target.closest("[data-finance-checklist-close]");

    if (checklistCloseButton) {
      const panel = checklistCloseButton.closest(".finance-checklist-panel");

      if (panel) {
        panel.hidden = true;
      }

      return;
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") {
      return;
    }

    document
      .querySelectorAll(".finance-modal-backdrop:not([hidden])")
      .forEach((modal) => {
        modal.hidden = true;
      });

    document.body.classList.remove("finance-modal-open");
  });
}

function initializeFinanceImportTypeHelp() {
  const select = document.querySelector("[data-import-type-select]");
  const cards = document.querySelectorAll("[data-import-help-card]");

  if (!select) {
    return;
  }

  function updateImportHelp() {
    const selectedType = select.value || "";

    cards.forEach((card) => {
      const cardType = card.getAttribute("data-import-help-card");
      const isActive = selectedType && cardType === selectedType;

      card.classList.toggle("is-active", Boolean(isActive));
      card.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function chooseImportType(card) {
    const cardType = card.getAttribute("data-import-help-card");

    if (!cardType) {
      return;
    }

    select.value = cardType;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    updateImportHelp();
  }

  cards.forEach((card) => {
    card.addEventListener("click", function () {
      chooseImportType(card);
    });

    card.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }

      event.preventDefault();
      chooseImportType(card);
    });
  });

  select.addEventListener("change", updateImportHelp);

  updateImportHelp();
}