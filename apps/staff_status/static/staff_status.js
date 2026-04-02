document.addEventListener("DOMContentLoaded", function () {
  initStaffStatusKiosk();
  initStaffStatusBoard();
  initAbsenceDurationForm();
  initInlineEditToggles();
  initEditAbsenceForms();
  initAbsenceUserFilterSearch();
});

function initStaffStatusKiosk() {
  const form = document.getElementById("staff-status-kiosk-form");
  if (!form) return;

  const resultBox = document.getElementById("staff-status-kiosk-result");
  const resetSeconds = Number(form.dataset.resetSeconds || "2");
  const submitButton = form.querySelector('button[type="submit"]');
  const successOverlay = document.getElementById("staff-status-kiosk-success-overlay");

  form.addEventListener("submit", async function (event) {
    event.preventDefault();

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
      if (successOverlay) {
        successOverlay.hidden = false;
      }

      window.setTimeout(() => {
        form.reset();

        if (successOverlay) {
          successOverlay.hidden = true;
        }
      }, resetSeconds * 1000);
    }else {
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
    }
  });
}

function initStaffStatusBoard() {
  const grid = document.getElementById("staff-status-board-grid");
  if (!grid) return;

  const dataUrl = grid.dataset.dataUrl;
  const refreshSeconds = Number(grid.dataset.refreshSeconds || "5");
  const boardTimezone = grid.dataset.timezone || "America/Chicago";
  const streamUrl = grid.dataset.streamUrl;

  const dateEl = document.getElementById("staff-status-board-date");
  const timeEl = document.getElementById("staff-status-board-time");

  let refreshInFlight = false;
  let refreshPending = false;

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
    if (refreshInFlight) {
      refreshPending = true;
      return;
    }

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
      // ignore transient failures
    } finally {
      refreshInFlight = false;

      if (refreshPending) {
        refreshPending = false;
        doRefreshBoard();
      }
    }
  }

  function connectStream() {
    if (!streamUrl) return;

    const source = new EventSource(streamUrl);

    source.onmessage = function (event) {
      try {
        const payload = JSON.parse(event.data);

        if (payload.type === "department_updated") {
          doRefreshBoard();
        }
      } catch (error) {
        // ignore malformed events
      }
    };

    source.onerror = function () {
      // EventSource auto-reconnects on its own
    };
  }

  updateClock();
  window.setInterval(updateClock, 1000);

  connectStream();

  // Keep a fallback poll in case SSE disconnects silently.
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
  if (!buttons.length) return;

  buttons.forEach((button) => {
    button.addEventListener("click", function () {
      const targetId = button.dataset.target;
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