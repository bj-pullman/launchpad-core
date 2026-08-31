document.addEventListener("DOMContentLoaded", initStaffStatusScripts);

function initStaffStatusScripts() {
  initStaffStatusKiosk();
  initStaffStatusBoard();
  initAbsenceDurationForm();
  initInlineEditToggles();
  initEditAbsenceForms();
  initAbsenceUserFilterSearch();
  initAbsenceDateRangeFields();
  initStaffStatusLocationSorting();
  initStaffStatusModals();
}

function initStaffStatusKiosk() {
  const form = document.getElementById("staff-status-kiosk-form");
  if (!form) return;

  const resultBox = document.getElementById("staff-status-kiosk-result");
  const resetSeconds = Number(form.dataset.resetSeconds || "2");
  const submitButton = form.querySelector('button[type="submit"]');
  const successOverlay = document.getElementById("staff-status-kiosk-success-overlay");
  const successMessage = document.getElementById("staff-status-kiosk-success-message");

  const userSearch = document.getElementById("staff-status-kiosk-user-search");
  const userList = document.getElementById("staff-status-kiosk-user-list");
  const clearUsersButton = document.getElementById("staff-status-kiosk-clear-users");
  const selectedCountEl = document.getElementById("staff-status-kiosk-selected-count");

  function getSelectedUsers() {
    return Array.from(form.querySelectorAll('input[name="user_ids"]:checked'));
  }

  function getSelectedLocations() {
    return Array.from(form.querySelectorAll('input[name="location_labels"]:checked'));
  }

  function updateSubmitLabel() {
    if (!submitButton) return;

    const selectedCount = getSelectedUsers().length;

    if (selectedCountEl) {
      selectedCountEl.textContent = String(selectedCount);
    }

    if (selectedCount > 1) {
      submitButton.textContent = `Update ${selectedCount} Staff`;
    } else {
      submitButton.textContent = "Update Status";
    }
  }

  function applyUserSearch() {
    if (!userSearch || !userList) return;

    const query = userSearch.value.trim().toLowerCase();
    const options = Array.from(
      userList.querySelectorAll(".staff-status-kiosk-user-option")
    );

    options.forEach((option) => {
      const label = option.dataset.userLabel || "";
      const checkbox = option.querySelector('input[type="checkbox"]');
      const isChecked = !!checkbox?.checked;

      option.hidden = !!query && !label.includes(query) && !isChecked;
    });
  }

  if (userList) {
    userList.addEventListener("change", function () {
      updateSubmitLabel();
      applyUserSearch();
    });
  }

  if (userSearch) {
    userSearch.addEventListener("input", applyUserSearch);
  }

  if (clearUsersButton) {
    clearUsersButton.addEventListener("click", function () {
      form.querySelectorAll('input[name="user_ids"]').forEach((checkbox) => {
        checkbox.checked = false;
      });

      updateSubmitLabel();
      applyUserSearch();
    });
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();

    const selectedUsers = getSelectedUsers();
    const selectedLocations = getSelectedLocations();

    if (!selectedUsers.length) {
      resultBox.hidden = false;
      resultBox.className = "staff-status-result staff-status-result-error";
      resultBox.textContent = "Select at least one staff member.";
      return;
    }

    if (!selectedLocations.length) {
      resultBox.hidden = false;
      resultBox.className = "staff-status-result staff-status-result-error";
      resultBox.textContent = "Select at least one location.";
      return;
    }

    const formData = new FormData(form);
    const originalText = submitButton.textContent;

    submitButton.disabled = true;
    submitButton.textContent = "Updating...";

    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: formData
      });

      const payload = await response.json();

      resultBox.hidden = false;

      if (response.ok && payload.ok) {
        resultBox.hidden = true;

        if (successMessage) {
          const updatedCount = payload.updated_count || selectedUsers.length;
          successMessage.textContent =
            updatedCount === 1
              ? "The status was updated successfully."
              : `${updatedCount} staff statuses were updated successfully.`;
        }

        if (successOverlay) {
          successOverlay.hidden = false;
        }

        window.setTimeout(() => {
          form.reset();
          updateSubmitLabel();
          applyUserSearch();

          if (successOverlay) {
            successOverlay.hidden = true;
          }
        }, resetSeconds * 1000);
      } else {
        resultBox.className = "staff-status-result staff-status-result-error";
        resultBox.textContent = payload.error || "Unable to update status.";
      }
    } catch (error) {
      resultBox.hidden = false;
      resultBox.className = "staff-status-result staff-status-result-error";
      resultBox.textContent = "Unable to update status.";
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = originalText;
      updateSubmitLabel();
    }
  });

  updateSubmitLabel();
  applyUserSearch();
}

