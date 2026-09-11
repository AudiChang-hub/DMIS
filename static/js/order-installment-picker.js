/* 選單只負責明確選取；載入方案絕不覆蓋原訂單金額。 */
((root) => {
  const companyNames = options => [...new Set(options.map(option => option.company))];
  const companyOptions = (options, company) => options.filter(option => option.company === company);
  function create(config) {
    const doc = config.document || root.document;
    const fetcher = config.fetcher || root.fetch.bind(root);
    const byId = id => doc.getElementById(id);
    const company = byId('installment-company-choice');
    const periods = byId('installment-period-choice');
    const toggle = byId('installment-manual-toggle');
    const applyButton = byId('installment-apply');
    const manualFields = [...doc.querySelectorAll('[data-installment-manual]')];
    const inputs = {
      company: byId('id_installment_company'), periods: byId('id_installment_periods'),
      monthly_amount: byId('id_installment_monthly'), opening_fee: byId('id_installment_opening_fee'),
    };
    let options = [], manual = true, ticket = 0, controller = null, versionHint = '';
    function add(select, value, label) {
      const option = doc.createElement('option');
      option.value = String(value);
      option.textContent = label;
      select.appendChild(option);
    }
    function reset(select, label) { select.replaceChildren(); add(select, '', label); }
    function emit(input, value) {
      input.value = String(value ?? '');
      input.dispatchEvent(new Event('input', {bubbles: true}));
    }
    function syncRequired() {
      const enabled = config.paymentType.value === 'installment';
      company.required = periods.required = enabled && !manual;
      inputs.company.required = inputs.periods.required = enabled && manual;
      applyButton.disabled = !options.some(option => option.company === company.value && String(option.periods) === periods.value);
    }
    function setManual(value) {
      manual = value;
      manualFields.forEach(field => { field.hidden = !value; });
      toggle.setAttribute('aria-expanded', String(value));
      toggle.textContent = value ? '改用車型方案' : '保留原值／人工調整';
      toggle.disabled = options.length === 0;
      syncRequired();
    }
    function renderPeriods(selected = '') {
      reset(periods, company.value ? '請選擇期數' : '請先選擇分期公司');
      companyOptions(options, company.value).forEach(option => {
        add(periods, option.periods, `${option.periods} 期 · 每期 $${Number(option.monthly_amount).toLocaleString('zh-TW')}`);
      });
      periods.value = String(selected);
      periods.disabled = !company.value;
    }
    function render(preserve) {
      reset(company, options.length ? '請選擇分期公司' : '此日期無有效車型方案');
      companyNames(options).forEach(name => add(company, name, name));
      const found = preserve && options.find(option => option.company === inputs.company.value && Number(option.periods) === Number(inputs.periods.value));
      if (found) company.value = found.company;
      else if (companyNames(options).length === 1) company.value = options[0].company;
      renderPeriods(found ? found.periods : '');
      company.disabled = !options.length;
      const historical = preserve && (inputs.company.value || Number(inputs.periods.value) > 0);
      setManual(!options.length || Boolean(historical && !found));
      config.hint.textContent = versionHint + (historical
        ? '保留原訂單公司、期數與金額；明確選擇方案後才會重新帶入。'
        : options.length ? '請選擇公司與期數，帶入每期金額及開辦費。' : '沒有有效方案，可保留原值或人工填寫；不套用今天的其他版本。');
    }
    function apply() {
      const option = options.find(item => item.company === company.value && String(item.periods) === periods.value);
      if (!option) return;
      for (const [key, input] of Object.entries(inputs)) emit(input, option[key]);
      setManual(false);
      const bonus = Number(option.extra_disbursement_bonus || 0);
      config.hint.textContent = `${versionHint}已選取 ${option.company}／${option.periods} 期；每期金額與開辦費已帶入${bonus ? `，預估撥款另含獎金 $${bonus.toLocaleString('zh-TW')}` : ''}，仍可依本單條件調整。`;
    }
    company.addEventListener('change', () => {
      renderPeriods();
      setManual(false);
      emit(inputs.company, company.value);
      emit(inputs.periods, '');
      config.hint.textContent = `${versionHint}請選擇這間公司的期數，完成後才會帶入金額。`;
    });
    periods.addEventListener('change', apply);
    applyButton.addEventListener('click', apply);
    toggle.addEventListener('click', () => {
      if (manual) {
        setManual(false);
        config.hint.textContent = `${versionHint}請選擇公司與期數；未選取前不更改原值。`;
      } else {
        setManual(true);
        config.hint.textContent = `${versionHint}人工調整模式：保留現有內容，不自動套用車型方案。`;
      }
    });
    async function load({force = false} = {}) {
      const current = ++ticket;
      controller?.abort();
      controller = new AbortController();
      const requestController = controller;
      const model = config.vehicleModel.value;
      options = [];
      company.disabled = periods.disabled = true;
      applyButton.disabled = true;
      config.hint.textContent = '正在讀取訂單日期適用的分期方案…';
      if (!model) { versionHint = ''; render(!force); return; }
      const params = new URLSearchParams({vehicle_model: model});
      if (config.orderId) params.set('order_id', config.orderId);
      const timeout = setTimeout(() => requestController.abort(), 10000);
      try {
        const response = await fetcher(`${config.endpoint}?${params}`, {signal: requestController.signal});
        const data = await response.json();
        if (current !== ticket || model !== config.vehicleModel.value) return;
        if (!response.ok) throw new Error(data.error || '無法讀取分期方案');
        options = data.options || [];
        versionHint = `依訂單日 ${data.order_date || ''}${data.version ? `／方案生效日 ${data.version.effective_from}` : ''}。`;
        render(!force);
      } catch (error) {
        if (current !== ticket) return;
        versionHint = '';
        render(true);
        config.hint.textContent = '分期方案讀取失敗或逾時，已保留原值；可人工填寫，或重新選擇付款方式重試。';
      } finally {
        clearTimeout(timeout);
      }
    }
    root.addEventListener?.('pagehide', () => { ++ticket; controller?.abort(); });
    return {load, syncRequired};
  }
  const api = {companyNames, companyOptions, create};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DmisInstallmentPicker = api;
})(globalThis);
