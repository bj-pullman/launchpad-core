document.addEventListener("DOMContentLoaded", initSettingsScripts);

function initSettingsScripts() {
  initSnipeOpsConnectionTest();
  initUserFormPasswordToggle();
  initSettingsTabs();
  initAuthenticationConnectionTests();
  initKioskTokenButtons();
  initBoardTokenButtons();
  initDeleteConfirmations();
  initSettingsProviderToggles();
  initSettingsFileUploads();
  initFinanceNotificationLogoPreviewName();
  initUsersPage();
  initDepartmentPills();

  if (typeof initFinanceNotificationTemplateBuilder === "function") {
    initFinanceNotificationTemplateBuilder();
  }

  initApiKeyCreatedModal();
}

function initSnipeOpsConnectionTest() {
  const form = document.getElementById("snipeops-settings-form");
  const testButton = document.getElementById("snipeops-test-btn");
  const resultBox = document.getElementById("snipeops-test-result");

  if (!form || !testButton || !resultBox) {
    return;
  }

  function showResult(message, ok) {
    resultBox.hidden = false;
    resultBox.textContent = message;
    resultBox.className = ok
      ? "settings-test-result settings-test-result-success"
      : "settings-test-result settings-test-result-error";
  }

  testButton.addEventListener("click", async function () {
    const formData = new FormData(form);

    testButton.disabled = true;
    showResult("Testing connection...", true);

    try {
      const response = await fetch("/settings/snipeops/test-connection", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      showResult(data.message || "Connection test completed.", !!data.ok);
    } catch (error) {
      showResult(
        "Connection test failed due to a network or server error.",
        false
      );
    } finally {
      testButton.disabled = false;
    }
  });
}

function initUserFormPasswordToggle() {
  const form = document.getElementById("user-form");
  const accountType = document.getElementById("account_type");
  const passwordField = document.getElementById("password-field");
  const passwordInput = document.getElementById("password");

  if (!form || !accountType || !passwordInput) {
    return;
  }

  const isNewForm = form.dataset.formMode === "new";

  function syncPasswordField() {
    const isSSO = accountType.value === "sso";

    if (isSSO) {
      passwordInput.value = "";
      passwordInput.placeholder = "Not required for SSO-only accounts";

      if (isNewForm && passwordField) {
        passwordField.style.display = "none";
      }
    } else {
      if (isNewForm) {
        passwordInput.placeholder = "Required for local accounts only";

        if (passwordField) {
          passwordField.style.display = "";
        }
      } else {
        passwordInput.placeholder = "Leave blank to keep current password";

        if (passwordField) {
          passwordField.style.display = "";
        }
      }
    }
  }

  accountType.addEventListener("change", syncPasswordField);
  syncPasswordField();
}

function initSettingsTabs() {
  const tabs = document.querySelectorAll(".settings-tab");
  const panels = document.querySelectorAll(".settings-tab-panel[data-panel]");
  const savePanels = document.querySelectorAll(".settings-tab-panel[data-panel-save]");
  const financeTabInput = document.getElementById("active_finance_tab");

  if (!tabs.length) {
    return;
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", function () {
      const targetPanel = tab.dataset.tab;

      tabs.forEach((t) => t.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));
      savePanels.forEach((p) => p.classList.remove("active"));

      tab.classList.add("active");

      const panel = document.querySelector(`.settings-tab-panel[data-panel="${targetPanel}"]`);
      if (panel) {
        panel.classList.add("active");
      }

      const savePanel = document.querySelector(`.settings-tab-panel[data-panel-save="${targetPanel}"]`);
      if (savePanel) {
        savePanel.classList.add("active");
      }

      if (financeTabInput) {
        financeTabInput.value = targetPanel;
      }
    });
  });
}

function initAuthenticationConnectionTests() {
  const form = document.getElementById("authentication-settings-form");
  const buttons = document.querySelectorAll(".test-connection-btn");

  if (!form || !buttons.length) {
    return;
  }

  buttons.forEach((button) => {
    button.addEventListener("click", async function () {
      const provider = button.dataset.provider;
      const testUrl = button.dataset.testUrl;
      const resultBox = document.querySelector(
        `[data-provider-result="${provider}"]`
      );

      if (!provider || !testUrl || !resultBox) {
        return;
      }

      const formData = new FormData(form);
      formData.set("provider", provider);

      button.disabled = true;
      resultBox.hidden = false;
      resultBox.textContent = "Testing configuration...";
      resultBox.className = "settings-test-result";

      try {
        const response = await fetch(testUrl, {
          method: "POST",
          body: formData,
        });

        const data = await response.json();

        resultBox.textContent =
          data.message || "Configuration test completed.";

        if (data.ok) {
          resultBox.className =
            "settings-test-result settings-test-result-success";
        } else {
          resultBox.className =
            "settings-test-result settings-test-result-error";
        }
      } catch (error) {
        resultBox.textContent =
          "Configuration test failed due to a network or server error.";
        resultBox.className =
          "settings-test-result settings-test-result-error";
      } finally {
        button.disabled = false;
      }
    });
  });
}

