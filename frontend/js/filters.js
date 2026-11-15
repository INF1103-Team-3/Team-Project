import {
  applyRatingFilterToWishesRaw,
  formatCuisineLabel,
  getActiveRatingFilterValue,
  normalizeWishText,
  RECENT_KEY,
  refreshIcons,
  state,
  validateEnglishWishesInput,
} from './state.js?v=20261114-12';
import { apiJson } from './api.js?v=20261114-12';
import { showToast } from './toast.js?v=20261114-12';
import { renderResults, renderResultsSkeleton, updateResultsSkeletonModel } from './results.js?v=20261114-12';

let chatCallbacks = {
  renderSummary: () => {},
  refreshGreetingIfIdle: () => {},
  postSearchOutcome: () => {},
};

export const MODE_LIMITS = {
  walk: { minTime: 1, maxTime: 90, minDist: 0.01, maxDist: 15, defaultTime: 30, defaultDist: 2.0 },
  drive: { minTime: 1, maxTime: 120, minDist: 0.01, maxDist: 50, defaultTime: 30, defaultDist: 10.0 },
  transit: { minTime: 1, maxTime: 150, minDist: 0.01, maxDist: 50, defaultTime: 40, defaultDist: 10.0 },
};

const LIMIT_UI_CONFIG = {
  time: {
    wrapId: 'timeDisplayWrap',
    inputId: 'timeInput',
    unitId: 'timeUnitLabel',
    sliderId: 'timeSlider',
    baseMin: 1,
    defaultStep: 1,
    unit: 'mins',
    maxKey: 'maxTime',
    minKey: 'minTime',
    defaultKey: 'defaultTime',
  },
  distance: {
    wrapId: 'distanceDisplayWrap',
    inputId: 'distanceInput',
    unitId: 'distanceUnitLabel',
    sliderId: 'distanceSlider',
    baseMin: 0.1,
    defaultStep: 0.1,
    unit: 'km',
    maxKey: 'maxDist',
    minKey: 'minDist',
    defaultKey: 'defaultDist',
  },
};

const BUDGET_UI_CONFIG = {
  wrapId: 'budgetDisplayWrap',
  inputId: 'budgetInput',
  prefixId: 'budgetPrefixLabel',
  plusId: 'budgetPlusLabel',
  sliderId: 'budgetSlider',
  hintId: 'budgetRangeHint',
  scaleMaxId: 'budgetScaleMax',
  baseMin: 5,
  baseMax: 100,
  plusSliderVal: 105,
  plusSearchVal: 1000,
  minVal: 0.01,
  searchMax: 1000,
  defaultStep: 5,
  defaultVal: 30,
};

function getModeLimits(mode = state.currentMode) {
  return MODE_LIMITS[mode] || MODE_LIMITS.walk;
}

function formatLimitNumber(val, decimals = 2) {
  const rounded = Math.round(val * 10 ** decimals) / 10 ** decimals;
  return String(rounded);
}

function sanitizeDecimalText(raw) {
  let seenDot = false;
  return String(raw || '')
    .replace(/[^\d.]/g, '')
    .replace(/\./g, () => {
      if (seenDot) return '';
      seenDot = true;
      return '.';
    });
}

function syncDynamicSliderBounds(slider, rawVal, {
  baseMin,
  baseMax,
  minVal,
  defaultStep,
  fineStep,
  isFineFn,
  contractToValue = true,
}) {
  if (!slider) return;
  if (!Number.isFinite(rawVal) || rawVal <= 0) {
    slider.min = String(baseMin);
    slider.max = String(baseMax);
    slider.step = String(defaultStep);
    return;
  }

  const clampedMinFloor = Math.min(baseMin, Math.max(minVal, rawVal));
  const currentMin = parseFloat(slider.min);
  const nextMin = contractToValue
    ? (rawVal < baseMin ? clampedMinFloor : baseMin)
    : (Number.isFinite(currentMin) ? Math.min(currentMin, clampedMinFloor) : baseMin);
  const nextMax = baseMax;

  slider.min = String(nextMin);
  slider.max = String(nextMax);
  slider.step = isFineFn(rawVal) ? String(fineStep) : String(defaultStep);
  slider.value = String(Math.max(nextMin, Math.min(nextMax, rawVal)));
}

function syncLimitInputWidth(inputEl, { emptyWidth = '5.8ch' } = {}) {
  if (!inputEl) return;
  const text = inputEl.value.trim();
  inputEl.style.width = text === ''
    ? emptyWidth
    : `${Math.min(7.5, Math.max(1.2, text.length + 0.25))}ch`;
}

function adaptSliderForValue(type, rawVal, { contractToValue = true } = {}) {
  const cfg = LIMIT_UI_CONFIG[type];
  const slider = cfg ? document.getElementById(cfg.sliderId) : null;
  if (!slider) return;
  const limits = getModeLimits();

  syncDynamicSliderBounds(slider, rawVal, {
    baseMin: cfg.baseMin,
    baseMax: limits[cfg.maxKey],
    minVal: limits[cfg.minKey],
    defaultStep: cfg.defaultStep,
    fineStep: type === 'time' ? 0.1 : 0.01,
    isFineFn: (v) => (type === 'time'
      ? !Number.isInteger(v)
      : (v < 0.1 || Math.abs(Math.round(v * 10) - v * 10) > 1e-6)),
    contractToValue,
  });
}

function adaptBudgetSliderForValue(rawVal, { contractToValue = true, keepPlusNotch = false } = {}) {
  const slider = document.getElementById(BUDGET_UI_CONFIG.sliderId);
  if (!slider) return;
  const shouldUsePlusNotch = Boolean(
    keepPlusNotch || (Number.isFinite(rawVal) && rawVal > BUDGET_UI_CONFIG.baseMax),
  );
  const clampedVal = shouldUsePlusNotch ? BUDGET_UI_CONFIG.baseMax : rawVal;
  syncDynamicSliderBounds(slider, clampedVal, {
    baseMin: BUDGET_UI_CONFIG.baseMin,
    baseMax: BUDGET_UI_CONFIG.plusSliderVal,
    minVal: BUDGET_UI_CONFIG.minVal,
    defaultStep: BUDGET_UI_CONFIG.defaultStep,
    fineStep: 1,
    isFineFn: (v) => !Number.isInteger(v) || Math.round(v) % 5 !== 0,
    contractToValue,
  });
  if (Number.isFinite(clampedVal) && clampedVal > 0 && !Number.isInteger(clampedVal) && !shouldUsePlusNotch) {
    slider.step = '0.01';
    slider.value = String(clampedVal);
  }
  if (shouldUsePlusNotch) {
    slider.value = String(BUDGET_UI_CONFIG.plusSliderVal);
  }
}

export function isBudgetPlusDisplay(val = null, isSet = state.isBudgetSet) {
  if (!isSet) return false;
  const num = val != null ? Number(val) : NaN;
  if (Number.isFinite(num)) {
    if (num > BUDGET_UI_CONFIG.baseMax) return true;
    if (num < BUDGET_UI_CONFIG.baseMax) return false;
  }
  return Boolean(state.isBudgetPlus);
}

function syncRangeTrackVisual(slider, isSet = true) {
  if (!slider) return;
  const min = parseFloat(slider.min);
  const max = parseFloat(slider.max);
  const val = parseFloat(slider.value);
  let pct = 0;
  if (Number.isFinite(min) && Number.isFinite(max) && max > min && Number.isFinite(val)) {
    pct = Math.min(100, Math.max(0, ((val - min) / (max - min)) * 100));
  }
  slider.style.setProperty('--bf-range-pct', `${pct}%`);
  slider.classList.toggle('is-set', Boolean(isSet));
}

function updateTravelScaleLabels() {
  const minEl = document.getElementById('travelScaleMin');
  const midEl = document.getElementById('travelScaleMid');
  const maxEl = document.getElementById('travelScaleMax');
  if (!minEl || !midEl || !maxEl) return;

  const type = state.currentLimitType === 'distance' ? 'distance' : 'time';
  const limits = getModeLimits();

  if (type === 'time') {
    minEl.textContent = '1 min';
    const midVal = Math.round(limits.maxTime / 2);
    midEl.textContent = `${midVal} mins`;
    maxEl.textContent = `${limits.maxTime} mins`;
  } else {
    minEl.textContent = '0.1 km';
    const midVal = formatLimitNumber(limits.maxDist / 2, 1);
    midEl.textContent = `${midVal} km`;
    maxEl.textContent = `${limits.maxDist} km`;
  }
}

function updateLimitRangeHint() {
  const hintEl = document.getElementById('limitRangeHint');
  if (!hintEl) return;
  const type = state.currentLimitType === 'distance' ? 'distance' : 'time';
  const cfg = LIMIT_UI_CONFIG[type];
  const limits = getModeLimits();
  const inputEl = document.getElementById(cfg.inputId);
  const raw = inputEl?.value.trim() || '';
  const val = raw !== '' ? parseFloat(raw) : NaN;

  if (state.isTravelSet && Number.isFinite(val) && val < limits[cfg.minKey]) {
    hintEl.textContent = `Minimum ${state.currentMode} limit is ${limits[cfg.minKey]} ${cfg.unit}`;
    hintEl.classList.remove('hidden');
    return;
  }
  hintEl.textContent = '';
  hintEl.classList.add('hidden');
}

