import { escapeHtml, getPlaceKey, refreshIcons, state } from './state.js?v=20261114-12';
import { openModal, closeModal } from './modals.js?v=20261114-12';
import { showToast } from './toast.js?v=20261114-12';

let onCompareChangeCallback = null;
let helpers = {
  formatHours: () => '',
  getTravelMinutes: () => null,
  getRatingValue: () => null,
  getReviewsValue: () => 0,
  getPriceValue: () => null,
};

export function setCompareHelpers({ onCompareChange, formatHours, getTravelMinutes, getRatingValue, getReviewsValue, getPriceValue }) {
  if (typeof onCompareChange === 'function') onCompareChangeCallback = onCompareChange;
  helpers = { formatHours, getTravelMinutes, getRatingValue, getReviewsValue, getPriceValue };
}

export function renderCompareTray() {
  const tray = document.getElementById('compareTray');
  const chipsEl = document.getElementById('compareTrayItems');
  const openBtn = document.getElementById('compareOpenModalBtn');
  if (!tray || !chipsEl || !openBtn) return;

  const entries = Array.from(state.compareKeys.entries());
  if (entries.length === 0) {
    tray.classList.add('hidden');
    chipsEl.innerHTML = '';
    return;
  }

  tray.classList.remove('hidden');
  openBtn.disabled = entries.length < 2;
  openBtn.textContent = entries.length < 2
    ? 'Select 1 more to Compare'
    : `Compare (${entries.length})`;

  chipsEl.innerHTML = entries.map(([key, entry]) => {
    const name = (entry.item?.restaurant?.name) || 'Restaurant';
    return `
      <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-800 dark:text-slate-100">
        <span class="truncate max-w-[140px]">${escapeHtml(name)}</span>
        <button type="button" data-remove-compare="${escapeHtml(key)}" aria-label="Remove ${escapeHtml(name)} from comparison"
          class="text-slate-400 hover:text-rose-500 transition">
          <i data-lucide="x" class="w-3 h-3"></i>
        </button>
      </span>
    `;
  }).join('');

  chipsEl.querySelectorAll('[data-remove-compare]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.compareKeys.delete(btn.dataset.removeCompare);
      renderCompareTray();
      if (onCompareChangeCallback) onCompareChangeCallback();
    });
  });

  refreshIcons(tray);
}

export function toggleCompareItem(displayIdx) {
  const item = state.displayedItems[displayIdx];
  if (!item || !item.restaurant) return;
  const key = getPlaceKey(item.restaurant);
  if (state.compareKeys.has(key)) {
    state.compareKeys.delete(key);
  } else {
    if (state.compareKeys.size >= 3) {
      showToast('You can compare up to 3 restaurants side by side. Remove one first.', 'warning');
      return;
    }
    state.compareKeys.set(key, { item, displayIdx });
  }
  renderCompareTray();
  if (onCompareChangeCallback) onCompareChangeCallback();
}

