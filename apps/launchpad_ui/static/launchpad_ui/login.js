document.addEventListener("DOMContentLoaded", function () {
    const checkbox = document.getElementById("remember_me");
    const button = document.getElementById("google-login-btn");

    if (!button) {
        return;
    }

    const nextUrl = button.dataset.nextUrl || "/";

    function updateGoogleHref() {
        const remember = checkbox && checkbox.checked ? "1" : "0";
        button.href = `/auth/google/start?next=${encodeURIComponent(nextUrl)}&remember=${remember}`;
    }

    if (checkbox) {
        checkbox.addEventListener("change", updateGoogleHref);
    }

    updateGoogleHref();
});