function updateBudgetRangeHint() {
  const hintEl = document.getElementById(BUDGET_UI_CONFIG.hintId);
  const scaleMaxEl = document.getElementById(BUDGET_UI_CONFIG.scaleMaxId);
  const inputEl = document.getElementById(BUDGET_UI_CONFIG.inputId);
  const raw = inputEl?.value.trim() || '';
  const val = raw !== '' ? parseFloat(raw) : NaN;

  if (scaleMaxEl) {
    scaleMaxEl.textContent = '$100+ (Fine Dine)';
  }

  if (!hintEl) return;
  if (state.isBudgetSet && !state.isBudgetPlus && Number.isFinite(val) && val < BUDGET_UI_CONFIG.minVal) {
    hintEl.textContent = `Minimum budget per person is SGD $${BUDGET_UI_CONFIG.minVal}`;
    hintEl.classList.remove('hidden');
    return;
  }
  hintEl.textContent = '';
  hintEl.classList.add('hidden');
}

export function setFilterChatCallbacks(cbs) {
  chatCallbacks = { ...chatCallbacks, ...cbs };
}

export function updateSliderDisplayStyles() {
  const timeInput = document.getElementById('timeInput');
  const distanceInput = document.getElementById('distanceInput');
  const budgetWrap = document.getElementById(BUDGET_UI_CONFIG.wrapId);
  const budgetInput = document.getElementById(BUDGET_UI_CONFIG.inputId);
  const budgetPrefix = document.getElementById(BUDGET_UI_CONFIG.prefixId);
  const budgetPlus = document.getElementById(BUDGET_UI_CONFIG.plusId);
  if (!timeInput || !distanceInput || !budgetWrap || !budgetInput) return;

  ['time', 'distance'].forEach((type) => {
    const cfg = LIMIT_UI_CONFIG[type];
    const wrap = document.getElementById(cfg.wrapId);
    const input = document.getElementById(cfg.inputId);
    const unit = document.getElementById(cfg.unitId);
    if (!wrap || !input) return;

    wrap.classList.toggle('hidden', state.currentLimitType !== type);
    if (!state.isTravelSet) {
      input.value = '';
    }
    const hasVal = state.isTravelSet && input.value.trim() !== '';
    wrap.classList.toggle('is-set', hasVal);
    input.classList.toggle('is-set', hasVal);
    if (unit) unit.classList.toggle('hidden', !hasVal);
    syncLimitInputWidth(input);
    syncRangeTrackVisual(document.getElementById(cfg.sliderId), state.isTravelSet);
  });

  if (!state.isBudgetSet) {
    budgetInput.value = '';
  }
  const budgetRaw = budgetInput.value.trim();
  const budgetVal = budgetRaw !== '' ? parseFloat(budgetRaw) : NaN;
  const hasBudget = state.isBudgetSet && budgetRaw !== '';
  const showPlus = hasBudget && isBudgetPlusDisplay(budgetVal, state.isBudgetSet);

  budgetWrap.classList.toggle('is-set', hasBudget);
  budgetInput.classList.toggle('is-set', hasBudget);
  if (budgetPrefix) budgetPrefix.classList.toggle('hidden', !hasBudget);
  if (budgetPlus) budgetPlus.classList.toggle('hidden', !showPlus);
  syncLimitInputWidth(budgetInput);
  syncRangeTrackVisual(document.getElementById(BUDGET_UI_CONFIG.sliderId), state.isBudgetSet);

  updateTravelScaleLabels();
  updateLimitRangeHint();
  updateBudgetRangeHint();
}

export function setLimitType(type, { activateIfUnset = false } = {}) {
  const targetType = type === 'distance' ? 'distance' : 'time';
  state.currentLimitType = targetType;
  const limitTypeTimeBtn = document.getElementById('limitTypeTimeBtn');
  const limitTypeDistBtn = document.getElementById('limitTypeDistBtn');
  const timeSlider = document.getElementById('timeSlider');
  const distanceSlider = document.getElementById('distanceSlider');
  if (!limitTypeTimeBtn || !limitTypeDistBtn || !timeSlider || !distanceSlider) return;

  const activeCls = 'whitespace-nowrap px-2 py-0.5 text-[10px] font-bold uppercase rounded-md bg-white dark:bg-slate-700 text-brand-600 dark:text-brand-400 shadow-sm transition';
  const inactiveCls = 'whitespace-nowrap px-2 py-0.5 text-[10px] font-bold uppercase rounded-md text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white transition';

  if (targetType === 'time') {
    limitTypeTimeBtn.className = activeCls;
    limitTypeDistBtn.className = inactiveCls;
    timeSlider.classList.remove('hidden');
    distanceSlider.classList.add('hidden');
  } else {
    limitTypeDistBtn.className = activeCls;
    limitTypeTimeBtn.className = inactiveCls;
    distanceSlider.classList.remove('hidden');
    timeSlider.classList.add('hidden');
  }

  const cfg = LIMIT_UI_CONFIG[targetType];
  const activeInput = document.getElementById(cfg.inputId);
  const activeSlider = document.getElementById(cfg.sliderId);
  const limits = getModeLimits();

  if ((state.isTravelSet || activateIfUnset) && activeInput && activeSlider) {
    state.isTravelSet = true;
    if (activeInput.value.trim() === '') {
      const sliderNum = parseFloat(activeSlider.value);
      const fallback = Number.isFinite(sliderNum) && sliderNum > 0 ? sliderNum : limits[cfg.defaultKey];
      activeInput.value = formatLimitNumber(fallback, 2);
      adaptSliderForValue(targetType, fallback, { contractToValue: true });
    } else {
      const typedNum = parseFloat(activeInput.value);
      if (Number.isFinite(typedNum) && typedNum > 0) {
        const cappedNum = Math.min(limits[cfg.maxKey], typedNum);
        if (cappedNum !== typedNum) {
          activeInput.value = formatLimitNumber(cappedNum, 2);
        }
        adaptSliderForValue(targetType, cappedNum, { contractToValue: true });
      }
    }
  }

  updateSliderDisplayStyles();
}

export function updateMidpointHint() {
  const extraLocationsContainer = document.getElementById('extraLocationsContainer');
  const midpointHintBadge = document.getElementById('midpointHintBadge');
  const midpointHintText = document.getElementById('midpointHintText');
  if (!extraLocationsContainer || !midpointHintBadge || !midpointHintText) return;

  const extraRows = extraLocationsContainer.querySelectorAll('.extra-location-input');
  const totalCount = 1 + extraRows.length;
  if (totalCount > 1) {
    midpointHintText.textContent = `Finding restaurants at the midpoint in-between ${totalCount} locations`;
    midpointHintBadge.classList.remove('hidden');
  } else {
    midpointHintBadge.classList.add('hidden');
  }
  extraRows.forEach((inp, idx) => {
    inp.placeholder = `Location ${idx + 2} (e.g. Punggol, Bugis, Jurong East)`;
  });
}

export function addExtraLocationInput(initialValue = '') {
  const extraLocationsContainer = document.getElementById('extraLocationsContainer');
  if (!extraLocationsContainer) return;

  const row = document.createElement('div');
  row.className = 'relative flex items-center gap-1.5';
  row.innerHTML = `
    <div class="relative flex-1">
      <i data-lucide="users" class="w-4 h-4 absolute left-3 top-2.5 text-indigo-500"></i>
      <input type="text" class="extra-location-input w-full pl-9 pr-3 py-2 text-sm rounded-xl border border-indigo-200 dark:border-indigo-800 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition"
        placeholder="Location 2 (e.g. Punggol)">
    </div>
    <button type="button" class="remove-loc-btn p-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-400 hover:text-rose-500 hover:border-rose-300 transition" title="Remove this location">
      <i data-lucide="x" class="w-4 h-4"></i>
    </button>
  `;
  const inp = row.querySelector('.extra-location-input');
  inp.value = initialValue;
  row.querySelector('.remove-loc-btn').addEventListener('click', () => {
    row.remove();
    updateMidpointHint();
    chatCallbacks.renderSummary();
  });
  extraLocationsContainer.appendChild(row);
  refreshIcons(row);
  updateMidpointHint();
  if (!initialValue) inp.focus();
}

export function getAllEnteredLocations() {
  const locationInput = document.getElementById('locationInput');
  const extraLocationsContainer = document.getElementById('extraLocationsContainer');
  const primary = locationInput ? locationInput.value.trim() : '';
  const extras = extraLocationsContainer
    ? Array.from(extraLocationsContainer.querySelectorAll('.extra-location-input')).map((el) => el.value.trim()).filter(Boolean)
    : [];
  return [primary, ...extras].filter(Boolean);
}

export function setEnteredLocations(locArray) {
  const list = Array.isArray(locArray) && locArray.length ? locArray : [''];
  const locationInput = document.getElementById('locationInput');
  const extraLocationsContainer = document.getElementById('extraLocationsContainer');
  if (locationInput) locationInput.value = list[0] || '';
  if (extraLocationsContainer) {
    extraLocationsContainer.innerHTML = '';
    list.slice(1).forEach((val) => addExtraLocationInput(val));
  }
  updateMidpointHint();
}

function ensureCuisineChip(containerId, chipClass, hoverBorderCls, cuisine, toggleFn) {
  const clean = String(cuisine || '').trim().toLowerCase();
  const container = document.getElementById(containerId);
  if (!clean || !container) return;
  const existing = container.querySelector(`.${chipClass}[data-cuisine="${CSS.escape(clean)}"]`);
  if (!existing) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.dataset.cuisine = clean;
    btn.dataset.custom = 'true';
    btn.className = `${chipClass} text-[11px] font-semibold px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 ${hoverBorderCls} transition`;
    btn.textContent = formatCuisineLabel(clean);
    btn.addEventListener('click', () => toggleFn(clean));
    container.appendChild(btn);
  }
}

