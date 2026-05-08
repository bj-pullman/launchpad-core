document.addEventListener("submit", async function (event) {
  const form = event.target.closest("form[data-sync-action-form]");
  if (!form) return;

  event.preventDefault();

  const row = form.closest("tr");
  const button = form.querySelector("button[type='submit']");
  const originalText = button.textContent;

  button.disabled = true;
  button.textContent = "Working...";

  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: {
        "X-Requested-With": "fetch"
      },
      body: new FormData(form)
    });

    const data = await response.json();

    let resultBox = row.querySelector("[data-sync-result]");
    if (!resultBox) {
      resultBox = document.createElement("div");
      resultBox.setAttribute("data-sync-result", "1");
      resultBox.style.marginTop = ".5rem";
      form.appendChild(resultBox);
    }

    resultBox.textContent = data.message;
    resultBox.style.color = data.ok ? "#16a34a" : "#dc2626";

    if (data.ok) {
      row.style.opacity = "0.55";
      button.textContent = "Applied";
    } else {
      button.disabled = false;
      button.textContent = originalText;
    }
  } catch (err) {
    alert("Sync action failed: " + err);
    button.disabled = false;
    button.textContent = originalText;
  }
});