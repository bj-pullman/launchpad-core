document.addEventListener("DOMContentLoaded", initStaffStatusScripts);

function initStaffStatusScripts() {
  initStaffStatusKiosk();
  initStaffStatusBoard();
  initAbsenceDurationForm();
  initInlineEditToggles();
  initEditAbsenceForms();
  initAbsenceUserFilterSearch();
  initStaffStatusLocationSorting();
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

  if (!durationSelect) return;

  function updateDurationFields() {
    const isMultiDay = durationSelect.value === "multi_day";

    if (daysValueField) {
      daysValueField.hidden = !isMultiDay;
    }

    if (endDateField) {
      endDateField.hidden = !isMultiDay;
    }
  }

  durationSelect.addEventListener("change", updateDurationFields);
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
    full_day: "1.0"
  };

  forms.forEach((form) => {
    const durationSelect = form.querySelector(".staff-status-edit-duration-mode");
    const endDateField = form.querySelector(".staff-status-edit-end-date-field");
    const daysValueField = form.querySelector(".staff-status-edit-days-value-field");
    const daysValueInput = form.querySelector(".staff-status-edit-days-value-input");
    const startDateInput = form.querySelector('input[name="start_date"]');
    const endDateInput = form.querySelector('input[name="end_date"]');

    if (!durationSelect) return;

    function updateEditDurationFields() {
      const mode = durationSelect.value;
      const isMultiDay = mode === "multi_day";

      if (endDateField) {
        endDateField.hidden = !isMultiDay;
      }

      if (daysValueField) {
        daysValueField.hidden = !isMultiDay;
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
  const searchInput = document.getElementById("absence-user-search");
  const userList = document.getElementById("absence-user-filter-list");

  if (!searchInput || !userList) return;

  const options = Array.from(
    userList.querySelectorAll(".staff-status-user-filter-option")
  );

  function applyFilter() {
    const query = searchInput.value.trim().toLowerCase();

    if (!query) {
      userList.hidden = true;

      options.forEach((option) => {
        const checked = !!option.querySelector('input[type="checkbox"]')?.checked;
        option.hidden = !checked;
      });

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