export function ensurePreferredChipExists(cuisine) {
  ensureCuisineChip('preferredChipsContainer', 'prefer-chip', 'hover:border-emerald-400', cuisine, togglePreferredCuisine);
}

export function ensureDislikedChipExists(cuisine) {
  ensureCuisineChip('dislikedChipsContainer', 'dislike-chip', 'hover:border-rose-300', cuisine, toggleDislikedCuisine);
}

export function updatePreferredChipsUI() {
  const container = document.getElementById('preferredChipsContainer');
  const clearBtn = document.getElementById('clearPreferredBtn');
  const quotaHint = document.getElementById('preferredQuotaHint');
  if (!container) return;

  container.querySelectorAll('.prefer-chip').forEach((chip) => {
    const c = chip.dataset.cuisine;
    const label = formatCuisineLabel(c);
    if (state.preferredCuisines.has(c)) {
      chip.className = 'prefer-chip text-[11px] font-bold px-2.5 py-1 rounded-lg border border-emerald-400 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-950/70 text-emerald-700 dark:text-emerald-300 transition';
      chip.textContent = `✓ ${label}`;
    } else {
      chip.className = 'prefer-chip text-[11px] font-semibold px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:border-emerald-400 transition';
      chip.textContent = label;
    }
  });
  if (clearBtn) clearBtn.classList.toggle('hidden', state.preferredCuisines.size === 0);
  if (quotaHint) {
    if (state.preferredCuisines.size > 1) {
      quotaHint.textContent = `${state.preferredCuisines.size} selected (Outputs ÷ ${state.preferredCuisines.size})`;
      quotaHint.classList.remove('hidden');
    } else {
      quotaHint.classList.add('hidden');
    }
  }
}

export function updateDislikedChipsUI() {
  const clearBtn = document.getElementById('clearDislikedBtn');
  document.querySelectorAll('.dislike-chip').forEach((chip) => {
    const c = chip.dataset.cuisine;
    const label = formatCuisineLabel(c);
    if (state.dislikedCuisines.has(c)) {
      chip.className = 'dislike-chip text-[11px] font-bold px-2.5 py-1 rounded-lg border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-950/70 text-rose-700 dark:text-rose-300 transition';
      chip.textContent = `✕ ${label}`;
    } else {
      chip.className = 'dislike-chip text-[11px] font-semibold px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:border-rose-300 transition';
      chip.textContent = label;
    }
  });
  if (clearBtn) clearBtn.classList.toggle('hidden', state.dislikedCuisines.size === 0);
}

function togglePreferredCuisine(c) {
  const clean = String(c || '').trim().toLowerCase();
  if (!clean) return;
  if (state.preferredCuisines.has(clean)) {
    state.preferredCuisines.delete(clean);
  } else {
    state.preferredCuisines.add(clean);
    if (state.dislikedCuisines.has(clean)) {
      state.dislikedCuisines.delete(clean);
      updateDislikedChipsUI();
    }
  }
  updatePreferredChipsUI();
  chatCallbacks.renderSummary();
}

function toggleDislikedCuisine(c) {
  const clean = String(c || '').trim().toLowerCase();
  if (!clean) return;
  if (state.dislikedCuisines.has(clean)) {
    state.dislikedCuisines.delete(clean);
  } else {
    state.dislikedCuisines.add(clean);
    if (state.preferredCuisines.has(clean)) {
      state.preferredCuisines.delete(clean);
      updatePreferredChipsUI();
    }
  }
  updateDislikedChipsUI();
  chatCallbacks.renderSummary();
}

function addCustomCuisinesToSet(inputId, ensureChipFn, targetSet, oppositeSet) {
  const inputEl = document.getElementById(inputId);
  if (!inputEl) return;
  const raw = inputEl.value.trim();
  if (!raw) return;
  raw.split(',').forEach((part) => {
    const clean = part.trim().toLowerCase();
    if (clean) {
      ensureChipFn(clean);
      targetSet.add(clean);
      oppositeSet.delete(clean);
    }
  });
  inputEl.value = '';
  updateDislikedChipsUI();
  updatePreferredChipsUI();
  chatCallbacks.renderSummary();
}

export function addCustomCuisinesFromInput() {
  addCustomCuisinesToSet('customCuisineInput', ensurePreferredChipExists, state.preferredCuisines, state.dislikedCuisines);
}

export function addCustomDislikedCuisinesFromInput() {
  addCustomCuisinesToSet('customDislikedCuisineInput', ensureDislikedChipExists, state.dislikedCuisines, state.preferredCuisines);
}

export function getUserRecentKey() {
  if (!state.currentUser || !state.currentUser.user_id) return null;
  return `${RECENT_KEY}_${state.currentUser.user_id}`;
}

function getLocalRecent() {
  const key = getUserRecentKey();
  if (!key) return [];
  try {
    return JSON.parse(localStorage.getItem(key)) || [];
  } catch {
    return [];
  }
}

export function saveLocalRecent(query) {
  const key = getUserRecentKey();
  if (!query || !key) return;
  let list = getLocalRecent().filter((q) => q.toLowerCase() !== query.toLowerCase());
  list.unshift(query);
  if (list.length > 5) list = list.slice(0, 5);
  try {
    localStorage.setItem(key, JSON.stringify(list));
  } catch { }
  renderRecentSearches(list);
}

export function renderRecentSearches(list) {
  const container = document.getElementById('recentSearches');
  const listEl = document.getElementById('recentList');
  if (!container || !listEl) return;
  if (!state.currentUser || !list || list.length === 0) {
    container.classList.add('hidden');
    return;
  }
  container.classList.remove('hidden');
  listEl.innerHTML = '';
  list.forEach((q) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'text-xs px-2.5 py-0.5 rounded-full bg-brand-50 dark:bg-brand-500/15 text-brand-700 dark:text-brand-300 hover:bg-brand-100 dark:hover:bg-brand-500/25 border border-brand-200 dark:border-brand-500/30 transition font-medium';
    btn.textContent = q;
    btn.addEventListener('click', () => {
      const parts = q.split(' + ').map((s) => s.trim()).filter(Boolean);
      setEnteredLocations(parts.length ? parts : [q]);
      chatCallbacks.renderSummary();
    });
    listEl.appendChild(btn);
  });
}

export async function initRecentSearches() {
  if (!state.currentUser) {
    renderRecentSearches([]);
    return;
  }
  let list = getLocalRecent();
  try {
    const data = await apiJson('/api/recent-searches');
    if (data.recent && data.recent.length > 0) {
      list = [...new Set([...list, ...data.recent])].slice(0, 5);
    }
  } catch { }
  renderRecentSearches(list);
}

export function collectCurrentFormPayload(forChat = false) {
  const halalCheck = document.getElementById('halalCheck');
  const vegCheck = document.getElementById('vegCheck');
  const specialInput = document.getElementById('specialInput');
  const customInput = document.getElementById('customCuisineInput');
  const customDislikedInput = document.getElementById('customDislikedCuisineInput');
  const timeSlider = document.getElementById('timeSlider');
  const distanceSlider = document.getElementById('distanceSlider');
  const timeInput = document.getElementById('timeInput');
  const distanceInput = document.getElementById('distanceInput');
  const budgetSlider = document.getElementById(BUDGET_UI_CONFIG.sliderId);
  const budgetInput = document.getElementById(BUDGET_UI_CONFIG.inputId);
  const trafficCheck = document.getElementById('trafficAwareCheck');

  const dietary = [];
  if (halalCheck?.checked) dietary.push('halal');
  if (vegCheck?.checked) dietary.push('vegetarian');

  const special = specialInput ? specialInput.value.trim() : '';
  const otherPreferences = special ? special.split(',').map(normalizeWishText).filter(Boolean) : [];

  if (customInput && customInput.value.trim()) {
    addCustomCuisinesFromInput();
  }
  if (customDislikedInput && customDislikedInput.value.trim()) {
    addCustomDislikedCuisinesFromInput();
  }
  const selectedLiked = Array.from(state.preferredCuisines);
  const allLocations = getAllEnteredLocations();
  const primaryLoc = allLocations[0] || '';

  const timeRaw = timeInput?.value.trim() || '';
  const distRaw = distanceInput?.value.trim() || '';
  const budgetRaw = budgetInput?.value.trim() || '';
  const parsedTime = timeRaw !== '' ? parseFloat(timeRaw) : parseFloat(timeSlider.value);
  const parsedDist = distRaw !== '' ? parseFloat(distRaw) : parseFloat(distanceSlider.value);
  const parsedBudget = budgetRaw !== '' ? parseFloat(budgetRaw) : parseFloat(budgetSlider.value);

  let maxMins = state.currentLimitType === 'time' ? parsedTime : null;
  let maxKm = state.currentLimitType === 'distance' ? parsedDist : null;
  let budget = (state.isBudgetSet && state.isBudgetPlus)
    ? BUDGET_UI_CONFIG.plusSearchVal
    : (Number.isFinite(parsedBudget) ? parsedBudget : BUDGET_UI_CONFIG.defaultVal);

  if (forChat) {
    if (!state.isTravelSet || (state.currentLimitType === 'time' && timeRaw === '')) {
      maxMins = null;
    }
    if (!state.isTravelSet || (state.currentLimitType === 'distance' && distRaw === '')) {
      maxKm = null;
    }
    if (!state.isBudgetSet || budgetRaw === '') {
      budget = null;
    }
  }

  return {
    location: primaryLoc,
    locations: allLocations,
    mode: state.currentMode,
    max_travel_minutes: maxMins,
    max_distance_km: maxKm,
    budget_per_person: budget,
    dietary_requirements: dietary,
    cuisine: selectedLiked.length === 1 ? selectedLiked[0] : (selectedLiked.length > 1 ? selectedLiked.join(', ') : null),
    liked_cuisines: selectedLiked,
    disliked_cuisines: Array.from(state.dislikedCuisines),
    other_preferences: otherPreferences,
    traffic_aware: state.currentMode === 'drive' && Boolean(trafficCheck?.checked),
  };
}

