(() => {
  async function submitForm(form) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: {"X-Requested-With": "XMLHttpRequest"},
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) throw new Error(payload.message || "儲存失敗，請稍後再試。");
      return payload;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("儲存等待逾時，請確認網路後再試一次。");
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  function updateProgress(payload) {
    document.querySelector("[data-progress-count]").textContent = `${payload.completed_count}／${payload.total_count} 家`;
    document.querySelector("[data-progress-label]").textContent = `尚有 ${payload.pending_count} 家未完成`;
    document.querySelector("[data-progress-percent]").textContent = `${payload.progress_percent}%`;
    document.querySelector("[data-progress-bar]").style.width = `${payload.progress_percent}%`;
  }

  document.addEventListener("submit", async event => {
    const form = event.target;
    if (!form.matches("[data-distribution-complete], [data-distribution-note]")) return;
    event.preventDefault();
    if (form.dataset.saving === "1") return;
    form.dataset.saving = "1";
    try {
      const payload = await submitForm(form);
      if (form.matches("[data-distribution-complete]")) {
        const card = form.closest("[data-distribution-item]");
        const button = form.querySelector("button");
        form.querySelector('input[name="completed"]').value = payload.completed ? "0" : "1";
        card.classList.toggle("is-completed", payload.completed);
        button.classList.toggle("is-completed", payload.completed);
        button.setAttribute("aria-checked", payload.completed ? "true" : "false");
        button.querySelector("strong").textContent = payload.completed ? "已完成" : "標記完成";
        updateProgress(payload);
      } else {
        const status = form.querySelector("[data-note-status]");
        status.textContent = "已儲存";
        status.classList.add("is-saved");
      }
    } catch (error) {
      window.alert(error.message);
    } finally {
      form.dataset.saving = "0";
    }
  });

  document.addEventListener("change", event => {
    const note = event.target.closest("[data-distribution-note] textarea");
    if (note) note.form.requestSubmit();
  });
})();