function initKioskTokenButtons() {
  const rotateButtons = document.querySelectorAll(".rotate-kiosk-token-btn");

  if (!rotateButtons.length) {
    return;
  }

  rotateButtons.forEach((button) => {
    button.addEventListener("click", async function () {
      const rotateUrl = button.dataset.rotateUrl;
      const department = button.dataset.department;
      const resultBox = document.querySelector(
        `[data-kiosk-result="${department}"]`
      );
      const urlInput = document.querySelector(
        `[data-kiosk-url-input="${department}"]`
      );

      button.disabled = true;
      const originalText = button.textContent;
      button.textContent = "Working...";

      try {
        const response = await fetch(rotateUrl, {
          method: "POST",
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
        });

        const payload = await response.json();

        if (resultBox) {
          resultBox.hidden = false;
        }

        if (response.ok && payload.ok) {
          if (urlInput) {
            urlInput.value = payload.kiosk_url;
          }
          if (resultBox) {
            resultBox.className =
              "settings-test-result settings-test-result-success";
            resultBox.textContent =
              `Kiosk URL updated for ${payload.department_name}.`;
          }
          button.textContent = "Regenerate Kiosk URL";
        } else {
          if (resultBox) {
            resultBox.className =
              "settings-test-result settings-test-result-error";
            resultBox.textContent =
              payload.message || "Unable to rotate kiosk URL.";
          }
          button.textContent = originalText;
        }
      } catch (error) {
        if (resultBox) {
          resultBox.hidden = false;
          resultBox.className =
            "settings-test-result settings-test-result-error";
          resultBox.textContent = "Unable to rotate kiosk URL.";
        }
        button.textContent = originalText;
      } finally {
        button.disabled = false;
      }
    });
  });
}

function initBoardTokenButtons() {
  const rotateButtons = document.querySelectorAll(".rotate-board-token-btn");

  if (!rotateButtons.length) {
    return;
  }

  rotateButtons.forEach((button) => {
    button.addEventListener("click", async function () {
      const rotateUrl = button.dataset.rotateUrl;
      const department = button.dataset.department;
      const resultBox = document.querySelector(
        `[data-board-result="${department}"]`
      );
      const urlInput = document.querySelector(
        `[data-board-url-input="${department}"]`
      );

      button.disabled = true;
      const originalText = button.textContent;
      button.textContent = "Working...";

      try {
        const response = await fetch(rotateUrl, {
          method: "POST",
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
        });

        const payload = await response.json();

        if (resultBox) {
          resultBox.hidden = false;
        }

        if (response.ok && payload.ok) {
          if (urlInput) {
            urlInput.value = payload.board_url;
          }
          if (resultBox) {
            resultBox.className =
              "settings-test-result settings-test-result-success";
            resultBox.textContent =
              `Board URL updated for ${payload.department_name}.`;
          }
          button.textContent = "Regenerate Board URL";
        } else {
          if (resultBox) {
            resultBox.className =
              "settings-test-result settings-test-result-error";
            resultBox.textContent =
              payload.message || "Unable to rotate board URL.";
          }
          button.textContent = originalText;
        }
      } catch (error) {
        if (resultBox) {
          resultBox.hidden = false;
          resultBox.className =
            "settings-test-result settings-test-result-error";
          resultBox.textContent = "Unable to rotate board URL.";
        }
        button.textContent = originalText;
      } finally {
        button.disabled = false;
      }
    });
  });
}

