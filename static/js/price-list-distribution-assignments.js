(() => {
  const rows = () => Array.from(document.querySelectorAll("[data-assignment-row]"));
  const assigneeValue = row => row.querySelector("[data-assignee-select]")?.value || "";
  const orderInput = row => row.querySelector("[data-order-input]");
  const orderLabel = row => row.querySelector("[data-order-label]");
  const dragHandle = row => row.querySelector("[data-drag-handle]");
  const rowChecks = () => rows().map(row => row.querySelector("[data-row-select]")).filter(Boolean);
  const dragAnnouncer = document.querySelector("[data-drag-announcer]");

  function dealerName(row) {
    return row.querySelector('td[data-label="車行"] strong')?.textContent.trim() || "這家車行";
  }

  function clearDropMarker() {
    rows().forEach(row => row.classList.remove("is-drop-before", "is-drop-after"));
  }

  function updateRowDirty(row) {
    const changed = (
      assigneeValue(row) !== (row.dataset.originalAssigneeId || "")
      || Number(orderInput(row)?.value || 0) !== Number(row.dataset.originalOrder || 0)
    );
    row.classList.toggle("has-unsaved-change", changed);
    return changed;
  }

  function updateActions() {
    const checks = rowChecks();
    const selected = checks.filter(check => check.checked);
    const dirty = rows().filter(updateRowDirty);
    const selectAll = document.querySelector("[data-select-all]");
    const count = document.querySelector("[data-selected-count]");
    const toolbar = document.querySelector("[data-selection-toolbar]");
    const idleHint = document.querySelector("[data-idle-hint]");
    const batchControls = document.querySelector("[data-batch-controls]");
    const saveControls = document.querySelector("[data-save-controls]");
    const dirtyCount = document.querySelector("[data-dirty-count]");
    const dirtyNote = document.querySelector("[data-batch-dirty-note]");
    const assignee = document.querySelector("[data-selected-assignee]");
    const assignButton = document.querySelector("[data-assign-selected]");

    checks.forEach(check => {
      check.closest("[data-assignment-row]")?.classList.toggle("is-selected", check.checked);
    });
    if (selectAll) {
      selectAll.checked = checks.length > 0 && selected.length === checks.length;
      selectAll.indeterminate = selected.length > 0 && selected.length < checks.length;
    }
    if (count) {
      if (selected.length) count.textContent = `已選 ${selected.length} 家`;
      else if (dirty.length) count.textContent = `${dirty.length} 家待儲存`;
      else count.textContent = "尚未選取";
    }

    const batchMode = selected.length > 0;
    const pendingMode = !batchMode && dirty.length > 0;
    toolbar?.classList.toggle("is-batch-mode", batchMode);
    toolbar?.classList.toggle("has-pending-changes", pendingMode);
    if (idleHint) idleHint.hidden = batchMode || pendingMode;
    if (batchControls) batchControls.hidden = !batchMode;
    if (saveControls) saveControls.hidden = !pendingMode;
    if (dirtyCount) dirtyCount.textContent = `${dirty.length} 家有變更`;
    if (dirtyNote) dirtyNote.hidden = dirty.length === 0;

    if (assignButton) {
      assignButton.disabled = !batchMode;
      const target = assignee?.value || "";
      const targetLabel = assignee?.selectedOptions?.[0]?.textContent.trim() || "未分配";
      assignButton.textContent = target
        ? `指派給 ${targetLabel}（${selected.length} 家）`
        : `取消分配（${selected.length} 家）`;
    }
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
      updateActions();
      return;
    }
    if (!newAssignee) {
      input.value = "0";
      label.textContent = "尚未排序";
      handle.disabled = true;
      updateActions();
      return;
    }
    if (previousAssignee !== newAssignee) {
      input.value = "0";
      label.textContent = "儲存後排最後";
      handle.disabled = true;
    }
    updateActions();
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
    document.body.classList.add("is-reordering-price-assignments");
    return {row, slots};
  }

  function placeAtPointer(state, target, clientY) {
    if (!target || target === state.row || assigneeValue(target) !== assigneeValue(state.row)) return;
    if (Number(orderInput(target)?.value || 0) <= 0) return;
    const body = state.row.parentElement;
    const rect = target.getBoundingClientRect();
    const placeAfter = clientY > rect.top + rect.height / 2;
    clearDropMarker();
    target.classList.add(placeAfter ? "is-drop-after" : "is-drop-before");
    body.insertBefore(state.row, placeAfter ? target.nextSibling : target);
    applyOrderSlots(state);
  }

  function finishDrag(state) {
    if (!state) return;
    clearDropMarker();
    state.row.classList.remove("is-dragging");
    document.body.classList.remove("is-reordering-price-assignments");
    applyOrderSlots(state);
    updateActions();
    if (dragAnnouncer) {
      dragAnnouncer.textContent = `${dealerName(state.row)}已移到${orderLabel(state.row)?.textContent || "新位置"}，尚未儲存。`;
    }
    dragHandle(state.row)?.focus({preventScroll: true});
  }

  const selectAll = document.querySelector("[data-select-all]");
  selectAll?.addEventListener("change", () => {
    rowChecks().forEach(check => { check.checked = selectAll.checked; });
    updateActions();
  });

  document.addEventListener("change", event => {
    const rowCheck = event.target.closest("[data-row-select]");
    if (rowCheck) {
      updateActions();
      return;
    }
    const targetAssignee = event.target.closest("[data-selected-assignee]");
    if (targetAssignee) {
      updateActions();
      return;
    }
    const select = event.target.closest("[data-assignee-select]");
    if (select) updateRowAssignment(select.closest("[data-assignment-row]"), select.value);
  });

  let activePointerDrag = null;

  document.querySelectorAll("[data-drag-handle]").forEach(handle => {
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

    handle.addEventListener("pointerdown", event => {
      if (handle.disabled || (event.pointerType === "mouse" && event.button !== 0)) return;
      const row = handle.closest("[data-assignment-row]");
      if (sortableRows(row).length < 2) return;
      event.preventDefault();
      handle.focus({preventScroll: true});
      activePointerDrag = {
        row,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        state: null,
      };
    });
  });

  document.addEventListener("pointermove", event => {
    if (!activePointerDrag || activePointerDrag.pointerId !== event.pointerId) return;
    if (!activePointerDrag.state) {
      const distance = Math.hypot(
        event.clientX - activePointerDrag.startX,
        event.clientY - activePointerDrag.startY
      );
      if (distance < 6) return;
      activePointerDrag.state = beginDrag(activePointerDrag.row);
      if (!activePointerDrag.state) {
        activePointerDrag = null;
        return;
      }
    }
    event.preventDefault();
    const target = document.elementsFromPoint(event.clientX, event.clientY)
      .map(element => element.closest?.("[data-assignment-row]"))
      .find(row => row && row !== activePointerDrag.row);
    placeAtPointer(activePointerDrag.state, target, event.clientY);
    if (event.clientY < 110) window.scrollBy({top: -18, behavior: "auto"});
    else if (event.clientY > window.innerHeight - 110) window.scrollBy({top: 18, behavior: "auto"});
  }, {passive: false});

  function endPointerDrag(event) {
    if (!activePointerDrag || activePointerDrag.pointerId !== event.pointerId) return;
    event.preventDefault();
    const state = activePointerDrag.state;
    activePointerDrag = null;
    if (state) finishDrag(state);
  }

  document.addEventListener("pointerup", endPointerDrag);
  document.addEventListener("pointercancel", endPointerDrag);
  window.addEventListener("blur", () => {
    if (activePointerDrag?.state) finishDrag(activePointerDrag.state);
    activePointerDrag = null;
  });

  updateActions();
})();
