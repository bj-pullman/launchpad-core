(function () {
  const tabs = document.querySelectorAll("[data-sur-tab]");
  const panels = document.querySelectorAll("[data-sur-panel]");
  const syncBtn = document.getElementById("surSyncBtn");

  const modal = document.getElementById("surConfirmModal");
  const modalTitle = document.getElementById("surConfirmTitle");
  const modalText = document.getElementById("surConfirmText");
  const modalWarning = document.getElementById("surConfirmWarning");
  const modalInput = document.getElementById("surConfirmInput");
  const modalSubmit = document.getElementById("surConfirmSubmit");

  const studentRows = Array.from(document.querySelectorAll("tbody [data-student-row]"));
  const studentPageSize = document.getElementById("studentPageSize");
  const studentPrevPage = document.getElementById("studentPrevPage");
  const studentNextPage = document.getElementById("studentNextPage");
  const studentPageStatus = document.getElementById("studentPageStatus");

  let pendingForm = null;
  let expectedPhrase = "";
  let studentPage = 1;

  function activateTab(name) {
    tabs.forEach((tab) => {
      const active = tab.dataset.surTab === name;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });

    panels.forEach((panel) => {
      panel.classList.toggle("is-active", panel.dataset.surPanel === name);
    });

    const url = new URL(window.location.href);
    url.hash = name;
    window.history.replaceState({}, "", url.toString());
  }

  function renderStudentPage() {
    if (!studentRows.length || !studentPageSize) return;

    const pageSize = parseInt(studentPageSize.value, 10) || 50;
    const totalPages = Math.max(1, Math.ceil(studentRows.length / pageSize));

    studentPage = Math.min(Math.max(studentPage, 1), totalPages);

    const start = (studentPage - 1) * pageSize;
    const end = start + pageSize;

    studentRows.forEach((row, index) => {
      row.hidden = !(index >= start && index < end);
    });

    if (studentPageStatus) {
      const visibleStart = studentRows.length ? start + 1 : 0;
      const visibleEnd = Math.min(end, studentRows.length);
      studentPageStatus.textContent = `${visibleStart}-${visibleEnd} of ${studentRows.length}`;
    }

    if (studentPrevPage) studentPrevPage.disabled = studentPage <= 1;
    if (studentNextPage) studentNextPage.disabled = studentPage >= totalPages;
  }

  function visibleStudentCheckboxes() {
    return Array.from(document.querySelectorAll("[data-student-checkbox]"))
      .filter((checkbox) => !checkbox.closest("tr").hidden);
  }

  function selectedStudentCheckboxes(form) {
    return Array.from(form.querySelectorAll('input[name="user_ids"]:checked'));
  }

  function showInlineMessage(form, message, type = "info") {
    let messageBox = form.querySelector("[data-sur-form-error]");

    if (!messageBox) {
      messageBox = document.createElement("div");
      messageBox.className = "sur-form-error";
      messageBox.setAttribute("data-sur-form-error", "");
      form.prepend(messageBox);
    }

    messageBox.textContent = message;
    messageBox.dataset.messageType = type;
  }

  function openModal(button) {
    const formId = button.dataset.targetForm;
    const action = button.dataset.modalAction;

    pendingForm = formId ? document.getElementById(formId) : button.closest("form");

    if (!pendingForm) {
      console.error("No form found for action button.", button);
      return;
    }

    pendingForm.querySelector("[data-sur-form-error]")?.remove();

    if (action === "student-purge") {
      const checked = selectedStudentCheckboxes(pendingForm);

      if (!checked.length) {
        showInlineMessage(pendingForm, "Select at least one student account first.", "error");
        return;
      }

      expectedPhrase = "DELETE STUDENTS";
      modalTitle.textContent = "Confirm Student Account Purge";
      modalText.textContent = `You are about to check in assets and delete ${checked.length} selected student account(s).`;
      modalWarning.textContent = "This will delete selected Snipe-IT student users only after assigned assets are checked in.";
      modalSubmit.textContent = "Delete Selected Students";
    } else if (action === "merge") {
      expectedPhrase = "MERGE USERS";
      modalTitle.textContent = "Confirm User Merge";
      modalText.textContent = "You are about to move assigned assets from the source user to the target user.";
      modalWarning.textContent = "If Delete Source is checked, the duplicate Snipe-IT user will be deleted after assets move.";
      modalSubmit.textContent = "Merge Users";
    } else {
      console.error("Unknown modal action.", action);
      return;
    }

    modalInput.value = "";
    modalInput.placeholder = `Type ${expectedPhrase}`;
    modalInput.classList.remove("sur-input-error");

    modal.hidden = false;
    setTimeout(() => modalInput.focus(), 50);
  }

  function closeModal() {
    modal.hidden = true;
    pendingForm = null;
    expectedPhrase = "";
    modalInput.value = "";
    modalSubmit.disabled = false;
    modalSubmit.classList.remove("is-working");
    modalSubmit.textContent = "Confirm";
  }

  async function submitPendingForm() {
    if (!pendingForm) return;

    if (modalInput.value.trim() !== expectedPhrase) {
      modalInput.classList.add("sur-input-error");
      modalInput.focus();
      return;
    }

    let confirmation = pendingForm.querySelector('input[name="confirmation"]');

    if (!confirmation) {
      confirmation = document.createElement("input");
      confirmation.type = "hidden";
      confirmation.name = "confirmation";
      pendingForm.appendChild(confirmation);
    }

    confirmation.value = expectedPhrase;

    modalSubmit.disabled = true;
    modalSubmit.classList.add("is-working");
    modalSubmit.textContent = "Working...";

    try {
      const response = await fetch(pendingForm.action, {
        method: "POST",
        body: new FormData(pendingForm),
        headers: {
          "X-Requested-With": "fetch",
          "Accept": "application/json"
        }
      });

      const contentType = response.headers.get("content-type") || "";
      const payload = contentType.includes("application/json")
        ? await response.json()
        : { ok: false, message: await response.text() };

      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || "Action failed.");
      }

      if (expectedPhrase === "DELETE STUDENTS") {
        const deleted = payload.result?.deleted || [];

        deleted.forEach((item) => {
          const checkbox = pendingForm.querySelector(
            `input[name="user_ids"][value="${item.user_id}"]`
          );

          const row = checkbox?.closest("tr");
          if (row) row.remove();

          const rowIndex = studentRows.indexOf(row);
          if (rowIndex >= 0) studentRows.splice(rowIndex, 1);
        });

        pendingForm.querySelectorAll('input[name="user_ids"]:checked').forEach((checkbox) => {
          checkbox.checked = false;
        });

        renderStudentPage();
      }

      if (expectedPhrase === "MERGE USERS") {
        const sourceUserId = payload.result?.source_user_id;
        if (sourceUserId) {
          const sourceInput = pendingForm.querySelector(`input[name="source_user_id"][value="${sourceUserId}"]`);
          const row = sourceInput?.closest("tr");
          if (row) row.remove();
        }
      }

      showInlineMessage(pendingForm, payload.message || "Action completed.", "success");
      closeModal();

    } catch (error) {
      showInlineMessage(pendingForm, error.message || "Action failed.", "error");
      modalSubmit.disabled = false;
      modalSubmit.classList.remove("is-working");
      modalSubmit.textContent = expectedPhrase === "DELETE STUDENTS"
        ? "Delete Selected Students"
        : "Merge Users";
    }
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.surTab));
  });

  document.querySelectorAll("[data-open-tab]").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.openTab));
  });

  if (syncBtn) {
    syncBtn.addEventListener("click", () => {
      syncBtn.classList.add("is-syncing");
      syncBtn.setAttribute("aria-busy", "true");
    });
  }

  document.querySelectorAll("[data-select-all-students]").forEach((button) => {
    button.addEventListener("click", () => {
      const checkboxes = visibleStudentCheckboxes();
      const shouldSelect = checkboxes.some((checkbox) => !checkbox.checked);

      checkboxes.forEach((checkbox) => {
        checkbox.checked = shouldSelect;
      });

      button.textContent = shouldSelect ? "Clear Visible" : "Select Visible";
    });
  });

  document.querySelectorAll("[data-open-confirm-modal]").forEach((button) => {
    button.addEventListener("click", () => openModal(button));
  });

  document.querySelectorAll("[data-close-confirm-modal]").forEach((button) => {
    button.addEventListener("click", closeModal);
  });

  modalSubmit?.addEventListener("click", submitPendingForm);

  modalInput?.addEventListener("input", () => {
    modalInput.classList.remove("sur-input-error");
  });

  studentPageSize?.addEventListener("change", () => {
    studentPage = 1;
    renderStudentPage();
  });

  studentPrevPage?.addEventListener("click", () => {
    studentPage -= 1;
    renderStudentPage();
  });

  studentNextPage?.addEventListener("click", () => {
    studentPage += 1;
    renderStudentPage();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal && !modal.hidden) {
      closeModal();
    }
  });

  renderStudentPage();

  const initialTab = window.location.hash.replace("#", "");
  if (initialTab && document.querySelector(`[data-sur-tab="${initialTab}"]`)) {
    activateTab(initialTab);
  }
})();