function initStaffStatusBoard() {
  const grid = document.getElementById("staff-status-board-grid");
  if (!grid) return;

  const dataUrl = grid.dataset.dataUrl;
  const refreshSeconds = Number(grid.dataset.refreshSeconds || "30");
  const boardTimezone = grid.dataset.timezone || "America/Chicago";

  const dateEl = document.getElementById("staff-status-board-date");
  const timeEl = document.getElementById("staff-status-board-time");

  let refreshInFlight = false;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function renderRows(rows) {
    grid.innerHTML = "";

    rows.forEach((row) => {
      const article = document.createElement("article");
      article.className = "staff-status-board-row";

      const updatedText = row.updated_at || "No updates yet";
      const outClass = row.is_out_of_office ? "out" : "";

      article.innerHTML = `
        <div class="staff-status-board-name">${escapeHtml(row.display_name)}</div>
        <div class="staff-status-board-status ${outClass}">${escapeHtml(row.display_status_label)}</div>
        <div class="staff-status-board-updated">${escapeHtml(updatedText)}</div>
      `;

      grid.appendChild(article);
    });
  }

  function updateClock() {
    const now = new Date();

    if (dateEl) {
      dateEl.textContent = new Intl.DateTimeFormat([], {
        weekday: "long",
        month: "long",
        day: "numeric",
        year: "numeric",
        timeZone: boardTimezone
      }).format(now);
    }

    if (timeEl) {
      timeEl.textContent = new Intl.DateTimeFormat([], {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
        timeZone: boardTimezone
      }).format(now);
    }
  }

  async function doRefreshBoard() {
    if (refreshInFlight || !dataUrl) return;

    refreshInFlight = true;

    try {
      const response = await fetch(dataUrl, {
        method: "GET",
        cache: "no-store"
      });

      const payload = await response.json();

      if (response.ok && payload.ok && Array.isArray(payload.rows)) {
        renderRows(payload.rows);
      }
    } catch (error) {
      // Ignore transient failures.
    } finally {
      refreshInFlight = false;
    }
  }

  updateClock();
  window.setInterval(updateClock, 1000);
  window.setInterval(doRefreshBoard, refreshSeconds * 1000);
}

function initAbsenceDurationForm() {
  const durationSelect = document.getElementById("duration_mode");
  const daysValueField = document.getElementById("days-value-field");
  const endDateField = document.getElementById("end-date-field");
  const startTimeField = document.getElementById("start-time-field");
  const daysValueInput = daysValueField?.querySelector('input[name="days_value"]');
  const endDateInput = endDateField?.querySelector('input[name="end_date"]');
  const startDateInput = document.querySelector(
    ".staff-status-add-absence-form input[name=\"start_date\"]"
  );
  const startTimeInput = startTimeField?.querySelector('input[name="start_time"]');

  if (!durationSelect) return;

  const durationLookup = {
    quarter_day: "0.25",
    half_day: "0.5",
    three_quarter_day: "0.75",
    full_day: "1.0",
    summer_2_hours: "0.25",
    summer_4_hours: "0.5",
    summer_6_hours: "0.75",
    summer_8_hours: "1.0",
    summer_full_day: "1.25"
  };

  const timedDurationModes = new Set([
    "quarter_day",
    "half_day",
    "three_quarter_day",
    "summer_2_hours",
    "summer_4_hours",
    "summer_6_hours"
  ]);

  function updateDurationFields() {
    const mode = durationSelect.value;
    const isMultiDay = mode === "multi_day";
    const isTimed = timedDurationModes.has(mode);

    if (daysValueField) {
      daysValueField.hidden = !isMultiDay;
    }

    if (endDateField) {
      endDateField.hidden = !isMultiDay;
    }

    if (startTimeField) {
      startTimeField.hidden = !isTimed && !isMultiDay;
    }

    if (startTimeInput) {
      startTimeInput.required = isTimed;

      if (!isTimed && !isMultiDay) {
        startTimeInput.value = "";
      }
    }

    if (daysValueInput) {
      daysValueInput.required = isMultiDay;

      if (!isMultiDay && durationLookup[mode]) {
        daysValueInput.value = durationLookup[mode];
      }
    }

    if (endDateInput) {
      endDateInput.required = isMultiDay;

      if (!isMultiDay && startDateInput) {
        endDateInput.value = startDateInput.value;
      }
    }
  }

  durationSelect.addEventListener("change", updateDurationFields);

  if (startDateInput && endDateInput) {
    startDateInput.addEventListener("change", function () {
      if (durationSelect.value !== "multi_day") {
        endDateInput.value = startDateInput.value;
      }
    });
  }

  updateDurationFields();
}

