(() => {
  const search = document.querySelector("[data-guide-search]");
  const topics = [...document.querySelectorAll("[data-guide-topic]")];
  const empty = document.querySelector("[data-guide-empty]");
  const count = document.querySelector("[data-guide-count]");
  const printButton = document.querySelector("[data-print-guide]");

  function normalize(value) {
    return value.toLocaleLowerCase("zh-Hant").replace(/\s+/g, " ").trim();
  }

  function filterTopics() {
    const query = normalize(search?.value || "");
    let visible = 0;
    topics.forEach((topic) => {
      const matches = !query || normalize(topic.textContent).includes(query);
      topic.hidden = !matches;
      if (matches) visible += 1;
    });
    if (empty) empty.hidden = visible !== 0;
    if (count) count.textContent = query ? `找到 ${visible} 個相關主題` : `共 ${topics.length} 個操作主題`;
  }

  search?.addEventListener("input", filterTopics);
  printButton?.addEventListener("click", () => window.print());

  if (window.location.hash) {
    window.setTimeout(() => document.querySelector(window.location.hash)?.scrollIntoView(), 80);
  }
  filterTopics();
})();
