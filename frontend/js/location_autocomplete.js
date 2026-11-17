const SUGGEST_DEBOUNCE_MS = 180;
const COORD_LOOKALIKE_REGEX = /^\s*[+-]?\d+(?:\.\d+)?\s*,/;

function getActiveSegment(rawValue, multiComma) {
  const val = String(rawValue || '');
  if (!multiComma || COORD_LOOKALIKE_REGEX.test(val)) {
    return val.trim();
  }
  const parts = val.split(',');
  return (parts[parts.length - 1] || '').trim();
}

function applySelectedSuggestion(inputEl, selectedLabel, multiComma) {
  const current = String(inputEl.value || '');
  if (!multiComma || COORD_LOOKALIKE_REGEX.test(current) || !current.includes(',')) {
    inputEl.value = selectedLabel;
    return;
  }
  const parts = current.split(',');
  parts[parts.length - 1] = ` ${selectedLabel}`;
  inputEl.value = parts
    .map((p, idx) => (idx === 0 ? p.trim() : p.trim()))
    .filter(Boolean)
    .join(', ');
}

export function attachLocationAutocomplete({
  inputEl,
  menuParentEl = null,
  multiComma = false,
  onSelect = null,
  limit = 6,
}) {
  if (!inputEl || inputEl.dataset.locAcAttached === '1') {
    return () => {};
  }
  inputEl.dataset.locAcAttached = '1';
  inputEl.setAttribute('autocomplete', 'off');

  const container = menuParentEl || inputEl.parentElement;
  if (!container) return () => {};
  if (getComputedStyle(container).position === 'static') {
    container.classList.add('relative');
  }

  const menu = document.createElement('div');
  menu.className = 'bf-loc-ac-menu hidden';
  menu.setAttribute('role', 'listbox');
  container.appendChild(menu);

  let items = [];
  let activeIndex = -1;
  let debounceTimer = null;
  let abortController = null;
  let lastPickedVal = null;

  const hideMenu = () => {
    menu.classList.add('hidden');
    menu.innerHTML = '';
    items = [];
    activeIndex = -1;
  };

  const renderMenu = () => {
    menu.innerHTML = '';
    if (!items.length) {
      menu.classList.add('hidden');
      return;
    }
    items.forEach((item, idx) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `bf-loc-ac-item${idx === activeIndex ? ' is-active' : ''}`;
      btn.setAttribute('role', 'option');
      btn.setAttribute('aria-selected', idx === activeIndex ? 'true' : 'false');

      const primary = document.createElement('span');
      primary.className = 'bf-loc-ac-primary';
      primary.textContent = item.label;

      const secondary = document.createElement('span');
      secondary.className = 'bf-loc-ac-secondary';
      secondary.textContent = item.secondary || 'Singapore';

      btn.appendChild(primary);
      btn.appendChild(secondary);
      btn.addEventListener('mousedown', (e) => {
        e.preventDefault();
        pickItem(idx);
      });
      menu.appendChild(btn);
    });
    menu.classList.remove('hidden');
  };

  const pickItem = (idx) => {
    const chosen = items[idx];
    if (!chosen) return;
    applySelectedSuggestion(inputEl, chosen.label, multiComma);
    lastPickedVal = inputEl.value;
    hideMenu();
    inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    inputEl.dispatchEvent(new Event('change', { bubbles: true }));
    if (typeof onSelect === 'function') {
      onSelect(chosen.label, chosen);
    }
  };

  const fetchSuggestions = async (query) => {
    if (abortController) {
      abortController.abort();
    }
    abortController = new AbortController();
    try {
      const url = `/api/locations/suggest?q=${encodeURIComponent(query)}&limit=${encodeURIComponent(limit)}`;
      const res = await fetch(url, { signal: abortController.signal });
      if (!res.ok) {
        hideMenu();
        return;
      }
      const data = await res.json();
      if (getActiveSegment(inputEl.value, multiComma) !== query) {
        return;
      }
      items = Array.isArray(data?.suggestions) ? data.suggestions : [];
      activeIndex = -1;
      renderMenu();
    } catch (err) {
      if (err?.name !== 'AbortError') {
        hideMenu();
      }
    }
  };

  const handleInput = () => {
    if (lastPickedVal !== null && inputEl.value === lastPickedVal) {
      lastPickedVal = null;
      return;
    }
    lastPickedVal = null;
    const seg = getActiveSegment(inputEl.value, multiComma);
    if (debounceTimer) clearTimeout(debounceTimer);
    if (!seg || seg.length < 1 || COORD_LOOKALIKE_REGEX.test(seg)) {
      hideMenu();
      return;
    }
    debounceTimer = setTimeout(() => {
      fetchSuggestions(seg);
    }, SUGGEST_DEBOUNCE_MS);
  };

  const handleKeydown = (e) => {
    if (menu.classList.contains('hidden') || !items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
      renderMenu();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = activeIndex <= 0 ? items.length - 1 : activeIndex - 1;
      renderMenu();
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      pickItem(activeIndex);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      hideMenu();
    }
  };

  const handleBlur = () => {
    setTimeout(hideMenu, 140);
  };

  inputEl.addEventListener('input', handleInput);
  inputEl.addEventListener('keydown', handleKeydown);
  inputEl.addEventListener('blur', handleBlur);

  return () => {
    if (debounceTimer) clearTimeout(debounceTimer);
    if (abortController) abortController.abort();
    inputEl.removeEventListener('input', handleInput);
    inputEl.removeEventListener('keydown', handleKeydown);
    inputEl.removeEventListener('blur', handleBlur);
    menu.remove();
    delete inputEl.dataset.locAcAttached;
  };
}
