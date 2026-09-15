(function () {
  'use strict';
  function choices(rows, field, brand, name) {
    return [...new Set(rows.filter(row => (!brand || row.brand === brand) &&
      (field === 'name' || !name || row.name === name)).map(row => row[field]).filter(Boolean))];
  }
  if (typeof module !== 'undefined') module.exports = { choices };
  if (typeof document === 'undefined') return;
  const form = document.querySelector('[data-catalog-filters]');
  const source = document.getElementById('catalog-filter-options');
  if (!form || !source) return;
  const rows = JSON.parse(source.textContent);
  const brand = form.elements.brand;
  const name = form.elements.model_name;
  const number = form.elements.model_number;
  function replace(select, values, label) {
    select.replaceChildren(new Option(label, ''), ...values.map(value => new Option(value, value)));
  }
  brand.addEventListener('change', () => {
    replace(name, choices(rows, 'name', brand.value, ''), '全部車型');
    replace(number, choices(rows, 'model_number', brand.value, ''), '全部型號');
  });
  name.addEventListener('change', () => {
    replace(number, choices(rows, 'model_number', brand.value, name.value), '全部型號');
  });
}());
