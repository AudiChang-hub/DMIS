(() => {
  const block = document.querySelector('[data-assisted-company]');
  const data = document.getElementById('assisted-companies');
  if (!block || !data) return;
  const companies = JSON.parse(data.textContent);
  const source = document.getElementById('id_source');
  const kind = document.getElementById('id_source_type');
  const confirmed = document.getElementById('id_assisted_company_confirmed');
  const revision = document.getElementById('id_assisted_company_revision');
  function refresh(reset) {
    block.hidden = kind.value !== 'dealer';
    const company = companies[source.value];
    block.querySelector('[data-assisted-company-summary]').textContent = company
      ? `${company.legal_name}｜${company.address}｜電話 ${company.phone}｜統編 ${company.tax_id}`
      : '請先選擇車行；若未設定公司資料，請洽 admin 完成設定。';
    if (reset || String(company?.revision ?? '') !== revision.value) confirmed.checked = false;
    revision.value = company ? String(company.revision) : '';
    confirmed.required = !block.hidden;
  }
  source.addEventListener('change', () => refresh(true));
  kind.addEventListener('change', () => refresh(true));
  refresh(false);
})();
