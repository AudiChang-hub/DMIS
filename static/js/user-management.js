(() => {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  const symbols = "!@#$%";

  function securePassword() {
    const bytes = new Uint32Array(28);
    window.crypto.getRandomValues(bytes);
    const chars = Array.from(bytes.slice(0, 14), (value, index) => {
      const source = index < 2 ? symbols : alphabet;
      return source[value % source.length];
    });
    for (let index = chars.length - 1; index > 0; index -= 1) {
      const swapIndex = bytes[14 + index] % (index + 1);
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
      first.type = "text";
      second.type = "text";
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