function initInlineEditToggles() {
  const buttons = document.querySelectorAll(".staff-status-edit-toggle-btn");
  const locationRows = document.querySelectorAll(".staff-status-location-row");

  function toggleEditRow(targetId) {
    if (!targetId) return;

    const targetRow = document.getElementById(targetId);
    if (!targetRow) return;

    const isHidden = targetRow.hidden;

    document.querySelectorAll(".staff-status-edit-row, .staff-status-location-edit-row").forEach((row) => {
      row.hidden = true;
    });

    if (isHidden) {
      targetRow.hidden = false;
    }
  }

  buttons.forEach((button) => {
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      toggleEditRow(button.dataset.target);
    });
  });

  locationRows.forEach((row) => {
    row.addEventListener("click", function (event) {
      const interactiveElement = event.target.closest(
        "button, a, input, select, textarea, label, form"
      );

      if (interactiveElement) return;

      toggleEditRow(row.dataset.editTarget);
    });
  });
}

function initEditAbsenceForms() {
  const forms = document.querySelectorAll(".staff-status-edit-absence-form");
  if (!forms.length) return;

  const durationLookup = {
    quarter_day: "0.25",
    half_day: "0.5",
    three_quarter_day: "0.75",
    full_day: "1.0",
    summer_2_hours: "0.25",
    summer_4_hours: "0.5",
    summer_6_hours: "0.75",
    summer_8_hours: "1.0",
    summer_full_day: "1.25"
  };

  forms.forEach((form) => {
    const durationSelect = form.querySelector(".staff-status-edit-duration-mode");
    const endDateField = form.querySelector(".staff-status-edit-end-date-field");
    const daysValueField = form.querySelector(".staff-status-edit-days-value-field");
    const daysValueInput = form.querySelector(".staff-status-edit-days-value-input");
    const startTimeField = form.querySelector(".staff-status-edit-start-time-field");
    const startTimeInput = form.querySelector('input[name="start_time"]');
    const startDateInput = form.querySelector('input[name="start_date"]');
    const endDateInput = form.querySelector('input[name="end_date"]');

    if (!durationSelect) return;

    const timedDurationModes = new Set([
      "quarter_day",
      "half_day",
      "three_quarter_day",
      "summer_2_hours",
      "summer_4_hours",
      "summer_6_hours"
    ]);

    function updateEditDurationFields() {
      const mode = durationSelect.value;
      const isMultiDay = mode === "multi_day";
      const isTimed = timedDurationModes.has(mode);

      if (endDateField) {
        endDateField.hidden = !isMultiDay;
      }

      if (daysValueField) {
        daysValueField.hidden = !isMultiDay;
      }

      if (startTimeField) {
        startTimeField.hidden = !isTimed && !isMultiDay;
      }

      if (startTimeInput) {
        startTimeInput.required = isTimed;

        if (!isTimed && !isMultiDay) {
          startTimeInput.value = "";
        }
      }

      if (daysValueInput) {
        daysValueInput.required = isMultiDay;
      }

      if (endDateInput) {
        endDateInput.required = isMultiDay;
      }

      if (!isMultiDay) {
        if (daysValueInput && durationLookup[mode]) {
          daysValueInput.value = durationLookup[mode];
        }

        if (startDateInput && endDateInput) {
          endDateInput.value = startDateInput.value;
        }
      }
    }

    durationSelect.addEventListener("change", updateEditDurationFields);

    if (startDateInput && endDateInput) {
      startDateInput.addEventListener("change", function () {
        if (durationSelect.value !== "multi_day") {
          endDateInput.value = startDateInput.value;
        }
      });
    }

    updateEditDurationFields();
  });
}

