const openStack = [];
let lastFocusedBeforeModal = null;
let lockedScrollY = 0;

function setBackgroundScrollLocked(locked) {
  const docEl = document.documentElement;
  const body = document.body;
  if (!docEl || !body) return;
  if (locked) {
    if (docEl.classList.contains('bf-modal-open')) return;
    lockedScrollY = window.scrollY || docEl.scrollTop || 0;
    const scrollbarWidth = Math.max(0, window.innerWidth - docEl.clientWidth);
    body.style.paddingRight = scrollbarWidth > 0 ? `${scrollbarWidth}px` : '';
    docEl.classList.add('bf-modal-open');
    body.classList.add('bf-modal-open');
    return;
  }
  if (!docEl.classList.contains('bf-modal-open')) return;
  docEl.classList.remove('bf-modal-open');
  body.classList.remove('bf-modal-open');
  body.style.paddingRight = '';
  if (Math.abs((window.scrollY || docEl.scrollTop || 0) - lockedScrollY) > 1) {
    window.scrollTo(0, lockedScrollY);
  }
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

function getFocusableElements(container) {
  if (!container) return [];
  return Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter((el) => {
    if (!(el instanceof HTMLElement)) return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    return el.offsetParent !== null || el === document.activeElement;
  });
}

export function openModal(modalEl, focusSelector = null) {
  if (!modalEl) return;
  if (openStack.length === 0) {
    lastFocusedBeforeModal = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }
  if (!openStack.includes(modalEl)) {
    openStack.push(modalEl);
  }
  setBackgroundScrollLocked(true);
  modalEl.classList.remove('hidden');
  modalEl.classList.add('flex');
  modalEl.setAttribute('aria-hidden', 'false');

  setTimeout(() => {
    const requested = focusSelector ? modalEl.querySelector(focusSelector) : null;
    if (requested instanceof HTMLElement && requested.offsetParent !== null) {
      requested.focus({ preventScroll: true });
      return;
    }
    const focusables = getFocusableElements(modalEl);
    if (focusables.length > 0) {
      focusables[0].focus({ preventScroll: true });
    } else {
      if (!modalEl.hasAttribute('tabindex')) modalEl.setAttribute('tabindex', '-1');
      modalEl.focus({ preventScroll: true });
    }
  }, 50);
}

export function closeModal(modalEl) {
  if (!modalEl) return;
  modalEl.classList.add('hidden');
  modalEl.classList.remove('flex');
  modalEl.setAttribute('aria-hidden', 'true');

  const idx = openStack.indexOf(modalEl);
  if (idx !== -1) openStack.splice(idx, 1);

  if (openStack.length === 0) {
    setBackgroundScrollLocked(false);
    if (lastFocusedBeforeModal && lastFocusedBeforeModal.isConnected) {
      lastFocusedBeforeModal.focus({ preventScroll: true });
      lastFocusedBeforeModal = null;
    }
  }
}

export function initModalAccessibility(modalIds = []) {
  modalIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    let pointerStartedOnBackdrop = false;
    let pointerEndedOnBackdrop = false;

    el.addEventListener('pointerdown', (e) => {
      const isPrimary = e.pointerType !== 'mouse' || e.button === 0;
      pointerStartedOnBackdrop = isPrimary && e.target === el;
      pointerEndedOnBackdrop = false;
    });

    el.addEventListener('pointerup', (e) => {
      pointerEndedOnBackdrop = e.target === el;
    });

    el.addEventListener('pointercancel', () => {
      pointerStartedOnBackdrop = false;
      pointerEndedOnBackdrop = false;
    });

    el.addEventListener('click', (e) => {
      const shouldClose = e.target === el && pointerStartedOnBackdrop && pointerEndedOnBackdrop;
      pointerStartedOnBackdrop = false;
      pointerEndedOnBackdrop = false;
      if (shouldClose) {
        closeModal(el);
      }
    });
  });

  document.addEventListener('keydown', (e) => {
    if (openStack.length === 0) return;
    const topModal = openStack[openStack.length - 1];
    if (e.key === 'Escape') {
      closeModal(topModal);
      return;
    }
    if (e.key === 'Tab') {
      const focusables = getFocusableElements(topModal);
      if (focusables.length === 0) {
        e.preventDefault();
        if (!topModal.hasAttribute('tabindex')) topModal.setAttribute('tabindex', '-1');
        topModal.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (!topModal.contains(active)) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });
}
