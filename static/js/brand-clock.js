(function () {
  var clock = document.querySelector('[data-brand-clock]');
  if (!clock) return;
  var weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  function pad(n) { return n < 10 ? '0' + n : String(n); }
  function tick() {
    var d = new Date();
    clock.textContent = d.getFullYear() + '/' + pad(d.getMonth() + 1) + '/' + pad(d.getDate()) +
      '（' + weekdays[d.getDay()] + '） ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    clock.setAttribute('datetime', d.toISOString());
  }
  tick();
  setInterval(tick, 1000);
})();
