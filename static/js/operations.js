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

      function activate(key) {
        var seg = key ? bar.querySelector('[data-ops-age="' + key + '"]') : null;
        bar.classList.toggle("has-active", !!seg);
        legend.classList.toggle("has-active", !!seg);
        card.querySelectorAll("[data-ops-age]").forEach(function (item) {
          item.classList.toggle("is-active", !!seg && item.getAttribute("data-ops-age") === key);
        });
        readout.textContent = "";
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

      [bar, legend].forEach(function (area) {
        area.addEventListener("pointerover", function (event) {
          var key = keyOf(event);
          if (key) activate(key);
        });
        area.addEventListener("pointerleave", function () { activate(pinned); });
        area.addEventListener("click", function (event) {
          var key = keyOf(event);
          if (key) activate(pinned = key);
        });
      });
      bar.addEventListener("focusin", function (event) {
        var key = keyOf(event);
        if (key) activate(pinned = key);
      });
      bar.addEventListener("focusout", function (event) {
        if (!bar.contains(event.relatedTarget)) activate(pinned = null);
      });
      document.addEventListener("click", function (event) {
        if (pinned && !bar.contains(event.target) && !legend.contains(event.target)) activate(pinned = null);
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

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
