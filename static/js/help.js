// 使用說明（T-197）：首頁搜尋與角色篩選、文章頁列印。資料來自頁面內的 #help-index。
(() => {
  document.querySelector("[data-help-print]")?.addEventListener("click", () => window.print());

  const home = document.querySelector("[data-help-home]");
  const indexNode = document.getElementById("help-index");
  if (!home || !indexNode) return;
  const index = JSON.parse(indexNode.textContent);
  const input = home.querySelector("[data-help-search]");
  const results = home.querySelector("[data-help-results]");
  const list = home.querySelector("[data-help-results-list]");
  const count = home.querySelector("[data-help-results-count]");
  const empty = home.querySelector("[data-help-empty]");
  const browse = [...home.querySelectorAll("[data-help-groups], .help-discover, .help-start, .help-context")];

  const normalize = (value) => (value || "").toLocaleLowerCase("zh-Hant").replace(/\s+/g, " ").trim();
  const articleUrl = (slug, hash = "") => home.dataset.helpArticleUrl.replace("SLUG", slug) + hash;

  function highlighted(text, terms) {
    const fragment = document.createDocumentFragment();
    const lower = text.toLocaleLowerCase("zh-Hant");
    let at = 0;
    while (at < text.length) {
      let next = -1;
      let size = 0;
      for (const term of terms) {
        const found = lower.indexOf(term, at);
        if (found !== -1 && (next === -1 || found < next)) { next = found; size = term.length; }
      }
      if (next === -1) { fragment.append(text.slice(at)); break; }
      fragment.append(text.slice(at, next));
      const mark = document.createElement("mark");
      mark.textContent = text.slice(next, next + size);
      fragment.append(mark);
      at = next + size;
    }
    return fragment;
  }

  function snippet(text, terms) {
    const lower = text.toLocaleLowerCase("zh-Hant");
    const first = Math.min(...terms.map((term) => lower.indexOf(term)).filter((at) => at >= 0));
    if (!Number.isFinite(first)) return text.slice(0, 80);
    const start = Math.max(0, first - 30);
    return `${start ? "…" : ""}${text.slice(start, start + 110)}${start + 110 < text.length ? "…" : ""}`;
  }

  function entry(href, label, title, body, terms) {
    const link = document.createElement("a");
    link.className = "help-result";
    link.href = href;
    const kind = document.createElement("span");
    kind.textContent = label;
    const heading = document.createElement("strong");
    heading.append(highlighted(title, terms));
    const text = document.createElement("p");
    text.append(highlighted(body, terms));
    link.append(kind, heading, text);
    return link;
  }

  function search() {
    const query = normalize(input.value);
    const searching = query.length > 0;
    browse.forEach((node) => { node.hidden = searching; });
    results.hidden = !searching;
    list.replaceChildren();
    if (!searching) return;
    const terms = query.split(" ").filter(Boolean);
    const hits = (text) => terms.every((term) => normalize(text).includes(term));
    let articles = 0;
    let faqs = 0;
    for (const item of index) {
      if (hits(`${item.title} ${item.when} ${item.text}`)) {
        articles += 1;
        const body = hits(item.when) ? item.when : snippet(item.text, terms);
        list.append(entry(articleUrl(item.slug), item.group, item.title, body, terms));
      }
      for (const faq of item.faqs) {
        if (hits(`${faq.q} ${faq.a}`)) {
          faqs += 1;
          list.append(entry(articleUrl(item.slug, "#help-faq"), `常見問題・${item.title}`, faq.q, faq.a, terms));
        }
      }
    }
    count.textContent = `「${input.value.trim()}」找到 ${articles} 篇、${faqs} 則常見問題`;
    empty.hidden = articles + faqs > 0;
  }

  input?.addEventListener("input", search);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target.closest("input, textarea, select, [contenteditable]")) return;
    event.preventDefault();
    input?.focus();
  });

})();
