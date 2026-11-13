const openStack = [];
let lastFocusedBeforeModal = null;

export function openModal(modalEl, focusSelector = null) {
  if (!modalEl) return;
  if (openStack.length === 0) {
    lastFocusedBeforeModal = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }
  if (!openStack.includes(modalEl)) {
    openStack.push(modalEl);
  }
  modalEl.classList.remove('hidden');
  modalEl.classList.add('flex');
  modalEl.setAttribute('aria-hidden', 'false');

  if (focusSelector) {
    const target = modalEl.querySelector(focusSelector);
    if (target instanceof HTMLElement) {
      setTimeout(() => target.focus(), 50);
    }
  }
}

export function closeModal(modalEl) {
  if (!modalEl) return;
  modalEl.classList.add('hidden');
  modalEl.classList.remove('flex');
  modalEl.setAttribute('aria-hidden', 'true');

  const idx = openStack.indexOf(modalEl);
  if (idx !== -1) openStack.splice(idx, 1);

  if (openStack.length === 0 && lastFocusedBeforeModal && lastFocusedBeforeModal.isConnected) {
    lastFocusedBeforeModal.focus();
    lastFocusedBeforeModal = null;
  }
}

export function initModalAccessibility(modalIds = []) {
  modalIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('click', (e) => {
      if (e.target === el) {
        closeModal(el);
      }
    });
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || openStack.length === 0) return;
    const topModal = openStack[openStack.length - 1];
    closeModal(topModal);
  });
}
