(() => {
  const rows = () => Array.from(document.querySelectorAll("[data-assignment-row]"));
  const assigneeValue = row => row.querySelector("[data-assignee-select]")?.value || "";
  const orderInput = row => row.querySelector("[data-order-input]");
  const orderLabel = row => row.querySelector("[data-order-label]");
  const dragHandle = row => row.querySelector("[data-drag-handle]");
  const rowChecks = () => rows().map(row => row.querySelector("[data-row-select]")).filter(Boolean);

  function updateSelection() {
    const checks = rowChecks();
    const selected = checks.filter(check => check.checked);
    const selectAll = document.querySelector("[data-select-all]");
    const count = document.querySelector("[data-selected-count]");
    const assignButton = document.querySelector("[data-assign-selected]");
    if (selectAll) {
      selectAll.checked = checks.length > 0 && selected.length === checks.length;
      selectAll.indeterminate = selected.length > 0 && selected.length < checks.length;
    }
    if (count) count.textContent = selected.length ? `已選 ${selected.length} 家` : "尚未選取";
    if (assignButton) assignButton.disabled = selected.length === 0;
  }

  function updateRowAssignment(row, newAssignee) {
    const previousAssignee = row.dataset.assigneeId || "";
    const input = orderInput(row);
    const label = orderLabel(row);
    const handle = dragHandle(row);
    row.dataset.assigneeId = newAssignee;
    if (newAssignee === (row.dataset.originalAssigneeId || "")) {
      const originalOrder = Number(row.dataset.originalOrder || 0);
      input.value = String(originalOrder);
      label.textContent = originalOrder ? `第 ${originalOrder} 站` : "尚未排序";
      handle.disabled = !originalOrder;
      handle.draggable = Boolean(originalOrder);
      return;
    }
    if (!newAssignee) {
      input.value = "0";
      label.textContent = "尚未排序";
      handle.disabled = true;
      handle.draggable = false;
      return;
    }
    if (previousAssignee !== newAssignee) {
      input.value = "0";
      label.textContent = "儲存後排最後";
      handle.disabled = true;
      handle.draggable = false;
    }
  }

  function sortableRows(row) {
    const assignee = assigneeValue(row);
    if (!assignee) return [];
    return rows().filter(candidate => (
      assigneeValue(candidate) === assignee && Number(orderInput(candidate)?.value || 0) > 0
    ));
  }

  function applyOrderSlots(state) {
    sortableRows(state.row).forEach((row, index) => {
      const value = state.slots[index];
      if (!value) return;
      orderInput(row).value = String(value);
      orderLabel(row).textContent = `第 ${value} 站`;
    });
  }

  function beginDrag(row) {
    const matching = sortableRows(row);
    if (matching.length < 2) return null;
    const slots = matching
      .map(candidate => Number(orderInput(candidate).value || 0))
      .sort((left, right) => left - right);
    row.classList.add("is-dragging");
    return {row, slots};
  }

  function placeAtPointer(state, target, clientY) {
    if (!target || target === state.row || assigneeValue(target) !== assigneeValue(state.row)) return;
    if (Number(orderInput(target)?.value || 0) <= 0) return;
    const body = state.row.parentElement;
    const rect = target.getBoundingClientRect();
    body.insertBefore(state.row, clientY > rect.top + rect.height / 2 ? target.nextSibling : target);
    applyOrderSlots(state);
  }

  function finishDrag(state) {
    if (!state) return;
    state.row.classList.remove("is-dragging");
    applyOrderSlots(state);
    dragHandle(state.row)?.focus({preventScroll: true});
  }

  const selectAll = document.querySelector("[data-select-all]");
  selectAll?.addEventListener("change", () => {
    rowChecks().forEach(check => { check.checked = selectAll.checked; });
    updateSelection();
  });

  document.addEventListener("change", event => {
    const rowCheck = event.target.closest("[data-row-select]");
    if (rowCheck) {
      updateSelection();
      return;
    }
    const select = event.target.closest("[data-assignee-select]");
    if (select) updateRowAssignment(select.closest("[data-assignment-row]"), select.value);
  });

  let mouseDrag = null;
  document.querySelectorAll("[data-drag-handle]").forEach(handle => {
    handle.draggable = !handle.disabled;
    handle.addEventListener("dragstart", event => {
      if (handle.disabled) return event.preventDefault();
      mouseDrag = beginDrag(handle.closest("[data-assignment-row]"));
      if (!mouseDrag) return event.preventDefault();
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", "route-order");
    });
    handle.addEventListener("dragend", () => {
      finishDrag(mouseDrag);
      mouseDrag = null;
    });
    handle.addEventListener("keydown", event => {
      if (!["ArrowUp", "ArrowDown"].includes(event.key) || handle.disabled) return;
      const row = handle.closest("[data-assignment-row]");
      const matching = sortableRows(row);
      const currentIndex = matching.indexOf(row);
      const targetIndex = event.key === "ArrowUp" ? currentIndex - 1 : currentIndex + 1;
      const target = matching[targetIndex];
      if (!target) return;
      event.preventDefault();
      const state = beginDrag(row);
      if (event.key === "ArrowUp") row.parentElement.insertBefore(row, target);
      else row.parentElement.insertBefore(target, row);
      finishDrag(state);
    });

    let touchDrag = null;
    handle.addEventListener("pointerdown", event => {
      if (event.pointerType === "mouse" || handle.disabled) return;
      touchDrag = beginDrag(handle.closest("[data-assignment-row]"));
      if (!touchDrag) return;
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
    });
    handle.addEventListener("pointermove", event => {
      if (!touchDrag) return;
      event.preventDefault();
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest("[data-assignment-row]");
      placeAtPointer(touchDrag, target, event.clientY);
      if (event.clientY < 110) window.scrollBy({top: -18, behavior: "auto"});
      else if (event.clientY > window.innerHeight - 110) window.scrollBy({top: 18, behavior: "auto"});
    });
    const endTouchDrag = event => {
      if (!touchDrag) return;
      event.preventDefault();
      finishDrag(touchDrag);
      touchDrag = null;
    };
    handle.addEventListener("pointerup", endTouchDrag);
    handle.addEventListener("pointercancel", endTouchDrag);
  });

  document.addEventListener("dragover", event => {
    if (!mouseDrag) return;
    const target = event.target.closest("[data-assignment-row]");
    if (!target || assigneeValue(target) !== assigneeValue(mouseDrag.row)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    placeAtPointer(mouseDrag, target, event.clientY);
  });
  document.addEventListener("drop", event => {
    if (mouseDrag) event.preventDefault();
  });

  updateSelection();
})();
