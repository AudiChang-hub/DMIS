(() => {
  const letters = "abcdefghjkmnpqrstuvwxyz";
  const digits = "23456789";

  function securePassword() {
    const bytes = new Uint32Array(16);
    window.crypto.getRandomValues(bytes);
    const chars = Array.from(bytes.slice(0, 8), (value, index) => {
      const source = index < 2 ? digits : letters;
      return source[value % source.length];
    });
    for (let index = chars.length - 1; index > 0; index -= 1) {
      const swapIndex = bytes[8 + index] % (index + 1);
      [chars[index], chars[swapIndex]] = [chars[swapIndex], chars[index]];
    }
    return chars.join("");
  }

  document.querySelectorAll("[data-password-generator]").forEach((form) => {
    const first = form.querySelector('[name="password1"]');
    const second = form.querySelector('[name="password2"]');
    const tools = form.querySelector("[data-password-tools]");
    const output = form.querySelector("[data-generated-password]");
    if (!first || !second || !tools || !output) return;

    form.querySelector("[data-generate-password]")?.addEventListener("click", () => {
      const password = securePassword();
      first.value = password;
      second.value = password;
      output.textContent = password;
      tools.hidden = false;
    });

    form.querySelector("[data-copy-password]")?.addEventListener("click", async (event) => {
      await navigator.clipboard.writeText(output.textContent || "");
      const button = event.currentTarget;
      button.textContent = "已複製";
      window.setTimeout(() => { button.textContent = "複製密碼"; }, 1800);
    });
  });
})();