export function openCompareModal() {
  const modal = document.getElementById('compareModal');
  const body = document.getElementById('compareTableContainer');
  if (!modal || !body) return;

  const entries = Array.from(state.compareKeys.values());
  if (entries.length < 2) {
    showToast('Pick at least 2 restaurants to compare.', 'info');
    return;
  }

  const rows = [
    {
      label: 'Status',
      render: ({ item }) => item.isMatch
        ? '<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">Direct Match</span>'
        : '<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300">Alternative</span>',
    },
    {
      label: 'Rating & Reviews',
      render: ({ item }) => {
        const r = item.restaurant || {};
        const rat = helpers.getRatingValue(r);
        const rev = helpers.getReviewsValue(r);
        return `<span class="font-bold text-amber-600 dark:text-amber-400">★ ${rat ? rat.toFixed(1) : 'N/A'}</span> <span class="text-slate-400">(${rev} reviews)</span>`;
      },
    },
    {
      label: 'Travel Time',
      render: ({ item }) => {
        const r = item.restaurant || {};
        const mins = helpers.getTravelMinutes(r, state.activeSearchMode);
        return mins !== null ? `${Math.round(mins)} mins (${escapeHtml(state.activeSearchMode)})` : 'N/A';
      },
    },
    {
      label: 'Estimated Price',
      render: ({ item }) => {
        const r = item.restaurant || {};
        if (r.price_range) return escapeHtml(r.price_range);
        const p = helpers.getPriceValue(r);
        return p !== null ? `~$${Math.round(p)}` : 'N/A';
      },
    },
    {
      label: 'Dietary / MUIS',
      render: ({ item }) => {
        const r = item.restaurant || {};
        const badges = [];
        if (r.halal_certification === 'official' || (r.muis_check && r.muis_check.status === 'verified')) {
          badges.push('<span class="px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 font-bold">Official MUIS Halal</span>');
        } else if (r.halal_hint || (r.dietary_requirements || []).includes('halal')) {
          badges.push('<span class="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300 font-semibold">Google Halal Hint</span>');
        }
        if (r.serves_vegetarian_food) {
          badges.push('<span class="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300 font-semibold">Vegetarian</span>');
        }
        return badges.length ? badges.join(' ') : '<span class="text-slate-400">—</span>';
      },
    },
    {
      label: 'Hours Today',
      render: ({ item }) => {
        const r = item.restaurant || {};
        const openTag = r.open_now
          ? '<span class="text-emerald-600 dark:text-emerald-400 font-bold">Open</span>'
          : '<span class="text-rose-600 dark:text-rose-400 font-bold">Closed</span>';
        return `${openTag} • ${escapeHtml(helpers.formatHours(r))}`;
      },
    },
    {
      label: 'Why It Matched',
      render: ({ item }) => {
        const reasons = (item.reasons || []).slice(0, 3);
        if (!reasons.length) return '<span class="text-slate-400">—</span>';
        return `<ul class="space-y-1">${reasons.map((x) => `<li>• ${escapeHtml(String(x).replace(/^!\s*/, ''))}</li>`).join('')}</ul>`;
      },
    },
  ];

  const colHeaders = entries.map(({ item }) => {
    const r = item.restaurant || {};
    return `
      <th class="p-3 text-left align-top border-b border-slate-200 dark:border-slate-700 min-w-[180px]">
        <div class="text-sm font-extrabold text-slate-900 dark:text-white">${escapeHtml(r.name || 'Restaurant')}</div>
        <div class="text-[11px] text-slate-500 dark:text-slate-400 font-normal mt-0.5">${escapeHtml(r.address || 'Singapore')}</div>
      </th>
    `;
  }).join('');

  const tableRows = rows.map((row) => `
    <tr class="border-b border-slate-100 dark:border-slate-800/80 last:border-none">
      <th class="p-3 text-left align-top text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 bg-slate-50/70 dark:bg-slate-800/40 w-36">${row.label}</th>
      ${entries.map((entry) => `<td class="p-3 align-top text-xs text-slate-700 dark:text-slate-200">${row.render(entry)}</td>`).join('')}
    </tr>
  `).join('');

  body.innerHTML = `
    <div class="overflow-x-auto">
      <table class="w-full border-collapse">
        <thead>
          <tr>
            <th class="p-3 text-left text-[11px] font-bold uppercase tracking-wider text-slate-400 border-b border-slate-200 dark:border-slate-700">Attribute</th>
            ${colHeaders}
          </tr>
        </thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
  `;

  openModal(modal);
  refreshIcons(modal);
}

export function initCompareControls() {
  const modal = document.getElementById('compareModal');
  document.getElementById('compareOpenModalBtn')?.addEventListener('click', openCompareModal);
  document.getElementById('compareClearBtn')?.addEventListener('click', () => {
    state.compareKeys.clear();
    renderCompareTray();
    if (onCompareChangeCallback) onCompareChangeCallback();
  });
  document.getElementById('closeCompareModalBtn')?.addEventListener('click', () => closeModal(modal));
  document.getElementById('closeCompareFooterBtn')?.addEventListener('click', () => closeModal(modal));
}