function initDeleteConfirmations() {
  const modal = document.getElementById("confirm-modal");
  const titleEl = document.getElementById("confirm-modal-title");
  const messageEl = document.getElementById("confirm-modal-message");
  const confirmBtn = document.getElementById("confirm-modal-confirm");
  const closeEls = document.querySelectorAll("[data-confirm-close]");
  const deleteForms = document.querySelectorAll(".inline-delete-form");

  if (!modal || !titleEl || !messageEl || !confirmBtn || !deleteForms.length) {
    return;
  }

  let pendingForm = null;
  let lastFocusedElement = null;

  function openModal(form) {
    pendingForm = form;
    lastFocusedElement = document.activeElement;

    titleEl.textContent = form.dataset.confirmTitle || "Confirm Action";
    messageEl.textContent =
      form.dataset.confirmMessage || "Are you sure you want to continue?";
    confirmBtn.textContent = form.dataset.confirmButtonLabel || "Confirm";

    modal.hidden = false;
    document.body.classList.add("confirm-modal-open");
    confirmBtn.focus();
  }

  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("confirm-modal-open");
    pendingForm = null;

    if (lastFocusedElement && typeof lastFocusedElement.focus === "function") {
      lastFocusedElement.focus();
    }
  }

  deleteForms.forEach((form) => {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      openModal(form);
    });
  });

  closeEls.forEach((el) => {
    el.addEventListener("click", closeModal);
  });

  confirmBtn.addEventListener("click", function () {
    if (!pendingForm) {
      closeModal();
      return;
    }

    const formToSubmit = pendingForm;
    pendingForm = null;

    formToSubmit.submit();
  });

  document.addEventListener("keydown", function (event) {
    if (modal.hidden) {
      return;
    }

    if (event.key === "Escape") {
      closeModal();
    }
  });
}

function initSettingsProviderToggles() {
  document.querySelectorAll(".settings-provider-card").forEach((card) => {
    const toggle = card.querySelector(".settings-toggle-row input[type='checkbox']");
    const toggleRow = card.querySelector(".settings-toggle-row");

    if (!toggle) {
      return;
    }

    const inputs = card.querySelectorAll(
      "input:not([type=checkbox]), select, textarea, button.test-connection-btn"
    );

    const applyState = () => {
      const enabled = toggle.checked;

      if (enabled) {
        card.classList.remove("settings-card-disabled");
        if (toggleRow) {
          toggleRow.classList.remove("settings-toggle-off");
        }
      } else {
        card.classList.add("settings-card-disabled");
        if (toggleRow) {
          toggleRow.classList.add("settings-toggle-off");
        }
      }

      inputs.forEach((el) => {
        if (enabled) {
          el.removeAttribute("disabled");
          el.classList.remove("settings-disabled");
        } else {
          el.setAttribute("disabled", "disabled");
          el.classList.add("settings-disabled");
        }
      });
    };

    toggle.addEventListener("change", applyState);
    applyState();
  });
}

function initSettingsFileUploads() {
  const fileInputs = document.querySelectorAll(".settings-file-input");

  fileInputs.forEach((input) => {
    const label = document.querySelector(`label[for="${input.id}"]`);
    if (!label) {
      return;
    }

    const textEl = label.querySelector(".settings-file-upload-text");
    if (!textEl) {
      return;
    }

    const defaultText = textEl.textContent;

    input.addEventListener("change", () => {
      if (input.files && input.files.length > 0) {
        textEl.textContent = input.files[0].name;
        label.classList.add("settings-file-upload-selected");
      } else {
        textEl.textContent = defaultText;
        label.classList.remove("settings-file-upload-selected");
      }
    });
  });
}

function initFinanceNotificationLogoPreviewName() {
  const input = document.getElementById("notification_logo");
  const textEl = document.getElementById("notification-logo-file-text");

  if (!input || !textEl) {
    return;
  }

  const defaultText = textEl.dataset.defaultText || textEl.textContent;

  input.addEventListener("change", () => {
    if (input.files && input.files.length > 0) {
      textEl.textContent = input.files[0].name;
    } else {
      textEl.textContent = defaultText;
    }
  });
}

function initApiKeyCreatedModal() {
  const modal = document.getElementById("api-key-modal");
  const input = document.getElementById("generated-api-key");
  const copyBtn = document.getElementById("copy-api-key-btn");
  const closeBtn = document.getElementById("close-api-key-modal-btn");

  if (!modal || !input || !copyBtn || !closeBtn) {
    return;
  }

  copyBtn.addEventListener("click", async function () {
    try {
      await navigator.clipboard.writeText(input.value);
      copyBtn.textContent = "Copied";
    } catch (error) {
      input.select();
      document.execCommand("copy");
      copyBtn.textContent = "Copied";
    }
  });

  closeBtn.addEventListener("click", function () {
    modal.remove();
  });
}

