document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".delivery-completion-form").forEach((form) => {
    const conditionInputs = Array.from(
      form.querySelectorAll('[name="vehicle_condition_note"]')
    );
    const damageDetails = form.querySelector("[data-delivery-damage-details]");
    if (!conditionInputs.length || !damageDetails) return;

    const syncDamageDetails = () => {
      const selected = conditionInputs.find((input) => input.checked);
      damageDetails.hidden = selected?.value !== "發現刮傷或損壞";
    };

    conditionInputs.forEach((input) => {
      input.addEventListener("change", syncDamageDetails);
    });
    syncDamageDetails();
  });
});