export function selectTravelMode(mode) {
  const target = ['walk', 'drive', 'transit'].includes(mode) ? mode : 'walk';
  const trafficBox = document.getElementById('trafficAwareBox');
  const trafficCheck = document.getElementById('trafficAwareCheck');
  document.querySelectorAll('.mode-btn').forEach((btn) => {
    const isTarget = btn.dataset.mode === target;
    btn.classList.toggle('bg-white', isTarget);
    btn.classList.toggle('dark:bg-slate-700', isTarget);
    btn.classList.toggle('shadow-sm', isTarget);
    btn.classList.toggle('text-brand-600', isTarget);
    btn.classList.toggle('dark:text-brand-400', isTarget);
    btn.classList.toggle('text-slate-600', !isTarget);
    btn.classList.toggle('dark:text-slate-400', !isTarget);
  });
  state.currentMode = target;
  state.activeSearchMode = target;
  if (trafficBox) trafficBox.classList.toggle('hidden', target !== 'drive');
  if (target !== 'drive' && trafficCheck) trafficCheck.checked = false;

  const limits = getModeLimits(target);
  const timeSlider = document.getElementById('timeSlider');
  const timeInput = document.getElementById('timeInput');
  const distanceSlider = document.getElementById('distanceSlider');
  const distanceInput = document.getElementById('distanceInput');

  if (state.isTravelSet) {
    if (timeInput && timeInput.value.trim() !== '') {
      const val = parseFloat(timeInput.value);
      if (Number.isFinite(val) && val > 0) {
        const clampedVal = Math.min(limits.maxTime, val);
        if (clampedVal !== val) {
          timeInput.value = formatLimitNumber(clampedVal, 2);
        }
        adaptSliderForValue('time', clampedVal, { contractToValue: true });
      } else {
        adaptSliderForValue('time', NaN);
      }
    } else {
      adaptSliderForValue('time', NaN);
      if (timeSlider) timeSlider.value = String(Math.min(limits.maxTime, limits.defaultTime));
    }
    if (distanceInput && distanceInput.value.trim() !== '') {
      const val = parseFloat(distanceInput.value);
      if (Number.isFinite(val) && val > 0) {
        const clampedVal = Math.min(limits.maxDist, val);
        if (clampedVal !== val) {
          distanceInput.value = formatLimitNumber(clampedVal, 2);
        }
        adaptSliderForValue('distance', clampedVal, { contractToValue: true });
      } else {
        adaptSliderForValue('distance', NaN);
      }
    } else {
      adaptSliderForValue('distance', NaN);
      if (distanceSlider) distanceSlider.value = String(Math.min(limits.maxDist, limits.defaultDist));
    }
  } else {
    adaptSliderForValue('time', NaN);
    adaptSliderForValue('distance', NaN);
    if (timeSlider) timeSlider.value = String(Math.min(limits.maxTime, limits.defaultTime));
    if (distanceSlider) distanceSlider.value = String(Math.min(limits.maxDist, limits.defaultDist));
  }
  updateSliderDisplayStyles();
}

export function applyFiltersToSearchForm(filters, { preserveBudgetPlus = false, preserveInactiveTravel = false } = {}) {
  if (!filters || typeof filters !== 'object') return;
  const locs = Array.isArray(filters.locations) && filters.locations.length
    ? filters.locations
    : (filters.location ? [filters.location] : ['']);
  setEnteredLocations(locs);

  selectTravelMode(filters.mode || 'walk');
  const limits = getModeLimits(state.currentMode);
  const trafficCheck = document.getElementById('trafficAwareCheck');
  if (state.currentMode === 'drive' && trafficCheck) {
    trafficCheck.checked = Boolean(filters.traffic_aware);
  }

  const timeSlider = document.getElementById('timeSlider');
  const timeInput = document.getElementById('timeInput');
  const distanceSlider = document.getElementById('distanceSlider');
  const distanceInput = document.getElementById('distanceInput');
  const budgetSlider = document.getElementById(BUDGET_UI_CONFIG.sliderId);
  const budgetInput = document.getElementById(BUDGET_UI_CONFIG.inputId);

  const rawDist = filters.max_distance_km;
  const rawTime = filters.max_travel_minutes;
  const hasDist = rawDist != null && rawDist !== '' && Number.isFinite(Number(rawDist)) && Number(rawDist) > 0;
  const hasTime = rawTime != null && rawTime !== '' && Number.isFinite(Number(rawTime)) && Number(rawTime) > 0;

  if (hasDist || hasTime) {
    state.isTravelSet = true;
    if (hasDist && distanceInput) {
      const dist = Math.min(limits.maxDist, Math.max(limits.minDist, Math.round(Number(rawDist) * 100) / 100));
      distanceInput.value = formatLimitNumber(dist, 2);
      adaptSliderForValue('distance', dist, { contractToValue: true });
      const distSliderEl = document.getElementById('distanceSlider');
      if (distSliderEl) distSliderEl.value = String(dist);
    } else if (!preserveInactiveTravel && distanceInput) {
      distanceInput.value = '';
      adaptSliderForValue('distance', NaN);
    }

    if (hasTime && timeInput) {
      const mins = Math.min(limits.maxTime, Math.max(limits.minTime, Math.round(Number(rawTime) * 100) / 100));
      timeInput.value = formatLimitNumber(mins, 2);
      adaptSliderForValue('time', mins, { contractToValue: true });
      const timeSliderEl = document.getElementById('timeSlider');
      if (timeSliderEl) timeSliderEl.value = String(mins);
    } else if (!preserveInactiveTravel && timeInput) {
      timeInput.value = '';
      adaptSliderForValue('time', NaN);
    }

    if (hasDist && !hasTime) {
      setLimitType('distance');
    } else if (hasTime && !hasDist) {
      setLimitType('time');
    } else {
      setLimitType(state.currentLimitType === 'distance' ? 'distance' : 'time');
    }
  } else {
    state.isTravelSet = false;
    if (timeInput) timeInput.value = '';
    if (distanceInput) distanceInput.value = '';
    adaptSliderForValue('time', NaN);
    adaptSliderForValue('distance', NaN);
    setLimitType('time');
  }

  if (filters.budget_per_person != null && Number.isFinite(Number(filters.budget_per_person))) {
    state.isBudgetSet = true;
    const rawBud = Math.max(BUDGET_UI_CONFIG.minVal, Math.round(Number(filters.budget_per_person) * 100) / 100);
    const keepPlus = Boolean(
      filters.budget_is_plus
      || rawBud > BUDGET_UI_CONFIG.baseMax
      || (preserveBudgetPlus && rawBud === BUDGET_UI_CONFIG.baseMax && state.isBudgetPlus),
    );
    state.isBudgetPlus = keepPlus;
    const displayBud = keepPlus ? BUDGET_UI_CONFIG.baseMax : rawBud;
    if (budgetInput) budgetInput.value = formatLimitNumber(displayBud, 2);
    adaptBudgetSliderForValue(displayBud, { contractToValue: true, keepPlusNotch: keepPlus });
  } else {
    state.isBudgetSet = false;
    state.isBudgetPlus = false;
    if (budgetInput) budgetInput.value = '';
    adaptBudgetSliderForValue(NaN);
    if (budgetSlider) budgetSlider.value = String(BUDGET_UI_CONFIG.defaultVal);
  }
  updateSliderDisplayStyles();

  const diet = filters.dietary_requirements || [];
  document.getElementById('halalCheck').checked = diet.includes('halal');
  document.getElementById('vegCheck').checked = diet.includes('vegetarian');

  state.preferredCuisines.clear();
  (filters.liked_cuisines || []).forEach((c) => {
    const clean = String(c || '').trim().toLowerCase();
    if (clean) {
      ensurePreferredChipExists(clean);
      state.preferredCuisines.add(clean);
    }
  });
  updatePreferredChipsUI();
  state.dislikedCuisines.clear();
  (filters.disliked_cuisines || []).forEach((c) => {
    const clean = String(c || '').trim().toLowerCase();
    if (clean) {
      ensureDislikedChipExists(clean);
      state.dislikedCuisines.add(clean);
    }
  });
  updateDislikedChipsUI();
  document.getElementById('specialInput').value = (filters.other_preferences || []).join(', ');
  searchRatingControl?.syncFromWishes();
  validateSpecialFilterInput(true);
  chatCallbacks.renderSummary();
}

const RATING_SLIDER_CONFIG = {
  baseMin: 3.0,
  anyNotch: 2.9,
  minVal: 1.0,
  maxVal: 5.0,
  defaultStep: 0.1,
};

