/**
 * 價格表水平欄位凍結
 * 動態量測前 FREEZE_COUNT 欄的寬度，注入 CSS 讓水平捲動時左側欄位固定。
 */
(function () {
    'use strict';

    var FREEZE_COUNT = 4;          // checkbox + 機種 + 型式 + 年份
    var TREE_CLS = 'dms_pricelist_tree';
    var STYLE_ID = 'dms-pricelist-col-freeze';

    function injectFreezeStyle(lefts) {
        var el = document.getElementById(STYLE_ID);
        if (!el) {
            el = document.createElement('style');
            el.id = STYLE_ID;
            document.head.appendChild(el);
        }
        el.textContent = lefts.map(function (left, i) {
            return (
                '.' + TREE_CLS + ' table th:nth-child(' + (i + 1) + '),\n' +
                '.' + TREE_CLS + ' table td:nth-child(' + (i + 1) + ') {\n' +
                '    position: sticky !important;\n' +
                '    left: ' + left + 'px !important;\n' +
                '}'
            );
        }).join('\n');
    }

    function tryFreeze() {
        var tree = document.querySelector('.' + TREE_CLS);
        if (!tree) return;
        var table = tree.querySelector('table');
        if (!table) return;
        var headerRow = table.querySelector('thead tr');
        if (!headerRow) return;
        var ths = Array.prototype.slice.call(headerRow.querySelectorAll('th'));
        if (ths.length < FREEZE_COUNT) return;

        requestAnimationFrame(function () {
            var lefts = [];
            var acc = 0;
            for (var i = 0; i < FREEZE_COUNT; i++) {
                var w = ths[i].getBoundingClientRect().width;
                if (w === 0) {
                    // 版面未就緒，延遲重試
                    setTimeout(tryFreeze, 80);
                    return;
                }
                lefts.push(acc);
                acc += w;
            }
            injectFreezeStyle(lefts);
        });
    }

    // 監聽 DOM 變化，待價格表渲染後套用凍結
    var mo = new MutationObserver(function () {
        if (document.querySelector('.' + TREE_CLS)) {
            tryFreeze();
        }
    });

    mo.observe(document.documentElement, { childList: true, subtree: true });
}());
