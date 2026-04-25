document.addEventListener("DOMContentLoaded", function () {
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

  if (typeof initFinanceNotificationTemplateBuilder === "function") {
    initFinanceNotificationTemplateBuilder();
  }

  initApiKeyCreatedModal();
});
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
    const toggle = card.querySelector('input[type="checkbox"]');
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