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