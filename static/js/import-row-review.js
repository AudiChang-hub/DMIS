(() => {
  const editor = document.getElementById('row-editor');
  if (!editor) return;
  let interacted = false;
  ['pointerdown', 'keydown'].forEach(event => editor.addEventListener(event, () => { interacted = true; }, {once: true, capture: true}));
  const reveal = target => {
    if (!target) return;
    target.focus({preventScroll: true});
    (target.closest('.import-review-field') || target).scrollIntoView({block: 'center', behavior: 'instant'});
  };
  editor.querySelectorAll('.import-review-summary a[href^="#"], .import-review-note a[href^="#"]').forEach(link => {
    link.addEventListener('click', event => {
      const target = document.getElementById(link.getAttribute('href').slice(1));
      if (target && editor.contains(target)) { event.preventDefault(); reveal(target); }
    });
  });
  // 送出失敗優先定位真正的表單錯誤；其餘依畫面順序定位待核對欄位。
  const initialFocus = () => requestAnimationFrame(() => requestAnimationFrame(() => !interacted && reveal(
    editor.querySelector('.has-error input, .has-error select, .has-error textarea')
    || editor.querySelector('[data-import-review-primary]')
    || editor.querySelector('[data-import-review-field]')
    || editor.querySelector('.import-review-summary')
  )));
  if (document.readyState === 'complete') initialFocus();
  else window.addEventListener('load', initialFocus, {once: true});
})();
