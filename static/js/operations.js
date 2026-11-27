// 營運總表駕駛艙（T-167）：走勢與結構的滑過提示、結構類別頁籤。沒有 JS 時走勢點仍有 <title> 提示，結構只顯示第一類。
(function () {
  "use strict";

  function init() {
    var root = document.querySelector("[data-ops]");
    var tip = document.querySelector("[data-ops-tooltip]");
    if (!root || !tip) return;

    function show(event, text) {
      tip.textContent = text;
      tip.hidden = false;
      var x = Math.min(event.clientX + 12, window.innerWidth - tip.offsetWidth - 16);
      var y = event.clientY - tip.offsetHeight - 12;
      tip.style.left = Math.max(16, x) + "px";
      tip.style.top = (y < 8 ? event.clientY + 16 : y) + "px";
    }

    // 捲動時每個事件都會呼叫：已經隱藏就不再寫 hidden，否則每次都觸發整頁樣式重算（T-241 量到 120 幀 373 次）。
    function hide() {
      if (!tip.hidden) tip.hidden = true;
    }

    root.addEventListener("pointermove", function (event) {
      var target = event.target.closest ? event.target.closest("[data-ops-tip]") : null;
      if (target) show(event, target.getAttribute("data-ops-tip"));
      else hide();
    });
    root.addEventListener("pointerleave", hide);
    window.addEventListener("scroll", hide, { passive: true });

    // T-303 貨卡庫齡：指到、Tab 聚焦或點一下某段（或圖例），標題右邊寫「區間 N 台・佔 %」，長條與圖例同一項標亮。
    // 滑鼠移開回到聚焦／點選中的那段；點卡片外面或焦點離開就清掉。讀螢幕軟體念每段自己的 aria-label。
    root.querySelectorAll("[data-ops-age-bar]").forEach(function (bar) {
      var card = bar.closest(".ops-card");
      var readout = card && card.querySelector("[data-ops-age-readout]");
      var legend = card && card.querySelector("[data-ops-age-legend]");
      if (!readout || !legend) return;
      var hint = readout.textContent;
      var pinned = null;
      readout.hidden = false;
      // T-304：長條下方的車型清單與表格對應列跟著換；沒有指到時回到預設那段（最久的那段）。
      var models = card.querySelector("[data-ops-age-models]");
      var fallbackGroup = models && models.querySelector("[data-ops-age-group]:not([hidden])");
      var fallback = fallbackGroup ? fallbackGroup.getAttribute("data-ops-age-group") : null;
      var leaveTimer = null;
      var hoverTimer = null;
      var hoverKey = null;

      function showModels(key) {
        if (!models) return;
        var shown = key || fallback;
        card.querySelectorAll("[data-ops-age-group]").forEach(function (item) {
          var hidden = item.getAttribute("data-ops-age-group") !== shown;
          if (item.hidden !== hidden) item.hidden = hidden;
        });
        card.querySelectorAll("[data-ops-age-row]").forEach(function (row) {
          var note = row.querySelector('[data-ops-age-group="' + shown + '"]');
          row.classList.toggle("is-age-hit", !!note);
          row.classList.toggle("is-alert", !!note && note.classList.contains("is-alert"));
        });
      }

      function activate(key) {
        var seg = key ? bar.querySelector('[data-ops-age="' + key + '"]') : null;
        bar.classList.toggle("has-active", !!seg);
        legend.classList.toggle("has-active", !!seg);
        card.querySelectorAll("[data-ops-age]").forEach(function (item) {
          item.classList.toggle("is-active", !!seg && item.getAttribute("data-ops-age") === key);
        });
        readout.textContent = "";
        showModels(seg ? key : null);
        if (!seg) {
          readout.setAttribute("data-empty", "");
          readout.textContent = hint;
          return;
        }
        readout.removeAttribute("data-empty");
        var count = document.createElement("b");
        count.textContent = seg.getAttribute("data-count") + " 台";
        readout.append(seg.getAttribute("data-label") + "　", count, "・佔 " + seg.getAttribute("data-share") + "%");
      }

      function keyOf(event) {
        var item = event.target.closest ? event.target.closest("[data-ops-age]") : null;
        return item && card.contains(item) ? item.getAttribute("data-ops-age") : null;
      }

      // 滑鼠從長條移到下方車型清單要點連結：離開後稍等再還原，進到清單就取消；
      // 已經指著某段時，路過圖例其他項要停一下才換，斜著移到清單不會被換掉。
      function revertLater() {
        clearTimeout(hoverTimer);
        clearTimeout(leaveTimer);
        leaveTimer = setTimeout(function () { hoverKey = null; activate(pinned); }, 300);
      }
      function hoverTo(key) {
        clearTimeout(hoverTimer);
        if (!key || key === hoverKey) return;
        if (hoverKey === null) {
          activate(hoverKey = key);
          return;
        }
        hoverTimer = setTimeout(function () { activate(hoverKey = key); }, 150);
      }
      if (models) {
        models.addEventListener("pointerover", function () { clearTimeout(leaveTimer); });
        models.addEventListener("pointerleave", revertLater);
        models.addEventListener("focusout", function (event) {
          if (!models.contains(event.relatedTarget) && !bar.contains(event.relatedTarget)) activate(pinned = null);
        });
      }
      [bar, legend].forEach(function (area) {
        area.addEventListener("pointerover", function (event) {
          var key = keyOf(event);
          clearTimeout(leaveTimer);
          if (!models) {
            if (key) activate(key);
            return;
          }
          hoverTo(key);
        });
        area.addEventListener("pointerleave", models ? revertLater : function () { activate(pinned); });
        area.addEventListener("click", function (event) {
          var key = keyOf(event);
          if (key) activate(hoverKey = pinned = key);
        });
      });
      bar.addEventListener("focusin", function (event) {
        var key = keyOf(event);
        if (key) activate(pinned = key);
      });
      bar.addEventListener("focusout", function (event) {
        if (!bar.contains(event.relatedTarget) && !(models && models.contains(event.relatedTarget))) activate(pinned = null);
      });
      // 鍵盤：在某段按 Enter／空白鍵，焦點移到下方這段的第一個車型連結。
      bar.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        var key = keyOf(event);
        var link = key && models && models.querySelector('[data-ops-age-group="' + key + '"] a');
        if (!link) return;
        event.preventDefault();
        activate(pinned = key);
        link.focus();
      });
      document.addEventListener("click", function (event) {
        if (pinned && !bar.contains(event.target) && !legend.contains(event.target)
            && !(models && models.contains(event.target))) activate(pinned = null);
      });
    });

    root.querySelectorAll("[role=tablist]").forEach(function (list) {
      var tabs = Array.prototype.slice.call(list.querySelectorAll("[data-ops-tab]"));
      function select(tab, focus) {
        tabs.forEach(function (item) {
          var selected = item === tab;
          item.setAttribute("aria-selected", selected ? "true" : "false");
          item.tabIndex = selected ? 0 : -1;
          var panel = document.getElementById(item.getAttribute("aria-controls"));
          if (panel) panel.hidden = !selected;
        });
        if (focus) tab.focus();
      }
      tabs.forEach(function (tab, index) {
        tab.tabIndex = tab.getAttribute("aria-selected") === "true" ? 0 : -1;
        tab.addEventListener("click", function () { select(tab, false); });
        tab.addEventListener("keydown", function (event) {
          var next = null;
          if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
          if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
          if (event.key === "Home") next = tabs[0];
          if (event.key === "End") next = tabs[tabs.length - 1];
          if (next) {
            event.preventDefault();
            select(next, true);
          }
        });
      });
    });
  }

  // T-320「怎麼算」：一次只開一張；點卡片外面或按 Esc 收起來（Esc 後焦點回到按鈕）。沒有 JS 時仍可點開、再點一次收起。
  function initHow() {
    var items = Array.prototype.slice.call(document.querySelectorAll("[data-ops-how]"));
    if (!items.length) return;
    function closeAll(except) {
      items.forEach(function (item) {
        if (item !== except && item.open) item.open = false;
      });
    }
    items.forEach(function (item) {
      item.addEventListener("toggle", function () {
        if (item.open) closeAll(item);
      });
      item.addEventListener("keydown", function (event) {
        if (event.key !== "Escape" || !item.open) return;
        item.open = false;
        var summary = item.querySelector("summary");
        if (summary) summary.focus();
      });
    });
    document.addEventListener("click", function (event) {
      if (!event.target.closest || !event.target.closest("[data-ops-how]")) closeAll(null);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initHow);
  else initHow();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
