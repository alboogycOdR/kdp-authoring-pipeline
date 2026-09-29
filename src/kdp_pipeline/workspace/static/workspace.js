(() => {
  const selector = document.getElementById("theme-choice");
  if (!selector) return;
  const allowed = new Set(["light", "dark", "brand"]);
  let stored = "brand";
  try {
    const value = window.localStorage.getItem("kdp-workspace-theme");
    if (allowed.has(value)) stored = value;
  } catch (_) {
    // Theme selection still works for this page when storage is unavailable.
  }
  document.body.dataset.theme = stored;
  selector.value = stored;
  selector.addEventListener("change", () => {
    const value = selector.value;
    if (!allowed.has(value)) return;
    document.body.dataset.theme = value;
    try {
      window.localStorage.setItem("kdp-workspace-theme", value);
    } catch (_) {
      // Keep the selection active for the current page without persistence.
    }
  });
  for (const form of document.querySelectorAll('form[data-provider-call="true"]')) {
    form.addEventListener("submit", () => {
      const button = form.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
        button.textContent = "Request running…";
      }
      const status = document.createElement("p");
      status.setAttribute("role", "status");
      status.textContent = "Keep this page open. If the connection fails, inspect Recent jobs before trying again.";
      form.append(status);
    });
  }
})();
