document.addEventListener("DOMContentLoaded", function () {
  initStaffStatusKiosk();
  initStaffStatusBoard();
});

function initStaffStatusKiosk() {
  const form = document.getElementById("staff-status-kiosk-form");
  if (!form) return;

  const resultBox = document.getElementById("staff-status-kiosk-result");
  const resetSeconds = Number(form.dataset.resetSeconds || "5");
  const submitButton = form.querySelector('button[type="submit"]');

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
        resultBox.className = "staff-status-result staff-status-result-success";
        resultBox.textContent = "Status updated successfully.";

        window.setTimeout(() => {
          form.reset();
          resultBox.hidden = true;
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
    }
  });
}

function initStaffStatusBoard() {
  const grid = document.getElementById("staff-status-board-grid");
  if (!grid) return;

  const dataUrl = grid.dataset.dataUrl;
  const refreshSeconds = Number(grid.dataset.refreshSeconds || "15");

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

  async function refreshBoard() {
    try {
      const response = await fetch(dataUrl, { method: "GET" });
      const payload = await response.json();

      if (response.ok && payload.ok && Array.isArray(payload.rows)) {
        renderRows(payload.rows);
      }
    } catch (error) {
      // ignore transient refresh failures
    }
  }

  window.setInterval(refreshBoard, refreshSeconds * 1000);
}