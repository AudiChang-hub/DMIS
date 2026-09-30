(function () {
  'use strict';
  function choices(rows, field, brand, name, energy = '') {
    return [...new Set(rows.filter(row => (!brand || row.brand === brand) &&
      (field === 'name' || !name || row.name === name) && (!energy || row.energy_type === energy)).map(row => row[field]).filter(Boolean))];
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
  const energy = form.elements.energy;
  function replace(select, values, label) {
    select.replaceChildren(new Option(label, ''), ...values.map(value => new Option(value, value)));
  }
  brand.addEventListener('change', () => {
    replace(name, choices(rows, 'name', brand.value, '', energy?.value), '全部車型');
    replace(number, choices(rows, 'model_number', brand.value, '', energy?.value), '全部型號');
  });
  name.addEventListener('change', () => {
    replace(number, choices(rows, 'model_number', brand.value, name.value, energy?.value), '全部型號');
  });
  // 選車頁：下拉選單一變更就在背景取得結果，只替換結果區，不重新整理整頁、不跳動。
  const results = document.querySelector('[data-catalog-results]');
  if (form.hasAttribute('data-auto-submit') && results) {
    let pending = null;
    async function load(url, {scrollToResults = false} = {}) {
      pending?.abort();
      const controller = new AbortController();
      pending = controller;
      results.setAttribute('aria-busy', 'true');
      results.style.opacity = '0.6';
      try {
        const response = await fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}, signal: controller.signal});
        if (!response.ok) throw new Error(String(response.status));
        const page = new DOMParser().parseFromString(await response.text(), 'text/html');
        const next = page.querySelector('[data-catalog-results]');
        if (!next) throw new Error('missing results');
        results.innerHTML = next.innerHTML;
        history.replaceState(null, '', url);
        if (scrollToResults) results.scrollIntoView({block: 'start', behavior: 'smooth'});
      } catch (error) {
        if (error.name === 'AbortError') return;
        window.location.assign(url);
      } finally {
        if (pending === controller) {
          pending = null;
          results.removeAttribute('aria-busy');
          results.style.opacity = '';
        }
      }
    }
    const filterUrl = () => {
      const params = new URLSearchParams(new FormData(form));
      [...params.keys()].forEach(key => { if (!params.get(key)) params.delete(key); });
      const query = params.toString();
      return form.action.split('?')[0] + (query ? `?${query}` : '');
    };
    form.addEventListener('change', event => {
      if (event.target.matches('select')) load(filterUrl());
    });
    form.addEventListener('submit', event => { event.preventDefault(); load(filterUrl()); });
    form.querySelector('[data-catalog-clear]')?.addEventListener('click', event => {
      event.preventDefault();
      if (energy) energy.value = '';
      brand.value = '';
      brand.dispatchEvent(new Event('change', {bubbles: true}));
    });
    results.addEventListener('click', event => {
      const link = event.target.closest('.site-pagination a[href]');
      if (!link) return;
      event.preventDefault();
      load(link.href, {scrollToResults: true});
    });
  }
  energy?.addEventListener('change', () => {
    const previousName = name.value, previousNumber = number.value;
    const names = choices(rows, 'name', brand.value, '', energy.value);
    replace(name, names, '全部車型');
    if (names.includes(previousName)) name.value = previousName;
    const numbers = choices(rows, 'model_number', brand.value, name.value, energy.value);
    replace(number, numbers, '全部型號');
    if (numbers.includes(previousNumber)) number.value = previousNumber;
  });
}());
