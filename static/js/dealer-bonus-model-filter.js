(() => {
  // 品牌鍵由伺服器 casefold 產生，前後端使用同一組名稱比對。
  const matchesModel = (model, brands, energy) =>
    (!brands.length || brands.includes(model.brand)) && (!energy || model.energy === energy);

  function initModelFilters(form) {
    if (!form || form.hasAttribute('data-conditions-locked')) return;
    const brands = form.querySelector('[name="brands"]');
    const energy = form.querySelector('[name="energy_type"]');
    const models = form.querySelector('[name="vehicle_models"]');
    const notice = form.querySelector('[data-model-conflict]');
    const detail = form.querySelector('[data-model-conflict-detail]');
    const confirm = form.querySelector('[data-model-conflict-confirm]');
    const restore = form.querySelector('[data-model-conflict-restore]');
    const status = form.querySelector('[data-model-filter-status]');
    if (!brands || !energy || !models || !notice) return;
    const selected = select => [...select.options].filter(option => option.selected && option.value);
    const snapshot = () => ({brands: selected(brands).map(option => option.value), energy: energy.value});
    let accepted = null;
    let conflicts = [];

    function update() {
      const keys = selected(brands).map(option => option.dataset.bonusBrand);
      [...models.options].forEach(option => {
        const hidden = !matchesModel({brand: option.dataset.bonusBrand, energy: option.dataset.bonusEnergy}, keys, energy.value);
        if (option.hidden !== hidden) option.hidden = hidden;
      });
      conflicts = selected(models).filter(option => option.hidden);
      notice.hidden = !conflicts.length;
      const count = [...models.options].filter(option => !option.hidden && option.value).length;
      status.textContent = count ? `可選 ${count} 個車型；未指定即不限車型。` : '沒有符合條件的車型，請調整品牌或能源別。';
      if (!conflicts.length) {
        accepted = snapshot();
        return;
      }
      const clearsAll = conflicts.length === selected(models).length;
      detail.textContent = `${conflicts.map(option => option.textContent.trim()).join('、')}。${clearsAll ? '移除後將變成「不限車型」，獎金會適用所有符合品牌與能源的車型。' : '確認後只移除不符車型，其餘選取會保留。'}尚未儲存，請確認或還原條件。`;
      confirm.textContent = clearsAll ? '移除並設為不限車型' : '移除不符車型';
      restore.hidden = !accepted;
    }

    [brands, energy, models].forEach(field => field.addEventListener('change', update));
    confirm.addEventListener('click', () => {
      conflicts.forEach(option => { option.selected = false; });
      models.dispatchEvent(new Event('change', {bubbles: true}));
    });
    restore.addEventListener('click', () => {
      if (!accepted) return;
      const previous = accepted;
      [...brands.options].forEach(option => { option.selected = previous.brands.includes(option.value); });
      energy.value = previous.energy;
      brands.dispatchEvent(new Event('change', {bubbles: true}));
      energy.dispatchEvent(new Event('change', {bubbles: true}));
    });
    form.addEventListener('submit', event => {
      update();
      if (!conflicts.length) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      notice.focus({preventScroll: true});
      notice.scrollIntoView({block: 'nearest', behavior: 'instant'});
    }, true);
    update();
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {matchesModel, initModelFilters};
  if (typeof document !== 'undefined') initModelFilters(document.querySelector('[data-bonus-rule-form]'));
})();