let searchRatingControl = null;

function formatRatingBadge(num) {
  if (!Number.isFinite(num)) return '';
  const rounded = Math.round(num * 100) / 100;
  return Number.isInteger(rounded) ? rounded.toFixed(1) : formatLimitNumber(rounded, 2);
}

export function createRatingSliderController({
  wrapId,
  inputId,
  unitId,
  clearBtnId,
  sliderId,
  scaleMinId,
  wishInputId,
  onSync = null,
  onChange = null,
}) {
  const wrap = document.getElementById(wrapId);
  const input = document.getElementById(inputId);
  const unit = document.getElementById(unitId);
  const clearBtn = document.getElementById(clearBtnId);
  const slider = document.getElementById(sliderId);
  const scaleMin = document.getElementById(scaleMinId);
  const wishInput = document.getElementById(wishInputId);
  if (!slider || !input || !wishInput) return null;

  let lastMaxToastTs = 0;
  const applyVisual = (ratingNum, { keepSliderFloor = false } = {}) => {
    const hasRating = typeof ratingNum === 'number'
      && Number.isFinite(ratingNum)
      && ratingNum >= RATING_SLIDER_CONFIG.minVal
      && ratingNum <= RATING_SLIDER_CONFIG.maxVal;
    if (hasRating) {
      const nextMin = ratingNum < RATING_SLIDER_CONFIG.baseMin
        ? Math.max(0.9, Math.round((ratingNum - 0.1) * 10) / 10)
        : RATING_SLIDER_CONFIG.anyNotch;
      if (!keepSliderFloor) {
        slider.min = String(nextMin);
      }
      slider.max = String(RATING_SLIDER_CONFIG.maxVal);
      slider.step = countStepDecimals(ratingNum) > 1
        ? '0.01'
        : String(RATING_SLIDER_CONFIG.defaultStep);
      slider.value = String(ratingNum);
      if (document.activeElement !== input) {
        input.value = formatRatingBadge(ratingNum);
      }
    } else {
      if (!keepSliderFloor) {
        slider.min = String(RATING_SLIDER_CONFIG.anyNotch);
      }
      slider.max = String(RATING_SLIDER_CONFIG.maxVal);
      slider.step = String(RATING_SLIDER_CONFIG.defaultStep);
      slider.value = slider.min;
      if (document.activeElement !== input) {
        input.value = '';
      }
    }
    wrap?.classList.toggle('is-set', hasRating);
    input.classList.toggle('is-set', hasRating);
    unit?.classList.toggle('hidden', !hasRating);
    clearBtn?.classList.toggle('hidden', !hasRating);
    if (scaleMin) scaleMin.textContent = 'Any';
    syncLimitInputWidth(input, { emptyWidth: '3.2ch' });
    syncRangeTrackVisual(slider, hasRating);
  };

  const syncFromWishes = () => {
    const active = getActiveRatingFilterValue(wishInput.value);
    applyVisual(typeof active === 'number' ? active : null);
  };

  const setWishRating = (nextRating, { keepSliderFloor = false } = {}) => {
    const valid = typeof nextRating === 'number'
      && Number.isFinite(nextRating)
      && nextRating >= RATING_SLIDER_CONFIG.minVal
      && nextRating <= RATING_SLIDER_CONFIG.maxVal;
    const cleanVal = valid ? Math.round(nextRating * 100) / 100 : '';
    wishInput.value = applyRatingFilterToWishesRaw(wishInput.value, cleanVal);
    applyVisual(valid ? cleanVal : null, { keepSliderFloor });
    onSync?.(wishInput.value);
    onChange?.();
  };

  bindRangeSliderDrag(slider);

  wrap?.addEventListener('click', (e) => {
    if (e.target !== input) {
      input.focus();
      input.select();
    }
  });

  slider.addEventListener('input', () => {
    const val = parseFloat(slider.value);
    const curMin = parseFloat(slider.min);
    if (!Number.isFinite(val) || val <= curMin + 1e-6) {
      setWishRating(null, { keepSliderFloor: true });
    } else {
      const clamped = Math.min(RATING_SLIDER_CONFIG.maxVal, Math.max(RATING_SLIDER_CONFIG.minVal, val));
      setWishRating(clamped, { keepSliderFloor: true });
    }
  });

  slider.addEventListener('change', () => {
    const val = parseFloat(slider.value);
    const curMin = parseFloat(slider.min);
    if (!Number.isFinite(val) || val <= curMin + 1e-6) {
      applyVisual(null);
    } else {
      applyVisual(Math.min(RATING_SLIDER_CONFIG.maxVal, Math.max(RATING_SLIDER_CONFIG.minVal, val)));
    }
  });

  clearBtn?.addEventListener('click', () => {
    if (document.activeElement === input) input.blur();
    setWishRating(null);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      input.blur();
      return;
    }
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      const step = e.shiftKey ? 0.5 : 0.1;
      const cur = parseFloat(input.value);
      let next;
      if (!Number.isFinite(cur)) {
        next = e.key === 'ArrowUp' ? RATING_SLIDER_CONFIG.baseMin : RATING_SLIDER_CONFIG.minVal;
      } else {
        const delta = e.key === 'ArrowUp' ? step : -step;
        next = Math.min(RATING_SLIDER_CONFIG.maxVal, Math.max(RATING_SLIDER_CONFIG.minVal, Math.round((cur + delta) * 100) / 100));
      }
      input.value = formatRatingBadge(next);
      setWishRating(next);
    }
  });

  input.addEventListener('input', (e) => {
    const stripped = String(e.target.value || '').replace(/\++$/, '');
    const cleaned = sanitizeDecimalText(stripped);
    if (cleaned !== e.target.value) e.target.value = cleaned;
    const raw = e.target.value.trim();
    if (raw === '') {
      setWishRating(null);
      return;
    }
    const val = parseFloat(raw);
    if (!Number.isFinite(val)) return;
    if (val > RATING_SLIDER_CONFIG.maxVal) {
      e.target.value = formatRatingBadge(RATING_SLIDER_CONFIG.maxVal);
      setWishRating(RATING_SLIDER_CONFIG.maxVal);
      const now = Date.now();
      if (now - lastMaxToastTs > 1500) {
        lastMaxToastTs = now;
        showToast('Maximum Google rating is 5.0 stars.', 'warning');
      }
    } else if (val >= RATING_SLIDER_CONFIG.minVal) {
      setWishRating(val);
    }
  });

  input.addEventListener('change', (e) => {
    const raw = e.target.value.trim();
    if (raw === '') {
      setWishRating(null);
      return;
    }
    let val = parseFloat(raw);
    if (!Number.isFinite(val) || val < RATING_SLIDER_CONFIG.minVal) {
      val = RATING_SLIDER_CONFIG.minVal;
      showToast('Minimum Google rating is 1.0 stars.', 'warning');
    } else if (val > RATING_SLIDER_CONFIG.maxVal) {
      val = RATING_SLIDER_CONFIG.maxVal;
      showToast('Maximum Google rating is 5.0 stars.', 'warning');
    }
    val = Math.round(val * 100) / 100;
    e.target.value = formatRatingBadge(val);
    setWishRating(val);
  });

  wishInput.addEventListener('input', () => {
    syncFromWishes();
  });

  wishInput.addEventListener('blur', () => {
    const normalized = wishInput.value
      .split(',')
      .map(normalizeWishText)
      .filter(Boolean)
      .join(', ');
    if (normalized !== wishInput.value.trim()) {
      wishInput.value = normalized;
    }
    syncFromWishes();
    onSync?.(wishInput.value);
  });

  syncFromWishes();
  return { syncFromWishes };
}

function setSpecialInputError(message = '') {
  const specialInput = document.getElementById('specialInput');
  const specialErrEl = document.getElementById('specialInputError');
  if (!specialInput || !specialErrEl) return;
  const err = String(message || '').trim();
  if (err) {
    specialErrEl.textContent = err;
    specialErrEl.classList.remove('hidden');
    specialInput.classList.add('border-rose-400', 'dark:border-rose-500', 'focus:ring-rose-500', 'focus:border-rose-500');
    specialInput.classList.remove('border-slate-300', 'dark:border-slate-700', 'focus:ring-brand-500', 'focus:border-brand-500');
  } else {
    specialErrEl.textContent = '';
    specialErrEl.classList.add('hidden');
    specialInput.classList.remove('border-rose-400', 'dark:border-rose-500', 'focus:ring-rose-500', 'focus:border-rose-500');
    specialInput.classList.add('border-slate-300', 'dark:border-slate-700', 'focus:ring-brand-500', 'focus:border-brand-500');
  }
}

export function validateSpecialFilterInput(showErrorUi = true) {
  const specialInput = document.getElementById('specialInput');
  const raw = specialInput ? specialInput.value.trim() : '';
  const items = raw ? raw.split(',').map(normalizeWishText).filter(Boolean) : [];
  const err = validateEnglishWishesInput(items, 'Special requests');
  if (showErrorUi) setSpecialInputError(err);
  return err;
}