function initUsersPage() {
  const table = document.getElementById("users-table");
  if (!table) return;

  const searchInput = document.getElementById("users-search");
  const statusFilter = document.getElementById("users-status-filter");
  const accountFilter = document.getElementById("users-account-filter");
  const departmentFilter = document.getElementById("users-department-filter");
  const visibleCount = document.getElementById("users-visible-count");
  const selectAll = document.getElementById("users-select-all");
  const bulkActions = document.getElementById("users-bulk-actions");
  const bulkAction = document.getElementById("users-bulk-action");
  const bulkApply = document.getElementById("users-bulk-apply");

  const modal = document.getElementById("users-bulk-modal");
  const modalTitle = document.getElementById("users-bulk-modal-title");
  const modalMessage = document.getElementById("users-bulk-modal-message");
  const modalList = document.getElementById("users-bulk-modal-list");
  const modalConfirm = document.getElementById("users-bulk-modal-confirm");
  const modalCancelButtons = document.querySelectorAll("[data-users-bulk-cancel]");

  const rows = Array.from(table.querySelectorAll("tbody tr.users-table-row"));
  let pendingBulkAction = null;
  let pendingSelectedCheckboxes = [];

  function applyFilters() {
    const query = (searchInput?.value || "").trim().toLowerCase();
    const status = statusFilter?.value || "";
    const accountType = accountFilter?.value || "";
    const department = departmentFilter?.value || "";

    const filterPanel = document.getElementById("users-filter-panel");
    const filterToggleBtn = document.getElementById("users-filter-toggle");

    if (filterPanel && (query || status || accountType || department)) {
      filterPanel.hidden = false;

      if (filterToggleBtn) {
        filterToggleBtn.setAttribute("aria-expanded", "true");
      }
    }

    let shown = 0;

    rows.forEach((row) => {
      const rowText = row.dataset.searchText || "";
      const rowStatus = row.dataset.status || "";
      const rowAccountType = row.dataset.accountType || "";
      const rowDepartment = row.dataset.department || "";

      const matchesSearch = !query || rowText.includes(query);
      const matchesStatus = !status || rowStatus === status;
      const matchesAccount = !accountType || rowAccountType === accountType;
      const matchesDepartment = !department || rowDepartment === department;

      const shouldShow = matchesSearch && matchesStatus && matchesAccount && matchesDepartment;

      row.classList.toggle("users-hidden-by-filter", !shouldShow);

      if (shouldShow) {
        shown += 1;
      } else {
        const checkbox = row.querySelector(".users-row-checkbox");
        if (checkbox) checkbox.checked = false;
      }
    });

    if (visibleCount) {
      visibleCount.textContent = String(shown);
    }

    syncBulkUi();
  }

  function getVisibleCheckboxes() {
    return rows
      .filter((row) => !row.classList.contains("users-hidden-by-filter"))
      .map((row) => row.querySelector(".users-row-checkbox"))
      .filter(Boolean);
  }

  function getSelectedCheckboxes() {
    return getVisibleCheckboxes().filter((checkbox) => checkbox.checked);
  }

  function syncBulkUi() {
    const visibleCheckboxes = getVisibleCheckboxes();
    const selectedCheckboxes = getSelectedCheckboxes();

    if (selectAll) {
      selectAll.checked =
        visibleCheckboxes.length > 0 &&
        selectedCheckboxes.length === visibleCheckboxes.length;

      selectAll.indeterminate =
        selectedCheckboxes.length > 0 &&
        selectedCheckboxes.length < visibleCheckboxes.length;
    }

    if (bulkActions) {
      bulkActions.hidden = selectedCheckboxes.length === 0;
    }

    if (bulkApply) {
      bulkApply.disabled = selectedCheckboxes.length === 0;
    }

    if (selectedCheckboxes.length === 0 && bulkAction) {
      bulkAction.value = "";
    }
  }

  function openBulkModal(action, selectedCheckboxes) {
    if (!modal || !modalTitle || !modalMessage || !modalList || !modalConfirm) {
      return;
    }

    pendingBulkAction = action;
    pendingSelectedCheckboxes = selectedCheckboxes;

    const count = selectedCheckboxes.length;
    const names = selectedCheckboxes
      .map((checkbox) => checkbox.dataset.username || `User ${checkbox.value}`)
      .slice(0, 10);

    const extraCount = Math.max(0, count - names.length);

    if (action === "activate") {
      modalTitle.textContent = "Activate Selected Users";
      modalMessage.textContent =
        `This will activate ${count} selected user account(s). They will be allowed to sign in again if their authentication method is valid.`;
      modalConfirm.textContent = "Activate Users";
      modalConfirm.className = "btn btn-primary";
    } else if (action === "disable") {
      modalTitle.textContent = "Disable Selected Users";
      modalMessage.textContent =
        `This will disable ${count} selected user account(s). They will no longer be able to sign in.`;
      modalConfirm.textContent = "Disable Users";
      modalConfirm.className = "btn btn-danger";
    } else if (action === "delete") {
      modalTitle.textContent = "Delete Selected Users";
      modalMessage.textContent =
        `This will delete ${count} selected user account(s). This removes the user record, local auth account, and role assignments.`;
      modalConfirm.textContent = "Delete Users";
      modalConfirm.className = "btn btn-danger";
    } else {
      return;
    }

    modalList.innerHTML = "";

    names.forEach((name) => {
      const item = document.createElement("div");
      item.className = "users-bulk-modal-list-item";
      item.textContent = name;
      modalList.appendChild(item);
    });

    if (extraCount > 0) {
      const item = document.createElement("div");
      item.className = "users-bulk-modal-list-item users-bulk-modal-list-more";
      item.textContent = `+${extraCount} more`;
      modalList.appendChild(item);
    }

    modal.hidden = false;
    document.body.classList.add("users-bulk-modal-open");
    modalConfirm.focus();
  }

  function closeBulkModal() {
    if (!modal) return;

    modal.hidden = true;
    document.body.classList.remove("users-bulk-modal-open");

    pendingBulkAction = null;
    pendingSelectedCheckboxes = [];
  }

  async function runBulkStatusUpdate(action, selectedCheckboxes) {
    const bulkActionUrl = bulkActions?.dataset.bulkActionUrl;
    if (!bulkActionUrl) {
      alert("Bulk update URL is missing.");
      return;
    }

    const userIds = selectedCheckboxes.map((checkbox) => checkbox.value);

    const response = await fetch(bulkActionUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify({
        action: action,
        user_ids: userIds
      })
    });

    const payload = await response.json();

    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || "Unable to update selected users.");
    }
  }

  async function runBulkDelete(selectedCheckboxes) {
    for (const checkbox of selectedCheckboxes) {
      const deleteUrl = checkbox.dataset.deleteUrl;
      if (!deleteUrl) continue;

      const response = await fetch(deleteUrl, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest"
        }
      });

      if (!response.ok) {
        throw new Error(`Unable to delete ${checkbox.dataset.username || checkbox.value}.`);
      }
    }
  }

  rows.forEach((row) => {
    row.addEventListener("click", function (event) {
      const interactiveElement = event.target.closest(
        "a, button, input, select, textarea, label, form"
      );

      if (interactiveElement) return;

      const editUrl = row.dataset.editUrl;
      if (editUrl) {
        window.location.href = editUrl;
      }
    });

    const checkbox = row.querySelector(".users-row-checkbox");
    if (checkbox) {
      checkbox.addEventListener("click", function (event) {
        event.stopPropagation();
      });

      checkbox.addEventListener("change", syncBulkUi);
    }
  });

  if (searchInput) searchInput.addEventListener("input", applyFilters);
  if (statusFilter) statusFilter.addEventListener("change", applyFilters);
  if (accountFilter) accountFilter.addEventListener("change", applyFilters);
  if (departmentFilter) departmentFilter.addEventListener("change", applyFilters);

  if (selectAll) {
    selectAll.addEventListener("change", function () {
      getVisibleCheckboxes().forEach((checkbox) => {
        checkbox.checked = selectAll.checked;
      });

      syncBulkUi();
    });
  }

  if (bulkApply) {
    bulkApply.addEventListener("click", function () {
      const action = bulkAction?.value || "";
      const selected = getSelectedCheckboxes();

      if (!selected.length) {
        alert("Select at least one user.");
        return;
      }

      if (!action) {
        alert("Choose a bulk action first.");
        return;
      }

      openBulkModal(action, selected);
    });
  }

  modalCancelButtons.forEach((button) => {
    button.addEventListener("click", closeBulkModal);
  });

  if (modalConfirm) {
    modalConfirm.addEventListener("click", async function () {
      if (!pendingBulkAction || !pendingSelectedCheckboxes.length) {
        closeBulkModal();
        return;
      }

      modalConfirm.disabled = true;
      const originalText = modalConfirm.textContent;
      modalConfirm.textContent = "Working...";

      try {
        if (pendingBulkAction === "activate" || pendingBulkAction === "disable") {
          await runBulkStatusUpdate(pendingBulkAction, pendingSelectedCheckboxes);
        } else if (pendingBulkAction === "delete") {
          await runBulkDelete(pendingSelectedCheckboxes);
        }

        window.location.reload();
      } catch (error) {
        alert(error.message || "Bulk update failed.");
        modalConfirm.disabled = false;
        modalConfirm.textContent = originalText;
      }
    });
  }

  document.addEventListener("keydown", function (event) {
    if (!modal || modal.hidden) return;

    if (event.key === "Escape") {
      closeBulkModal();
    }
  });

  applyFilters();
}

