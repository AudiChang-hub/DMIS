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

  document.addEventListener("click", event => {
    const toggle = event.target.closest("[data-note-toggle]");
    if (!toggle) return;
    const card = toggle.closest("[data-distribution-item]");
    const open = !card.classList.contains("is-note-open");
    card.classList.toggle("is-note-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) card.querySelector("[data-distribution-note] textarea").focus({preventScroll: true});
  });

  const filters = document.querySelector("[data-distribution-filters]");
  if (!filters) return;
  const filterToggle = filters.querySelector("[data-distribution-filter-toggle]");
  const filterCount = filters.querySelector("[data-distribution-filter-count]");
  const activeFilters = [...filters.querySelectorAll("select[data-filter-default]")]
    .filter(select => !select.disabled && select.value !== select.dataset.filterDefault).length;
  if (activeFilters) {
    filterCount.textContent = activeFilters;
    filterCount.hidden = false;
    filterToggle.setAttribute("aria-label", `篩選，已套用 ${activeFilters} 項條件`);
  }
  filterToggle.addEventListener("click", () => {
    const open = !filters.classList.contains("is-expanded");
    filters.classList.toggle("is-expanded", open);
    filterToggle.setAttribute("aria-expanded", open ? "true" : "false");
  });

  const search = filters.querySelector("[data-distribution-quick-search]");
  const status = filters.querySelector("[data-distribution-search-status]");
  const noMatch = document.querySelector("[data-distribution-no-match]");
  const cards = [...document.querySelectorAll("[data-distribution-item]")];
  const normalize = value => value.toLowerCase().replace(/\s+/g, "").replace(/台/g, "臺");

  function applyQuickSearch() {
    const terms = search.value.trim().split(/\s+/).map(normalize).filter(Boolean);
    let visible = 0;
    cards.forEach(card => {
      const note = card.querySelector("[data-distribution-note] textarea")?.value || "";
      const address = card.querySelector(".price-distribution-card__identity p")?.textContent || "";
      const haystack = normalize(`${card.dataset.search} ${address} ${note}`);
      const match = terms.every(term => haystack.includes(term));
      card.hidden = !match;
      if (match) visible += 1;
    });
    status.hidden = !terms.length;
    status.textContent = terms.length ? `符合 ${visible}／${cards.length} 家` : "";
    if (noMatch) noMatch.hidden = visible > 0;
  }

  search.addEventListener("input", applyQuickSearch);
  search.addEventListener("search", applyQuickSearch);
})();
