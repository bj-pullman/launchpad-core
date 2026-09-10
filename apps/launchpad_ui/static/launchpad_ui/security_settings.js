document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector(".settings-security-form");
  const secure = form?.querySelector('[name="cookie_secure"]');
  const sameSite = form?.querySelector('[name="cookie_samesite"]');
  const error = document.getElementById("cookie-samesite-error");

  if (!form || !secure || !sameSite || !error || sameSite.disabled) return;

  const validateCookiePolicy = () => {
    const invalid = sameSite.value === "None" && !secure.checked;
    const message = invalid ? "SameSite=None requires Secure cookies." : "";
    sameSite.setCustomValidity(message);
    sameSite.toggleAttribute("aria-invalid", invalid);
    error.hidden = !invalid;
    return !invalid;
  };

  secure.addEventListener("change", validateCookiePolicy);
  sameSite.addEventListener("change", validateCookiePolicy);
  form.addEventListener("submit", event => {
    if (validateCookiePolicy()) return;
    event.preventDefault();
    sameSite.reportValidity();
    sameSite.focus();
  });

  validateCookiePolicy();
});