function initDepartmentPills() {
  const pills = document.querySelectorAll("[data-department-pill]");
  if (!pills.length) return;

  const palette = [
    { bg: "#eff6ff", text: "#1d4ed8", border: "#bfdbfe" },
    { bg: "#ecfdf5", text: "#047857", border: "#bbf7d0" },
    { bg: "#fefce8", text: "#a16207", border: "#fde68a" },
    { bg: "#fdf2f8", text: "#be185d", border: "#fbcfe8" },
    { bg: "#f5f3ff", text: "#6d28d9", border: "#ddd6fe" },
    { bg: "#fff7ed", text: "#c2410c", border: "#fed7aa" },
    { bg: "#f0fdfa", text: "#0f766e", border: "#99f6e4" },
    { bg: "#f8fafc", text: "#334155", border: "#cbd5e1" },
    { bg: "#eef2ff", text: "#4338ca", border: "#c7d2fe" },
    { bg: "#f0f9ff", text: "#0369a1", border: "#bae6fd" },

    { bg: "#f7fee7", text: "#4d7c0f", border: "#d9f99d" },
    { bg: "#fef2f2", text: "#b91c1c", border: "#fecaca" },
    { bg: "#faf5ff", text: "#7e22ce", border: "#e9d5ff" },
    { bg: "#fff1f2", text: "#be123c", border: "#fecdd3" },
    { bg: "#ecfeff", text: "#0e7490", border: "#a5f3fc" },
    { bg: "#fefce8", text: "#854d0e", border: "#fef08a" },
    { bg: "#f0fdf4", text: "#166534", border: "#bbf7d0" },
    { bg: "#fdf4ff", text: "#a21caf", border: "#f5d0fe" },
    { bg: "#f5f5f4", text: "#57534e", border: "#d6d3d1" },
    { bg: "#f1f5f9", text: "#0f172a", border: "#cbd5e1" },

    { bg: "#e0f2fe", text: "#075985", border: "#7dd3fc" },
    { bg: "#dcfce7", text: "#14532d", border: "#86efac" },
    { bg: "#fae8ff", text: "#86198f", border: "#f0abfc" },
    { bg: "#ffedd5", text: "#9a3412", border: "#fdba74" },
    { bg: "#ccfbf1", text: "#115e59", border: "#5eead4" },
    { bg: "#ede9fe", text: "#5b21b6", border: "#c4b5fd" },
    { bg: "#fee2e2", text: "#991b1b", border: "#fca5a5" },
    { bg: "#dbeafe", text: "#1e40af", border: "#93c5fd" },
    { bg: "#e2e8f0", text: "#334155", border: "#94a3b8" },
    { bg: "#fef3c7", text: "#92400e", border: "#fcd34d" }
  ];

  function hashDepartment(value) {
    let hash = 0;
    const text = String(value || "").trim().toLowerCase();

    for (let i = 0; i < text.length; i++) {
      hash = text.charCodeAt(i) + ((hash << 5) - hash);
      hash = hash & hash;
    }

    return Math.abs(hash);
  }

  pills.forEach((pill) => {
    const department = pill.dataset.departmentPill || pill.textContent || "";
    const normalizedDepartment = String(department || "").trim().toLowerCase();

    const color =
      normalizedDepartment === "technology"
        ? { bg: "#f5f3ff", text: "#6d28d9", border: "#ddd6fe" }
        : palette[hashDepartment(department) % palette.length];

    pill.style.backgroundColor = color.bg;
    pill.style.color = color.text;
    pill.style.borderColor = color.border;
  });
}