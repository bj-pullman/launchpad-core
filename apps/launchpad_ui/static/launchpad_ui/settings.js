document.addEventListener("DOMContentLoaded", function () {
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
        false,
      );
    } finally {
      testButton.disabled = false;
    }
  });
});

document.addEventListener("DOMContentLoaded", function () {
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
});

document.addEventListener("DOMContentLoaded", function () {
    const tabs = document.querySelectorAll(".settings-tab");
    const panels = document.querySelectorAll(".settings-tab-panel");

    if (tabs.length) {
        tabs.forEach((tab) => {
            tab.addEventListener("click", function () {
                tabs.forEach((t) => t.classList.remove("active"));
                panels.forEach((p) => p.classList.remove("active"));

                tab.classList.add("active");

                const panel = document.querySelector(
                    `.settings-tab-panel[data-panel="${tab.dataset.tab}"]`
                );

                if (panel) {
                    panel.classList.add("active");
                }
            });
        });
    }

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
});