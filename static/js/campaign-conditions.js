(() => {
  // 獎勵活動（T-149）：條件即時預覽、「全部電動類」快捷、活動表單內新增車行獎勵品項。
  // 比對規則與伺服器相同：同一條件任一符合、不同條件同時符合，空白不限；品牌鍵由伺服器 casefold 產生。
  const matches = (model, brands, energies, chosen) =>
    (!brands.length || brands.includes(model.brand))
    && (!energies.length || energies.includes(model.energy))
    && (!chosen.length || chosen.includes(model.id));

  function initConditions(section) {
    if (!section) return;
    const brands = section.querySelector("[data-campaign-brands]");
    const models = section.querySelector("[data-campaign-models]");
    const energies = [...section.querySelectorAll('input[name="energy_types"]')];
    const count = section.querySelector("[data-campaign-match-count]");
    const text = section.querySelector("[data-campaign-match-text]");
    const list = section.querySelector("[data-campaign-match-list]");
    if (!brands || !models || !count || !text || !list) return;
    const selected = (select) => [...select.options].filter((option) => option.selected && option.value);

    function update() {
      const brandKeys = selected(brands).map((option) => option.value.toLocaleLowerCase());
      const energyKeys = energies.filter((input) => input.checked).map((input) => input.value);
      const chosen = selected(models).map((option) => option.value);
      const hasCondition = brandKeys.length || energyKeys.length || chosen.length;
      const matched = [...models.options].filter((option) => option.value && matches(
        {id: option.value, brand: option.dataset.campaignBrand || "", energy: option.dataset.campaignEnergy || ""},
        brandKeys, energyKeys, chosen,
      ));
      list.replaceChildren();
      if (!hasCondition) {
        count.textContent = "—";
        text.textContent = "請至少選一個品牌、能源別或年式，避免套用到全部車輛。";
        section.dataset.matchState = "empty";
        return;
      }
      count.textContent = `${matched.length} 個年式`;
      text.textContent = matched.length
        ? "符合目前條件（只列啟用中與已選的年式）。"
        : "條件沒有交集，沒有任何年式符合，請調整品牌、能源別或年式。";
      section.dataset.matchState = matched.length ? "ok" : "none";
      matched.slice(0, 12).forEach((option) => {
        const item = document.createElement("li");
        item.textContent = option.textContent.trim();
        list.appendChild(item);
      });
      if (matched.length > 12) {
        const more = document.createElement("li");
        more.className = "is-more";
        more.textContent = `另 ${matched.length - 12} 個年式`;
        list.appendChild(more);
      }
    }

    [brands, models, ...energies].forEach((field) => field.addEventListener("change", update));
    section.querySelector("[data-campaign-all-electric]")?.addEventListener("click", () => {
      energies.forEach((input) => { input.checked = input.value !== "gas"; });
      update();
    });
    update();
  }

  function csrfToken(form) {
    return form?.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
  }

  function initQuickCatalog(form) {
    const panel = document.querySelector("[data-quick-catalog]");
    const opener = document.querySelector("[data-quick-catalog-open]");
    if (!panel || !opener) return;
    const error = panel.querySelector("[data-quick-catalog-error]");
    const field = (name) => panel.querySelector(`[data-quick-field="${name}"]`);
    const toggle = (open) => {
      panel.hidden = !open;
      opener.setAttribute("aria-expanded", String(open));
      if (open) field("name")?.focus();
    };
    opener.addEventListener("click", () => toggle(panel.hidden));
    panel.querySelector("[data-quick-catalog-cancel]")?.addEventListener("click", () => toggle(false));
    panel.querySelector("[data-quick-catalog-save]")?.addEventListener("click", async () => {
      const body = new FormData();
      ["reward_type", "name", "unit", "unit_cost"].forEach((name) => body.append(`quick-${name}`, field(name)?.value || ""));
      body.append("quick-cost_from", document.getElementById("id_effective_from")?.value || "");
      error.hidden = true;
      let payload = {};
      try {
        const response = await fetch(panel.dataset.url, {
          method: "POST",
          body,
          headers: {"X-CSRFToken": csrfToken(form), "X-Requested-With": "XMLHttpRequest"},
          credentials: "same-origin",
        });
        payload = await response.json();
      } catch (_error) {
        payload = {ok: false, errors: ["連線失敗，請稍後再試。"]};
      }
      if (!payload.ok) {
        error.textContent = (payload.errors || ["無法新增品項。"]).join(" ");
        error.hidden = false;
        return;
      }
      const label = payload.label;
      const addOption = (select) => {
        if ([...select.options].some((option) => option.value === String(payload.id))) return;
        select.appendChild(new Option(label, payload.id));
      };
      document.querySelectorAll("select[data-reward-catalog]").forEach(addOption);
      const template = document.querySelector("[data-reward-template]");
      template?.content.querySelectorAll("select[data-reward-catalog]").forEach(addOption);
      window.dispatchEvent(new CustomEvent("dealer-reward-catalog:add", {detail: payload}));
      const empty = [...document.querySelectorAll("[data-reward-row]:not([hidden]) select[data-reward-catalog]")]
        .find((select) => !select.value);
      if (empty) {
        empty.value = String(payload.id);
        empty.dispatchEvent(new Event("change", {bubbles: true}));
      }
      ["name", "unit", "unit_cost"].forEach((name) => { if (field(name)) field(name).value = ""; });
      toggle(false);
      opener.focus();
    });
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {matches};
  if (typeof document === "undefined") return;
  const form = document.querySelector("[data-campaign-form]");
  initConditions(form?.querySelector("[data-campaign-conditions]"));
  initQuickCatalog(form);
})();
