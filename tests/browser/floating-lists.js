const modal = document.querySelector('#modal'), second = document.querySelector('#second');
document.querySelector('#open').onclick = () => modal.showModal();
const tick = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
const input = id => document.querySelector(`#${id}-search`);
const list = id => document.querySelector(`#${id}-search-options`);
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const hit = element => {
  const r = element.getBoundingClientRect();
  const x = r.left + Math.min(20, r.width / 2), y = r.top + Math.min(20, r.height / 2);
  return element.contains(document.elementFromPoint(x, y));
};
document.querySelector('#run').onclick = async () => {
  const lines = [], output = document.querySelector('#results');
  const check = async (name, fn) => { await fn(); lines.push(`PASS ${name}`); output.textContent = lines.join('\n'); };
  let nativeShow;
  try {
    await check('一般頁面：逃離 overflow / transform 容器，可點選', async () => {
      input('page-select').focus(); await tick();
      assert(list('page-select').matches(':popover-open'), '未進入頂層');
      assert(hit(list('page-select').querySelector('button')), '選項被遮住');
    });
    await check('第一個彈窗：選項在 dialog 裡、且位於其頂層', async () => {
      modal.showModal(); input('modal-select').focus(); await tick();
      assert(list('page-select').hidden, '舊選單未收起');
      assert(list('modal-select').parentNode === modal, '選項落到 dialog 外而被 inert');
      assert(list('modal-select').matches(':popover-open'), 'modal 選單未進入頂層');
      assert(hit(list('modal-select').querySelector('button')), 'modal 選項不可點選');
      assert(list('modal-select').scrollWidth <= list('modal-select').clientWidth, '選項左右溢出');
    });
    await check('搜尋與選取：寫回原欄位，單選收合', async () => {
      input('modal-select').value = 'Beta'; input('modal-select').dispatchEvent(new Event('input'));
      await tick(); list('modal-select').querySelector('[data-value="b"]').click(); await tick();
      assert(document.querySelector('#modal-select').value === 'b', '值未寫回');
      assert(list('modal-select').hidden, '選取後未收合');
    });
    await check('Escape 只關選項，不關尚未儲存的彈窗', async () => {
      input('modal-select').click(); await tick();
      input('modal-select').dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true, cancelable:true}));
      assert(modal.open && list('modal-select').hidden, 'Escape 關閉層級錯誤');
    });
    await check('最近輸入建議也在所屬彈窗頂層', async () => {
      localStorage.setItem(`dmis-recent-field:v1:qa-user:${location.pathname}:memo`, JSON.stringify(['測試備註']));
      document.querySelector('#memo').focus(); await tick();
      const recent = document.querySelector('.recent-field-values');
      assert(recent.parentNode === modal && recent.matches(':popover-open'), '最近輸入層級錯誤');
      assert(hit(recent.querySelector('button')), '最近輸入被遮住');
      recent.querySelector('button').click(); assert(document.querySelector('#memo').value === '測試備註', '最近輸入選取失敗');
    });
    await check('關閉彈窗清理選項，第二彈窗複選仍正常', async () => {
      input('modal-select').focus(); await tick(); modal.close(); await tick();
      assert(list('modal-select').hidden, '關窗後殘留選項');
      second.showModal(); input('multi').focus(); await tick();
      list('multi').querySelector('[data-value="a"]').click(); await tick();
      assert(document.querySelector('#multi').selectedOptions.length === 1 && !list('multi').hidden, '複選操作失敗');
      assert(list('multi').parentNode === second && hit(list('multi').querySelector('[data-value="b"]')), '第二彈窗層級錯誤');
      assert(getComputedStyle(list('multi').querySelector('[data-value="a"]'), '::before').content !== 'none', '複選勾選樣式遺失');
      second.close(); await tick();
    });
    await check('無 Popover API 的相容模式仍在 dialog 內', async () => {
      nativeShow = HTMLElement.prototype.showPopover; HTMLElement.prototype.showPopover = undefined;
      modal.showModal(); input('modal-select').focus(); await tick();
      assert(list('modal-select').parentNode === modal && !list('modal-select').hasAttribute('popover'), '相容模式錯誤');
      assert(hit(list('modal-select').querySelector('button')), '相容模式仍被遮住');
      modal.close(); await tick(); HTMLElement.prototype.showPopover = nativeShow;
    });
    await check('欄位被動態移除後不殘留浮動選項', async () => {
      const field = input('page-select'), parent = field.parentNode, sibling = field.nextSibling;
      field.focus(); await tick(); field.remove(); await tick();
      assert(list('page-select').hidden, '移除欄位後仍殘留選項');
      parent.insertBefore(field, sibling);
    });
    output.textContent += '\n全部通過';
  } catch (error) { output.textContent += `\nFAIL ${error.message}`; }
  finally { if (nativeShow) HTMLElement.prototype.showPopover = nativeShow; modal.close(); second.close(); }
};
