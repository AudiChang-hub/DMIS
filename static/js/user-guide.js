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

  // 從各畫面開啟時停在頁首，只提供目前畫面相關主題的捷徑，不自動捲動。
  const contextTopic = new URLSearchParams(window.location.search).get("topic");
  const contextTarget = contextTopic && /^[a-z0-9-]+$/.test(contextTopic) ? document.getElementById(contextTopic) : null;
  const contextBox = document.querySelector("[data-guide-context]");
  const contextLink = document.querySelector("[data-guide-context-link]");
  if (contextTarget && contextBox && contextLink) {
    contextLink.href = `#${contextTopic}`;
    contextLink.textContent = contextTarget.querySelector("h2")?.textContent.trim() || "查看說明";
    contextLink.addEventListener("click", () => {
      if (search && search.value) {
        search.value = "";
        filterTopics();
      }
    });
    contextBox.hidden = false;
  }
  if (window.location.hash) {
    window.setTimeout(() => document.querySelector(window.location.hash)?.scrollIntoView(), 80);
  }
  filterTopics();
})();