function initAbsenceUserFilterSearch() {
  initAbsenceUserSearch("absence-table-user-search", "absence-table-user-filter-list");
  initAbsenceUserSearch("absence-report-user-search", "absence-report-user-filter-list");
}

function initAbsenceUserSearch(searchInputId, userListId) {
  const searchInput = document.getElementById(searchInputId);
  const userList = document.getElementById(userListId);

  if (!searchInput || !userList) return;

  const options = Array.from(
    userList.querySelectorAll(".staff-status-user-filter-option")
  );

  function applyFilter() {
    const query = searchInput.value.trim().toLowerCase();

    if (!query) {
      let anyChecked = false;

      options.forEach((option) => {
        const checked = !!option.querySelector('input[type="checkbox"]')?.checked;
        option.hidden = !checked;

        if (checked) {
          anyChecked = true;
        }
      });

      userList.hidden = !anyChecked;
      return;
    }

    let anyVisible = false;

    options.forEach((option) => {
      const label = (option.dataset.userLabel || "").toLowerCase();
      const checked = !!option.querySelector('input[type="checkbox"]')?.checked;
      const matches = label.includes(query);

      option.hidden = !(matches || checked);

      if (!option.hidden) {
        anyVisible = true;
      }
    });

    userList.hidden = !anyVisible;
  }

  searchInput.addEventListener("input", applyFilter);
  userList.addEventListener("change", applyFilter);

  applyFilter();
}

function initAbsenceDateRangeFields() {
  initAbsenceCustomRangeFields("absence-table-date-range", "absence-table-custom-range-fields");
  initAbsenceCustomRangeFields("absence-report-date-range", "absence-report-custom-range-fields");
  initAbsenceReportPeriodHelper();
}

function initAbsenceCustomRangeFields(dateRangeSelectId, customRangeFieldsId) {
  const dateRangeSelect = document.getElementById(dateRangeSelectId);
  const customRangeFields = document.getElementById(customRangeFieldsId);

  if (!dateRangeSelect || !customRangeFields) return;

  const customInputs = Array.from(
    customRangeFields.querySelectorAll('input[type="date"]')
  );

  function updateCustomFields() {
    const isCustom = dateRangeSelect.value === "custom";
    customRangeFields.hidden = !isCustom;

    customInputs.forEach((input) => {
      input.required = isCustom;
    });
  }

  dateRangeSelect.addEventListener("change", updateCustomFields);
  updateCustomFields();
}

function initAbsenceReportPeriodHelper() {
  const dateRangeSelect = document.getElementById("absence-report-date-range");
  const helperText = document.getElementById("absence-report-period-helper");
  const startDateInput = document.getElementById("absence-report-start-date");
  const endDateInput = document.getElementById("absence-report-end-date");

  if (!dateRangeSelect || !helperText) return;

  function formatDate(isoDate) {
    if (!isoDate || !/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
      return "";
    }

    const [year, month, day] = isoDate.split("-");
    return `${month}/${day}/${year}`;
  }

  function updateHelperText() {
    const selectedOption = dateRangeSelect.options[dateRangeSelect.selectedIndex];
    const selectedLabel = selectedOption?.dataset.label || selectedOption?.textContent.trim() || "Export period";

    if (dateRangeSelect.value === "custom") {
      const startDate = startDateInput?.value || "";
      const endDate = endDateInput?.value || "";

      if (startDate && endDate) {
        helperText.textContent = `${selectedLabel}: ${formatDate(startDate)} to ${formatDate(endDate)}`;
      } else if (startDate) {
        helperText.textContent = `${selectedLabel}: ${formatDate(startDate)} to choose an end date.`;
      } else if (endDate) {
        helperText.textContent = `${selectedLabel}: choose a start date to ${formatDate(endDate)}.`;
      } else {
        helperText.textContent = `${selectedLabel}: choose a start and end date.`;
      }

      return;
    }

    const helper = selectedOption?.dataset.helperText;
    const startDate = selectedOption?.dataset.startDate || "";
    const endDate = selectedOption?.dataset.endDate || "";

    if (helper) {
      helperText.textContent = helper;
    } else if (startDate && endDate) {
      helperText.textContent = `${selectedLabel}: ${formatDate(startDate)} to ${formatDate(endDate)}`;
    } else {
      helperText.textContent = selectedLabel;
    }
  }

  dateRangeSelect.addEventListener("change", updateHelperText);

  [startDateInput, endDateInput].forEach((input) => {
    if (!input) return;
    input.addEventListener("input", updateHelperText);
    input.addEventListener("change", updateHelperText);
  });

  updateHelperText();
}

