document.addEventListener("DOMContentLoaded", initSetupScripts);

function initSetupScripts() {
  initSetupAdminPasswordValidation();
  initSetupSkipModal();
}

function initSetupAdminPasswordValidation() {
  const form = document.getElementById("setup-admin-form");
  if (!form) return;

  const password = document.getElementById("password");
  const confirm = document.getElementById("confirm");

  if (!password || !confirm) return;

  function syncPasswordValidity() {
    if (!confirm.value || password.value === confirm.value) {
      confirm.setCustomValidity("");
    } else {
      confirm.setCustomValidity("Passwords do not match.");
    }
  }

  password.addEventListener("input", syncPasswordValidity);
  confirm.addEventListener("input", syncPasswordValidity);

  form.addEventListener("submit", function () {
    syncPasswordValidity();
  });
}

function initSetupSkipModal() {
  const modal = document.getElementById("setup-skip-modal");
  const skipButtons = document.querySelectorAll(".setup-skip-btn");
  const cancelButtons = document.querySelectorAll("[data-setup-skip-cancel]");

  if (!modal || !skipButtons.length) return;

  const titleEl = document.getElementById("setup-skip-modal-title");
  const messageEl = document.getElementById("setup-skip-modal-message");
  const settingsEl = document.getElementById("setup-skip-modal-settings");

function openModal() {
  if (titleEl) {
    titleEl.textContent = modal.dataset.skipTitle || "Skip this step?";
  }

  if (messageEl) {
    messageEl.textContent =
      modal.dataset.skipMessage ||
      "You can configure this area later from Settings.";
  }

  if (settingsEl) {
    settingsEl.textContent =
      modal.dataset.settingsLater || "Settings";
  }

  modal.hidden = false;

  // Focus first button for accessibility
  const firstButton = modal.querySelector("button");
  if (firstButton) {
    firstButton.focus();
  }
}

  function closeModal() {
    modal.hidden = true;
  }

  skipButtons.forEach((button) => {
    button.addEventListener("click", openModal);
  });

  cancelButtons.forEach((button) => {
    button.addEventListener("click", closeModal);
  });

  document.addEventListener("keydown", function (event) {
    if (modal.hidden) return;

    if (event.key === "Escape") {
      closeModal();
    }
  });
}