export function applyUserToSearchForm(user) {
  if (!user) return;
  let targetMode = state.currentMode || 'walk';
  const modeLimits = getModeLimits(targetMode);
  const userMins = user.max_travel_time_minutes != null ? Number(user.max_travel_time_minutes) : null;
  const userDist = user.max_distance_km != null ? Number(user.max_distance_km) : null;
  if (
    (Number.isFinite(userMins) && userMins > modeLimits.maxTime)
    || (Number.isFinite(userDist) && userDist > modeLimits.maxDist)
  ) {
    targetMode = 'transit';
  }
  applyFiltersToSearchForm({
    locations: Array.isArray(user.location) && user.location.length ? user.location : [''],
    mode: targetMode,
    max_travel_minutes: user.max_travel_time_minutes ?? null,
    max_distance_km: user.max_distance_km ?? null,
    budget_per_person: user.budget_per_person || null,
    dietary_requirements: user.dietary_requirements || [],
    liked_cuisines: user.liked_cuisines || [],
    disliked_cuisines: user.disliked_cuisines || [],
    other_preferences: user.other_preferences || [],
  });
  chatCallbacks.refreshGreetingIfIdle();
}

function countStepDecimals(num) {
  const str = String(num);
  const idx = str.indexOf('.');
  return idx === -1 ? 0 : str.length - idx - 1;
}

function computeRangeValueFromClientX(slider, clientX) {
  const rect = slider.getBoundingClientRect();
  if (!rect || rect.width <= 0) return parseFloat(slider.value);
  const min = parseFloat(slider.min);
  const max = parseFloat(slider.max);
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
    return Number.isFinite(min) ? min : 0;
  }
  const stepRaw = parseFloat(slider.step);
  const step = Number.isFinite(stepRaw) && stepRaw > 0 ? stepRaw : 1;
  const thumbRadius = 9;
  const usableWidth = Math.max(1, rect.width - thumbRadius * 2);
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left - thumbRadius) / usableWidth));
  const raw = min + ratio * (max - min);
  const steps = Math.round((raw - min) / step);
  const decimals = Math.min(4, Math.max(countStepDecimals(step), countStepDecimals(min)));
  let next = Number((min + steps * step).toFixed(decimals));
  if (next > max) {
    const maxSteps = Math.floor((max - min + 1e-9) / step);
    next = Number((min + maxSteps * step).toFixed(decimals));
  }
  return Math.min(max, Math.max(min, next));
}

function bindRangeSliderDrag(slider) {
  if (!slider) return;
  slider.draggable = false;

  const stopBrowserDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };
  slider.addEventListener('dragstart', stopBrowserDrag);
  slider.addEventListener('selectstart', stopBrowserDrag);

  let activePointerId = null;

  const applyClientX = (clientX, { forceInput = false } = {}) => {
    const nextVal = computeRangeValueFromClientX(slider, clientX);
    const nextStr = String(nextVal);
    if (forceInput || nextStr !== slider.value) {
      slider.value = nextStr;
      slider.dispatchEvent(new Event('input', { bubbles: true }));
    }
  };

  const finishDrag = (e, { emitChange = true } = {}) => {
    if (activePointerId === null) return;
    if (e && e.pointerId !== undefined && e.pointerId !== activePointerId) return;
    const ptrId = activePointerId;
    activePointerId = null;
    slider.classList.remove('is-dragging');
    try {
      if (slider.hasPointerCapture?.(ptrId)) {
        slider.releasePointerCapture(ptrId);
      }
    } catch { }
    if (emitChange) {
      slider.dispatchEvent(new Event('change', { bubbles: true }));
    }
  };

  slider.addEventListener('pointerdown', (e) => {
    if (slider.disabled) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;

    e.preventDefault();
    e.stopPropagation();
    try {
      window.getSelection()?.removeAllRanges();
    } catch { }
    try {
      slider.focus({ preventScroll: true });
    } catch { }

    activePointerId = e.pointerId;
    slider.classList.add('is-dragging');
    try {
      slider.setPointerCapture(e.pointerId);
    } catch { }

    applyClientX(e.clientX, { forceInput: true });
  });

  slider.addEventListener('pointermove', (e) => {
    if (activePointerId === null || e.pointerId !== activePointerId) return;
    e.preventDefault();
    applyClientX(e.clientX);
  });

  slider.addEventListener('pointerup', (e) => finishDrag(e, { emitChange: true }));
  slider.addEventListener('pointercancel', (e) => finishDrag(e, { emitChange: true }));
  slider.addEventListener('lostpointercapture', (e) => finishDrag(e, { emitChange: true }));
}

function bindEditableSliderField({
  wrapId,
  inputId,
  sliderId,
  setIsSet,
  onAdapt,
  getArrowStep,
  getMinVal,
  getMaxVal,
  formatMinToast,
  formatMaxToast = null,
  stripPlusOnInput = false,
  resolveSliderValue = null,
  onExceedMax = null,
  isAtMaxPlus = null,
  onInputEdit = null,
  onArrowStep = null,
}) {
  const slider = document.getElementById(sliderId);
  const input = document.getElementById(inputId);
  const wrap = document.getElementById(wrapId);
  let lastMaxToastTs = 0;

  const notifyMaxExceeded = (maxVal) => {
    const now = Date.now();
    if (formatMaxToast && now - lastMaxToastTs > 1500) {
      lastMaxToastTs = now;
      showToast(formatMaxToast(maxVal), 'warning');
    }
  };

  bindRangeSliderDrag(slider);

  wrap?.addEventListener('click', (e) => {
    if (e.target !== input && input) {
      input.focus();
      input.select();
    }
  });

  slider?.addEventListener('input', (e) => {
    const val = parseFloat(e.target.value);
    setIsSet(true);
    if (input && Number.isFinite(val)) {
      const resolved = resolveSliderValue ? resolveSliderValue(val, slider) : { inputVal: formatLimitNumber(val, 2) };
      input.value = resolved.inputVal;
    }
    updateSliderDisplayStyles();
    chatCallbacks.renderSummary();
  });

  slider?.addEventListener('change', (e) => {
    const val = parseFloat(e.target.value);
    if (Number.isFinite(val) && val > 0) {
      const resolved = resolveSliderValue
        ? resolveSliderValue(val, slider)
        : { adaptVal: val, adaptOpts: { contractToValue: true } };
      onAdapt(resolved.adaptVal ?? val, resolved.adaptOpts ?? { contractToValue: true });
    }
    updateSliderDisplayStyles();
    chatCallbacks.renderSummary();
  });

  input?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      input.blur();
      return;
    }
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      const { step, fallback } = getArrowStep(e.shiftKey);
      const signedDelta = e.key === 'ArrowUp' ? step : -step;
      const current = parseFloat(input.value);
      const seed = Number.isFinite(current) ? current : (parseFloat(slider?.value || '') || fallback);
      const minAllowed = getMinVal();
      const maxAllowed = getMaxVal();
      if (onArrowStep && onArrowStep(e.key, seed, step, minAllowed, maxAllowed)) {
        return;
      }
      const nextVal = Math.min(maxAllowed, Math.max(minAllowed, Math.round((seed + signedDelta) * 100) / 100));
      input.value = formatLimitNumber(nextVal, 2);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });

  input?.addEventListener('input', (e) => {
    const hadTrailingPlus = stripPlusOnInput && /\++$/.test(String(e.target.value || ''));
    onInputEdit?.();
    const rawStr = stripPlusOnInput ? String(e.target.value || '').replace(/\++$/, '') : e.target.value;
    const cleaned = sanitizeDecimalText(rawStr);
    if (cleaned !== e.target.value) {
      e.target.value = cleaned;
    }
    const raw = e.target.value.trim();
    if (raw === '') {
      setIsSet(false);
      onAdapt(NaN);
    } else {
      const val = parseFloat(raw);
      const maxAllowed = getMaxVal();
      if (Number.isFinite(val) && val > 0) {
        if (val > maxAllowed || (hadTrailingPlus && val >= maxAllowed)) {
          setIsSet(true);
          if (onExceedMax) {
            e.target.value = onExceedMax(val, { hadTrailingPlus, maxAllowed });
          } else {
            e.target.value = formatLimitNumber(maxAllowed, 2);
            onAdapt(maxAllowed, { contractToValue: true });
          }
          if (val > maxAllowed) {
            notifyMaxExceeded(maxAllowed);
          }
        } else {
          setIsSet(true);
          onAdapt(val, { contractToValue: true });
        }
      }
    }
    updateSliderDisplayStyles();
    chatCallbacks.renderSummary();
  });

  input?.addEventListener('change', (e) => {
    const raw = e.target.value.trim();
    if (raw === '') {
      onInputEdit?.();
      setIsSet(false);
      onAdapt(NaN);
      updateSliderDisplayStyles();
      chatCallbacks.renderSummary();
      return;
    }
    let val = parseFloat(raw);
    const minAllowed = getMinVal();
    const maxAllowed = getMaxVal();
    if (!Number.isFinite(val) || val < minAllowed) {
      onInputEdit?.();
      val = minAllowed;
      showToast(formatMinToast(val), 'warning');
      val = Math.round(val * 100) / 100;
      e.target.value = formatLimitNumber(val, 2);
      setIsSet(true);
      onAdapt(val, { contractToValue: true });
    } else if (val > maxAllowed) {
      setIsSet(true);
      if (onExceedMax) {
        e.target.value = onExceedMax(val, { hadTrailingPlus: false, maxAllowed });
      } else {
        e.target.value = formatLimitNumber(maxAllowed, 2);
        onAdapt(maxAllowed, { contractToValue: true });
      }
      notifyMaxExceeded(maxAllowed);
    } else if (isAtMaxPlus && isAtMaxPlus(val, maxAllowed)) {
      setIsSet(true);
      e.target.value = formatLimitNumber(maxAllowed, 2);
      onAdapt(maxAllowed, { contractToValue: true, keepPlusNotch: true });
    } else {
      onInputEdit?.();
      val = Math.round(val * 100) / 100;
      e.target.value = formatLimitNumber(val, 2);
      setIsSet(true);
      onAdapt(val, { contractToValue: true });
    }
    updateSliderDisplayStyles();
    chatCallbacks.renderSummary();
  });
}

