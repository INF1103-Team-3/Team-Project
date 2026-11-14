import {
  formatCuisineLabel,
  RECENT_KEY,
  refreshIcons,
  state,
} from './state.js';
import { apiJson } from './api.js';
import { showToast } from './toast.js';
import { renderResults, renderResultsSkeleton } from './results.js';

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

function syncLimitInputWidth(inputEl) {
  if (!inputEl) return;
  const text = inputEl.value.trim();
  inputEl.style.width = text === ''
    ? '5.8ch'
    : `${Math.min(7.5, Math.max(1.4, text.length + 0.35))}ch`;
}

function adaptSliderForValue(type, rawVal, { contractToValue = true } = {}) {
  const cfg = LIMIT_UI_CONFIG[type];
  const slider = cfg ? document.getElementById(cfg.sliderId) : null;
  if (!slider) return;
  const limits = getModeLimits();
  const modeMax = limits[cfg.maxKey];
  const modeMin = limits[cfg.minKey];

  if (!Number.isFinite(rawVal) || rawVal <= 0) {
    slider.min = String(cfg.baseMin);
    slider.max = String(modeMax);
    slider.step = String(cfg.defaultStep);
    return;
  }

  const clampedMinFloor = Math.min(cfg.baseMin, Math.max(modeMin, rawVal));
  const currentMin = parseFloat(slider.min);
  const currentMax = parseFloat(slider.max);
  const nextMin = contractToValue
    ? (rawVal < cfg.baseMin ? clampedMinFloor : cfg.baseMin)
    : (Number.isFinite(currentMin) ? Math.min(currentMin, clampedMinFloor) : cfg.baseMin);
  const nextMax = contractToValue
    ? Math.max(modeMax, rawVal)
    : Math.max(modeMax, Number.isFinite(currentMax) ? currentMax : modeMax, rawVal);

  const needsFineStep = type === 'time'
    ? !Number.isInteger(rawVal)
    : (rawVal < 0.1 || Math.abs(Math.round(rawVal * 10) - rawVal * 10) > 1e-6);

  slider.min = String(nextMin);
  slider.max = String(nextMax);
  slider.step = needsFineStep ? (type === 'time' ? '0.1' : '0.01') : String(cfg.defaultStep);
  slider.value = String(Math.max(nextMin, Math.min(nextMax, rawVal)));
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

  if (state.isTravelSet && Number.isFinite(val)) {
    if (val > limits[cfg.maxKey]) {
      hintEl.textContent = `Slider scaled to ${formatLimitNumber(val, 2)} ${cfg.unit} (${state.currentMode} search max: ${limits[cfg.maxKey]} ${cfg.unit})`;
      hintEl.classList.remove('hidden');
      return;
    }
    if (val < limits[cfg.minKey]) {
      hintEl.textContent = `Minimum ${state.currentMode} limit is ${limits[cfg.minKey]} ${cfg.unit}`;
      hintEl.classList.remove('hidden');
      return;
    }
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
  const budgetDisplay = document.getElementById('budgetDisplay');
  if (!timeInput || !distanceInput || !budgetDisplay) return;

  const setCls = 'text-xs font-bold text-brand-600 dark:text-brand-400';
  const unsetCls = 'text-xs font-bold text-slate-400 dark:text-slate-500';

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
  });

  budgetDisplay.className = state.isBudgetSet ? setCls : unsetCls;
  if (!state.isBudgetSet) {
    budgetDisplay.textContent = 'Not set';
  }
  updateLimitRangeHint();
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
        adaptSliderForValue(targetType, typedNum, { contractToValue: true });
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
  const budgetSlider = document.getElementById('budgetSlider');
  const trafficCheck = document.getElementById('trafficAwareCheck');

  const dietary = [];
  if (halalCheck?.checked) dietary.push('halal');
  if (vegCheck?.checked) dietary.push('vegetarian');

  const special = specialInput ? specialInput.value.trim() : '';
  const otherPreferences = special ? special.split(',').map((s) => s.trim()).filter(Boolean) : [];

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
  const parsedTime = timeRaw !== '' ? parseFloat(timeRaw) : parseFloat(timeSlider.value);
  const parsedDist = distRaw !== '' ? parseFloat(distRaw) : parseFloat(distanceSlider.value);

  let maxMins = state.currentLimitType === 'time' ? parsedTime : null;
  let maxKm = state.currentLimitType === 'distance' ? parsedDist : null;
  let budget = parseFloat(budgetSlider.value);

  if (forChat) {
    if (!state.isTravelSet || (state.currentLimitType === 'time' && timeRaw === '')) {
      maxMins = null;
    }
    if (!state.isTravelSet || (state.currentLimitType === 'distance' && distRaw === '')) {
      maxKm = null;
    }
    if (!state.isBudgetSet) {
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
      adaptSliderForValue('time', Number.isFinite(val) && val > 0 ? val : NaN, { contractToValue: true });
    } else {
      adaptSliderForValue('time', NaN);
      if (timeSlider) timeSlider.value = String(Math.min(limits.maxTime, limits.defaultTime));
    }
    if (distanceInput && distanceInput.value.trim() !== '') {
      const val = parseFloat(distanceInput.value);
      adaptSliderForValue('distance', Number.isFinite(val) && val > 0 ? val : NaN, { contractToValue: true });
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

export function applyFiltersToSearchForm(filters) {
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
  const budgetSlider = document.getElementById('budgetSlider');
  const budgetDisplay = document.getElementById('budgetDisplay');

  if (filters.max_distance_km != null && filters.max_travel_minutes == null) {
    state.isTravelSet = true;
    const dist = Math.max(limits.minDist, Math.round(filters.max_distance_km * 100) / 100);
    distanceInput.value = formatLimitNumber(dist, 2);
    timeInput.value = '';
    adaptSliderForValue('distance', dist, { contractToValue: true });
    setLimitType('distance');
  } else if (filters.max_travel_minutes != null) {
    state.isTravelSet = true;
    const mins = Math.max(limits.minTime, Math.round(filters.max_travel_minutes * 100) / 100);
    timeInput.value = formatLimitNumber(mins, 2);
    distanceInput.value = '';
    adaptSliderForValue('time', mins, { contractToValue: true });
    setLimitType('time');
  } else {
    state.isTravelSet = false;
    if (timeInput) timeInput.value = '';
    if (distanceInput) distanceInput.value = '';
    adaptSliderForValue('time', NaN);
    adaptSliderForValue('distance', NaN);
    setLimitType('time');
  }

  if (filters.budget_per_person != null) {
    state.isBudgetSet = true;
    const bud = Math.min(100, Math.max(5, Math.round(filters.budget_per_person / 5) * 5));
    budgetSlider.value = bud;
    budgetDisplay.textContent = `SGD $${bud}`;
  } else {
    state.isBudgetSet = false;
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
  chatCallbacks.renderSummary();
}

export function applyUserToSearchForm(user) {
  if (!user) return;
  applyFiltersToSearchForm({
    locations: Array.isArray(user.location) && user.location.length ? user.location : [''],
    mode: state.currentMode || 'walk',
    max_travel_minutes: user.max_travel_time_minutes || null,
    max_distance_km: user.max_travel_time_minutes ? null : (user.max_distance_km || null),
    budget_per_person: user.budget_per_person || null,
    dietary_requirements: user.dietary_requirements || [],
    liked_cuisines: user.liked_cuisines || [],
    disliked_cuisines: user.disliked_cuisines || [],
    other_preferences: user.other_preferences || [],
  });
  chatCallbacks.refreshGreetingIfIdle();
}

export function initFiltersControls() {
  const budgetSlider = document.getElementById('budgetSlider');
  const budgetDisplay = document.getElementById('budgetDisplay');
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
    const slider = document.getElementById(cfg.sliderId);
    const input = document.getElementById(cfg.inputId);
    const wrap = document.getElementById(cfg.wrapId);

    wrap?.addEventListener('click', (e) => {
      if (e.target !== input && input) {
        input.focus();
        input.select();
      }
    });

    slider?.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      state.isTravelSet = true;
      if (input && Number.isFinite(val)) {
        input.value = formatLimitNumber(val, 2);
      }
      updateSliderDisplayStyles();
      chatCallbacks.renderSummary();
    });

    slider?.addEventListener('change', (e) => {
      const val = parseFloat(e.target.value);
      if (Number.isFinite(val) && val > 0) {
        adaptSliderForValue(type, val, { contractToValue: true });
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
        const limits = getModeLimits();
        const deltaBase = type === 'time' ? (e.shiftKey ? 5 : 1) : (e.shiftKey ? 1 : 0.1);
        const signedDelta = e.key === 'ArrowUp' ? deltaBase : -deltaBase;
        const current = parseFloat(input.value);
        const seed = Number.isFinite(current) ? current : (parseFloat(slider?.value || '') || limits[cfg.defaultKey]);
        const nextVal = Math.max(limits[cfg.minKey], Math.round((seed + signedDelta) * 100) / 100);
        input.value = formatLimitNumber(nextVal, 2);
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });

    input?.addEventListener('input', (e) => {
      const cleaned = sanitizeDecimalText(e.target.value);
      if (cleaned !== e.target.value) {
        e.target.value = cleaned;
      }
      const raw = e.target.value.trim();
      if (raw === '') {
        state.isTravelSet = false;
        adaptSliderForValue(type, NaN);
      } else {
        const val = parseFloat(raw);
        if (Number.isFinite(val) && val > 0) {
          state.isTravelSet = true;
          adaptSliderForValue(type, val, { contractToValue: true });
        }
      }
      updateSliderDisplayStyles();
      chatCallbacks.renderSummary();
    });

    input?.addEventListener('change', (e) => {
      const raw = e.target.value.trim();
      const limits = getModeLimits();
      if (raw === '') {
        state.isTravelSet = false;
        adaptSliderForValue(type, NaN);
        updateSliderDisplayStyles();
        chatCallbacks.renderSummary();
        return;
      }
      let val = parseFloat(raw);
      if (!Number.isFinite(val) || val < limits[cfg.minKey]) {
        val = limits[cfg.minKey];
        const minLabel = cfg.unit === 'km' ? 'distance' : 'travel time';
        showToast(`Minimum ${minLabel} is ${val} ${val === 1 && cfg.unit === 'mins' ? 'min' : cfg.unit}.`, 'warning');
      }
      val = Math.round(val * 100) / 100;
      e.target.value = formatLimitNumber(val, 2);
      state.isTravelSet = true;
      adaptSliderForValue(type, val, { contractToValue: true });
      updateSliderDisplayStyles();
      chatCallbacks.renderSummary();
    });
  });

  budgetSlider?.addEventListener('input', (e) => {
    state.isBudgetSet = true;
    budgetDisplay.textContent = `SGD $${e.target.value}`;
    updateSliderDisplayStyles();
    chatCallbacks.renderSummary();
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

    const limits = getModeLimits();
    const timeRaw = document.getElementById('timeInput')?.value.trim() || '';
    const distRaw = document.getElementById('distanceInput')?.value.trim() || '';
    if (state.currentLimitType === 'time' && timeRaw !== '') {
      const minsVal = parseFloat(timeRaw);
      if (!Number.isFinite(minsVal) || minsVal < limits.minTime || minsVal > limits.maxTime) {
        showToast(`Search travel time for ${state.currentMode} must be ${limits.minTime}–${limits.maxTime} mins — use the slider to scale down or switch mode.`, 'warning');
        return;
      }
    }
    if (state.currentLimitType === 'distance' && distRaw !== '') {
      const kmVal = parseFloat(distRaw);
      if (!Number.isFinite(kmVal) || kmVal < limits.minDist || kmVal > limits.maxDist) {
        showToast(`Search distance for ${state.currentMode} must be ${limits.minDist}–${limits.maxDist} km — use the slider to scale down or switch mode.`, 'warning');
        return;
      }
    }

    const payload = collectCurrentFormPayload(false);
    if (!payload.location) {
      showToast('Please enter a starting location before searching.', 'warning');
      return;
    }

    const allLocations = payload.locations || [];
    state.activeSearchMode = payload.mode;
    state.activeBudgetLimit = payload.budget_per_person ?? null;
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

    if (emptyState) emptyState.remove();
    document.getElementById('mapSection')?.classList.add('hidden');
    resultsHeader?.classList.add('hidden');

    statusBanner.className = 'p-4 rounded-2xl border text-sm flex items-center gap-3 bg-amber-50 dark:bg-amber-950/50 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200';
    statusIcon.innerHTML = '<svg class="animate-spin w-4 h-4 text-amber-600 dark:text-amber-400" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';
    statusText.textContent = `Searching near ${allLocations.join(' & ')} (${activeModelLabel})...`;
    statusBanner.classList.remove('hidden');

    let stepTick = 0;
    renderResultsSkeleton(stepTick, activeModelLabel);
    const stageTimer = setInterval(() => {
      if (stepTick < 3) {
        stepTick += 1;
        renderResultsSkeleton(stepTick, activeModelLabel);
      }
    }, 2400);

    const modelPollTimer = setInterval(async () => {
      try {
        const pData = await apiJson('/api/active-model');
        if (pData.active_model && pData.active_model !== activeModelLabel) {
          activeModelLabel = pData.active_model;
          statusText.textContent = `Searching near ${allLocations.join(' & ')} (${activeModelLabel})...`;
        }
      } catch { }
    }, 800);

    try {
      const data = await apiJson('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      clearInterval(stageTimer);
      clearInterval(modelPollTimer);

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
      clearInterval(stageTimer);
      clearInterval(modelPollTimer);
      statusBanner.className = 'p-4 rounded-2xl border text-sm flex items-center gap-3 bg-rose-50 dark:bg-rose-950/50 border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200';
      statusIcon.innerHTML = '<i data-lucide="alert-circle" class="w-4 h-4 text-rose-600 dark:text-rose-400"></i>';
      statusText.textContent = error.message;
      refreshIcons(statusBanner);
      document.getElementById('resultsList').innerHTML = '';
      chatCallbacks.postSearchOutcome({ errorMessage: error.message, fromChat });
    } finally {
      clearInterval(stageTimer);
      clearInterval(modelPollTimer);
      searchBtn.disabled = false;
      searchBtn.innerHTML = '<i data-lucide="search" class="w-4 h-4"></i> Find Matching Restaurants';
      refreshIcons(searchBtn);
    }
  });
}
