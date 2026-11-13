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

    function hide() {
      tip.hidden = true;
    }

    root.addEventListener("pointermove", function (event) {
      var target = event.target.closest ? event.target.closest("[data-ops-tip]") : null;
      if (target) show(event, target.getAttribute("data-ops-tip"));
      else hide();
    });
    root.addEventListener("pointerleave", hide);
    window.addEventListener("scroll", hide, { passive: true });

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