export function initFiltersControls() {
  const customInput = document.getElementById('customCuisineInput');
  selectTravelMode(state.currentMode || 'walk');

  document.querySelectorAll('.mode-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      selectTravelMode(btn.dataset.mode);
      chatCallbacks.renderSummary();
      if (state.lastMatches.length > 0 || state.lastAlternatives.length > 0) {
        renderResults(state.lastMatches, state.lastAlternatives);
      }
    });
  });

  document.getElementById('addLocationRowBtn')?.addEventListener('click', () => addExtraLocationInput(''));

  const useGpsBtn = document.getElementById('useGpsBtn');
  useGpsBtn?.addEventListener('click', () => {
    if (!navigator.geolocation) {
      showToast('Geolocation is not supported by your browser.', 'warning');
      return;
    }
    const origHtml = useGpsBtn.innerHTML;
    useGpsBtn.disabled = true;
    useGpsBtn.innerHTML = '<svg class="animate-spin w-3 h-3 text-brand-600" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg><span>Locating...</span>';
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude.toFixed(5);
        const lng = pos.coords.longitude.toFixed(5);
        document.getElementById('locationInput').value = `${lat}, ${lng}`;
        useGpsBtn.disabled = false;
        useGpsBtn.innerHTML = origHtml;
        showToast('Updated starting location from GPS.', 'success');
        chatCallbacks.renderSummary();
      },
      (err) => {
        showToast(`Could not access GPS location: ${err.message || 'Permission denied'}`, 'error');
        useGpsBtn.disabled = false;
        useGpsBtn.innerHTML = origHtml;
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  });

  document.querySelectorAll('.preset-pill').forEach((pill) => {
    pill.addEventListener('click', () => {
      document.getElementById('locationInput').value = pill.dataset.loc;
      chatCallbacks.renderSummary();
    });
  });

  document.getElementById('limitTypeTimeBtn')?.addEventListener('click', () => {
    setLimitType('time', { activateIfUnset: true });
    chatCallbacks.renderSummary();
  });
  document.getElementById('limitTypeDistBtn')?.addEventListener('click', () => {
    setLimitType('distance', { activateIfUnset: true });
    chatCallbacks.renderSummary();
  });

  ['time', 'distance'].forEach((type) => {
    const cfg = LIMIT_UI_CONFIG[type];
    bindEditableSliderField({
      wrapId: cfg.wrapId,
      inputId: cfg.inputId,
      sliderId: cfg.sliderId,
      setIsSet: (v) => { state.isTravelSet = v; },
      onAdapt: (val, opts) => adaptSliderForValue(type, val, opts),
      getArrowStep: (shiftKey) => {
        const limits = getModeLimits();
        return {
          step: type === 'time' ? (shiftKey ? 5 : 1) : (shiftKey ? 1 : 0.1),
          fallback: limits[cfg.defaultKey],
        };
      },
      getMinVal: () => getModeLimits()[cfg.minKey],
      getMaxVal: () => getModeLimits()[cfg.maxKey],
      formatMinToast: (val) => {
        const minLabel = cfg.unit === 'km' ? 'distance' : 'travel time';
        return `Minimum ${minLabel} is ${val} ${val === 1 && cfg.unit === 'mins' ? 'min' : cfg.unit}.`;
      },
      formatMaxToast: (val) => {
        const maxLabel = cfg.unit === 'km' ? 'distance' : 'travel time';
        return `Maximum ${maxLabel} for ${state.currentMode} is ${val} ${cfg.unit}.`;
      },
    });
  });

  bindEditableSliderField({
    wrapId: BUDGET_UI_CONFIG.wrapId,
    inputId: BUDGET_UI_CONFIG.inputId,
    sliderId: BUDGET_UI_CONFIG.sliderId,
    setIsSet: (v) => { state.isBudgetSet = v; },
    onAdapt: (val, opts) => {
      adaptBudgetSliderForValue(val, opts);
      if (!Number.isFinite(val) || val <= 0) {
        state.isBudgetPlus = false;
        const slider = document.getElementById(BUDGET_UI_CONFIG.sliderId);
        if (slider) slider.value = String(BUDGET_UI_CONFIG.defaultVal);
      }
    },
    getArrowStep: (shiftKey) => ({
      step: shiftKey ? 5 : 1,
      fallback: BUDGET_UI_CONFIG.defaultVal,
    }),
    getMinVal: () => BUDGET_UI_CONFIG.minVal,
    getMaxVal: () => BUDGET_UI_CONFIG.baseMax,
    formatMinToast: (val) => `Minimum budget per person is SGD $${val}.`,
    formatMaxToast: () => 'Maximum budget per person is SGD $100+ (Fine Dine).',
    stripPlusOnInput: true,
    onExceedMax: () => {
      state.isBudgetPlus = true;
      adaptBudgetSliderForValue(BUDGET_UI_CONFIG.baseMax, { contractToValue: true, keepPlusNotch: true });
      return String(BUDGET_UI_CONFIG.baseMax);
    },
    isAtMaxPlus: (val, maxAllowed) => Boolean(state.isBudgetPlus && val >= maxAllowed),
    onArrowStep: (key, seed, step, _minAllowed, maxAllowed) => {
      const inputEl = document.getElementById(BUDGET_UI_CONFIG.inputId);
      if (key === 'ArrowUp') {
        if (state.isBudgetPlus) return true;
        if (seed >= maxAllowed || seed + step > maxAllowed) {
          state.isBudgetSet = true;
          state.isBudgetPlus = true;
          if (inputEl) inputEl.value = String(BUDGET_UI_CONFIG.baseMax);
          adaptBudgetSliderForValue(BUDGET_UI_CONFIG.baseMax, { contractToValue: true, keepPlusNotch: true });
          updateSliderDisplayStyles();
          chatCallbacks.renderSummary();
          return true;
        }
      } else if (key === 'ArrowDown' && state.isBudgetPlus) {
        state.isBudgetSet = true;
        state.isBudgetPlus = false;
        if (inputEl) inputEl.value = String(BUDGET_UI_CONFIG.baseMax);
        adaptBudgetSliderForValue(BUDGET_UI_CONFIG.baseMax, { contractToValue: true, keepPlusNotch: false });
        updateSliderDisplayStyles();
        chatCallbacks.renderSummary();
        return true;
      }
      return false;
    },
    resolveSliderValue: (val, sliderEl) => {
      const sliderMax = sliderEl ? parseFloat(sliderEl.max) : NaN;
      const isPlusNotch = Number.isFinite(sliderMax)
        && sliderMax === BUDGET_UI_CONFIG.plusSliderVal
        && val >= BUDGET_UI_CONFIG.plusSliderVal;
      state.isBudgetPlus = isPlusNotch;
      return {
        inputVal: isPlusNotch ? String(BUDGET_UI_CONFIG.baseMax) : formatLimitNumber(val, 2),
        adaptVal: isPlusNotch ? BUDGET_UI_CONFIG.baseMax : val,
        adaptOpts: { contractToValue: true, keepPlusNotch: isPlusNotch },
      };
    },
    onInputEdit: () => {
      state.isBudgetPlus = false;
    },
  });

  document.querySelectorAll('#preferredChipsContainer .prefer-chip').forEach((chip) => {
    chip.addEventListener('click', () => togglePreferredCuisine(chip.dataset.cuisine));
  });

  document.getElementById('addCustomCuisineBtn')?.addEventListener('click', addCustomCuisinesFromInput);
  customInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addCustomCuisinesFromInput();
    }
  });

  document.getElementById('clearPreferredBtn')?.addEventListener('click', () => {
    state.preferredCuisines.clear();
    if (customInput) customInput.value = '';
    updatePreferredChipsUI();
    chatCallbacks.renderSummary();
  });

  document.querySelectorAll('#dislikedChipsContainer .dislike-chip').forEach((chip) => {
    chip.addEventListener('click', () => toggleDislikedCuisine(chip.dataset.cuisine));
  });

  const customDislikedInput = document.getElementById('customDislikedCuisineInput');
  document.getElementById('addCustomDislikedCuisineBtn')?.addEventListener('click', addCustomDislikedCuisinesFromInput);
  customDislikedInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addCustomDislikedCuisinesFromInput();
    }
  });

  document.getElementById('clearDislikedBtn')?.addEventListener('click', () => {
    state.dislikedCuisines.clear();
    if (customDislikedInput) customDislikedInput.value = '';
    updateDislikedChipsUI();
    chatCallbacks.renderSummary();
  });

  const specialInput = document.getElementById('specialInput');
  const specialErrEl = document.getElementById('specialInputError');
  searchRatingControl = createRatingSliderController({
    wrapId: 'ratingDisplayWrap',
    inputId: 'ratingInput',
    unitId: 'ratingUnitLabel',
    clearBtnId: 'ratingClearBtn',
    sliderId: 'ratingSlider',
    scaleMinId: 'ratingScaleMin',
    wishInputId: 'specialInput',
    onSync: () => validateSpecialFilterInput(true),
    onChange: () => chatCallbacks.renderSummary(),
  });
  specialInput?.addEventListener('input', () => {
    if (specialErrEl && !specialErrEl.classList.contains('hidden')) {
      validateSpecialFilterInput(true);
    }
  });

  const searchForm = document.getElementById('searchForm');
  searchForm?.addEventListener('input', () => chatCallbacks.renderSummary());
  searchForm?.addEventListener('change', () => chatCallbacks.renderSummary());

  searchForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fromChat = state.searchTriggeredFromChat;
    state.searchTriggeredFromChat = false;

    const searchBtn = document.getElementById('searchBtn');
    const emptyState = document.getElementById('emptyState');
    const statusBanner = document.getElementById('statusBanner');
    const statusText = document.getElementById('statusText');
    const statusIcon = document.getElementById('statusIcon');
    const resultsHeader = document.getElementById('resultsHeader');
    const resultsCount = document.getElementById('resultsCount');

    const failValidation = (msg, focusEl = null) => {
      showToast(msg, 'warning');
      if (!fromChat && focusEl) focusEl.focus();
      if (fromChat) chatCallbacks.postSearchOutcome({ errorMessage: msg, fromChat });
    };

    const limits = getModeLimits();
    const timeRaw = document.getElementById('timeInput')?.value.trim() || '';
    const distRaw = document.getElementById('distanceInput')?.value.trim() || '';
    if (state.currentLimitType === 'time' && timeRaw !== '') {
      const minsVal = parseFloat(timeRaw);
      if (!Number.isFinite(minsVal) || minsVal < limits.minTime || minsVal > limits.maxTime) {
        failValidation(`Search travel time for ${state.currentMode} must be ${limits.minTime}–${limits.maxTime} mins — use the slider to scale down or switch mode.`);
        return;
      }
    }
    if (state.currentLimitType === 'distance' && distRaw !== '') {
      const kmVal = parseFloat(distRaw);
      if (!Number.isFinite(kmVal) || kmVal < limits.minDist || kmVal > limits.maxDist) {
        failValidation(`Search distance for ${state.currentMode} must be ${limits.minDist}–${limits.maxDist} km — use the slider to scale down or switch mode.`);
        return;
      }
    }

    const budgetRaw = document.getElementById(BUDGET_UI_CONFIG.inputId)?.value.trim() || '';
    if (state.isBudgetSet && budgetRaw !== '') {
      const budVal = parseFloat(budgetRaw);
      if (!Number.isFinite(budVal) || budVal < BUDGET_UI_CONFIG.minVal || budVal > BUDGET_UI_CONFIG.baseMax) {
        failValidation(
          `Search budget must be SGD $${BUDGET_UI_CONFIG.minVal}–$${BUDGET_UI_CONFIG.baseMax}+ — adjust the slider or type a value within range.`,
          document.getElementById(BUDGET_UI_CONFIG.inputId),
        );
        return;
      }
    }

    const specialErr = validateSpecialFilterInput(true);
    if (specialErr) {
      failValidation(specialErr, specialInput);
      return;
    }

    const payload = collectCurrentFormPayload(false);
    if (!payload.location) {
      failValidation('Please enter a starting location before searching.', document.getElementById('locationInput'));
      return;
    }

    const allLocations = payload.locations || [];
    state.activeSearchMode = payload.mode;
    state.activeBudgetLimit = payload.budget_per_person ?? null;
    state.activeBudgetIsPlus = isBudgetPlusDisplay(state.activeBudgetLimit, state.isBudgetSet);
    state.compareKeys.clear();
    chatCallbacks.renderSummary();
    saveLocalRecent(allLocations.length > 1 ? allLocations.join(' + ') : payload.location);

    searchBtn.disabled = true;
    searchBtn.innerHTML = '<svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline-block" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Analyzing & Ranking...';

    let activeModelLabel = 'Gemini AI';
    try {
      const mData = await apiJson('/api/active-model');
      if (mData.active_model) activeModelLabel = mData.active_model;
    } catch { }

    if (emptyState) emptyState.classList.add('hidden');
    document.getElementById('mapSection')?.classList.add('hidden');
    resultsHeader?.classList.add('hidden');

    statusBanner.className = 'p-4 rounded-2xl border text-sm flex items-center gap-3 bg-amber-50 dark:bg-amber-950/50 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200';
    statusIcon.innerHTML = '<svg class="animate-spin w-4 h-4 text-amber-600 dark:text-amber-400" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';
    statusText.textContent = `Searching near ${allLocations.join(' & ')} (${activeModelLabel})...`;
    statusBanner.classList.remove('hidden');

    renderResultsSkeleton(activeModelLabel);

    let pollingActive = true;
    const pollAbort = new AbortController();
    let pollInFlight = false;
    const modelPollTimer = setInterval(async () => {
      if (!pollingActive || pollInFlight) return;
      pollInFlight = true;
      try {
        const pData = await apiJson('/api/active-model', { signal: pollAbort.signal });
        if (pollingActive && pData.active_model && pData.active_model !== activeModelLabel) {
          activeModelLabel = pData.active_model;
          statusText.textContent = `Searching near ${allLocations.join(' & ')} (${activeModelLabel})...`;
          updateResultsSkeletonModel(activeModelLabel);
        }
      } catch {
        // Ignore transient or aborted status polls while a search request is active.
      } finally {
        pollInFlight = false;
      }
    }, 500);

    const stopModelPolling = () => {
      if (!pollingActive) return;
      pollingActive = false;
      clearInterval(modelPollTimer);
      pollAbort.abort();
    };

    try {
      const data = await apiJson('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      stopModelPolling();

      if (data.message && (!data.matches || data.matches.length === 0)) {
        statusBanner.className = 'p-4 rounded-2xl border text-sm flex items-center gap-3 bg-amber-50 dark:bg-amber-950/50 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200';
        statusIcon.innerHTML = '<i data-lucide="info" class="w-4 h-4 text-amber-600 dark:text-amber-400"></i>';
        statusText.textContent = data.message;
        refreshIcons(statusBanner);
        resultsHeader.classList.remove('hidden');
        resultsCount.textContent = '0 Recommendations';
        state.lastMatches = [];
        state.lastAlternatives = [];
        renderResults([], []);
        chatCallbacks.postSearchOutcome({ emptyMessage: data.message, fromChat });
        return;
      }

      const matches = data.matches || [];
      const alternatives = data.alternatives || [];
      const modelUsed = data.model_used || activeModelLabel;
      const breakdown = data.cuisines_breakdown || {};
      const breakdownKeys = Object.keys(breakdown);
      let breakdownStr = '';
      if (breakdownKeys.length > 1) {
        const parts = breakdownKeys.map((k) => `${formatCuisineLabel(k)}: ${breakdown[k]}`);
        breakdownStr = ` • Divided across ${breakdownKeys.length} cuisines (${parts.join(', ')})`;
      } else if (breakdownKeys.length === 1) {
        breakdownStr = ` • Cuisine: ${formatCuisineLabel(breakdownKeys[0])}`;
      }

      state.lastOrigin = data.origin || null;
      state.lastInputOrigins = data.input_origins || data.origins || [];
      state.lastMatches = matches;
      state.lastAlternatives = alternatives;

      const totalFound = matches.length + alternatives.length;
      const midpointNote = state.lastInputOrigins.length > 1
        ? ` • 🎯 In-between ${state.lastInputOrigins.map((o) => o.query).join(' & ')}`
        : '';

      statusBanner.className = 'p-4 rounded-2xl border text-sm flex items-center gap-3 bg-emerald-50 dark:bg-emerald-950/50 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200';
      statusIcon.innerHTML = '<i data-lucide="check-circle-2" class="w-4 h-4 text-emerald-600 dark:text-emerald-400"></i>';
      statusText.textContent = `Found ${matches.length} direct match${matches.length === 1 ? '' : 'es'} and ${alternatives.length} alternative${alternatives.length === 1 ? '' : 's'}${midpointNote}${breakdownStr} • Ranked by ${modelUsed}`;
      refreshIcons(statusBanner);

      resultsHeader.classList.remove('hidden');
      resultsCount.textContent = `${totalFound} Restaurant Recommendation${totalFound === 1 ? '' : 's'}`;
      const subtextEl = document.getElementById('resultsSubtext');
      if (subtextEl) {
        subtextEl.textContent = `Verified with Google Places & official MUIS records • Ranked by ${modelUsed}`;
      }

      renderResults(state.lastMatches, state.lastAlternatives);
      chatCallbacks.postSearchOutcome({ matches, alternatives, modelUsed, fromChat });
    } catch (error) {
      stopModelPolling();
      if (/special requests?/i.test(error.message || '')) {
        setSpecialInputError(error.message);
      }
      statusBanner.className = 'p-4 rounded-2xl border text-sm flex items-center gap-3 bg-rose-50 dark:bg-rose-950/50 border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200';
      statusIcon.innerHTML = '<i data-lucide="alert-circle" class="w-4 h-4 text-rose-600 dark:text-rose-400"></i>';
      statusText.textContent = error.message;
      refreshIcons(statusBanner);
      document.getElementById('resultsList').innerHTML = '';
      chatCallbacks.postSearchOutcome({ errorMessage: error.message, fromChat });
    } finally {
      stopModelPolling();
      searchBtn.disabled = false;
      searchBtn.innerHTML = '<i data-lucide="search" class="w-4 h-4"></i> Find Matching Restaurants';
      refreshIcons(searchBtn);
    }
  });
}
