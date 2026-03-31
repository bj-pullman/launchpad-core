document.addEventListener("DOMContentLoaded", function () {
  initStaffStatusKiosk();
  initStaffStatusBoard();
  initAbsenceDurationForm();
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