function initStaffStatusLocationSorting() {
  const sortableBody = document.getElementById("staff-status-location-sortable");
  if (!sortableBody) return;

  if (typeof Sortable === "undefined") {
    console.warn("SortableJS is not loaded. Location drag-and-drop is disabled.");
    return;
  }

  const reorderUrl = sortableBody.dataset.reorderUrl;
  const resultBox = document.getElementById("staff-status-location-order-result");

  let saveTimer = null;

  function showResult(message, ok) {
    if (!resultBox) return;

    resultBox.hidden = false;
    resultBox.textContent = message;
    resultBox.className = ok
      ? "staff-status-result staff-status-result-success"
      : "staff-status-result staff-status-result-error";

    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      resultBox.hidden = true;
    }, 2500);
  }

  async function saveOrder() {
    if (!reorderUrl) {
      showResult("Location reorder URL is missing.", false);
      return;
    }

    const locationIds = Array.from(
      sortableBody.querySelectorAll(".staff-status-location-row")
    )
      .map((row) => Number(row.dataset.locationId))
      .filter((locationId) => Number.isInteger(locationId) && locationId > 0);

    try {
      const response = await fetch(reorderUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          location_ids: locationIds
        })
      });

      const payload = await response.json();

      if (!response.ok || !payload.ok) {
        showResult(payload.error || "Unable to save location order.", false);
        return;
      }

      showResult("Location order saved.", true);
    } catch (error) {
      showResult("Unable to save location order.", false);
    }
  }

  new Sortable(sortableBody, {
    animation: 150,
    draggable: ".staff-status-location-row",
    filter: "button, a, input, select, textarea, label, form, .staff-status-location-edit-row",
    preventOnFilter: false,
    ghostClass: "staff-status-location-sort-ghost",
    chosenClass: "staff-status-location-sort-chosen",
    onEnd: saveOrder
  });
}

function initStaffStatusModals() {
  const openButtons = document.querySelectorAll("[data-modal-open]");
  const closeButtons = document.querySelectorAll("[data-modal-close]");
  const modals = document.querySelectorAll(".staff-status-modal-backdrop");

  if (!openButtons.length && !modals.length) return;

  let activeModal = null;
  let lastFocusedElement = null;

  function focusFirstControl(modal) {
    const focusable = modal.querySelector(
      "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex=\"-1\"])"
    );

    if (focusable) {
      focusable.focus();
    }
  }

  function openModal(modalId, trigger) {
    const modal = document.getElementById(modalId);
    if (!modal) return;

    if (activeModal && activeModal !== modal) {
      closeModal(activeModal, false);
    }

    lastFocusedElement = trigger || document.activeElement;
    activeModal = modal;
    modal.hidden = false;
    document.body.classList.add("staff-status-modal-open");
    focusFirstControl(modal);
  }

  function closeModal(modal, restoreFocus = true) {
    if (!modal) return;

    modal.hidden = true;

    if (activeModal === modal) {
      activeModal = null;
      document.body.classList.remove("staff-status-modal-open");
    }

    if (restoreFocus && lastFocusedElement && typeof lastFocusedElement.focus === "function") {
      lastFocusedElement.focus();
    }
  }

  openButtons.forEach((button) => {
    button.addEventListener("click", function () {
      openModal(button.dataset.modalOpen, button);
    });
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", function () {
      closeModal(button.closest(".staff-status-modal-backdrop"));
    });
  });

  modals.forEach((modal) => {
    modal.addEventListener("click", function (event) {
      if (event.target === modal) {
        closeModal(modal);
      }
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && activeModal) {
      closeModal(activeModal);
    }
  });

  document.querySelectorAll("[data-edit-close]").forEach((button) => {
    button.addEventListener("click", function () {
      const editRow = button.closest(".staff-status-edit-row");
      if (editRow) {
        editRow.hidden = true;
      }
    });
  });
}
