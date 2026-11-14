import {
  escapeHtml,
  formatCuisineLabel,
  getPlaceKey,
  getSingaporeDate,
  refreshIcons,
  state,
} from './state.js?v=20261114-12';
import {
  drawOriginToRestaurantLine,
  flyToMarkerForItem,
  focusRestaurantOnMap,
  highlightMapPin,
  openRouteDrawer,
  setMapFormatters,
  updateInteractiveMap,
} from './map.js?v=20261114-12';
import { renderCompareTray, setCompareHelpers, toggleCompareItem } from './compare.js?v=20261114-12';

let favoriteToggleHandler = async () => { };

export function setFavoriteToggleHandler(fn) {
  if (typeof fn === 'function') favoriteToggleHandler = fn;
}

export function to12Hour(timeStr) {
  if (!timeStr) return '';
  const clean = String(timeStr).replace(':', '').trim();
  if (clean.length !== 4 || Number.isNaN(parseInt(clean, 10))) return String(timeStr);
  const h = parseInt(clean.slice(0, 2), 10);
  const m = clean.slice(2, 4);
  if (h === 24 || (h === 23 && m === '59')) return '12:00 AM';
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m} ${ampm}`;
}

function getNormalizedDayPairs(openingHours, dayName) {
  if (!openingHours || typeof openingHours !== 'object') return [];
  const raw = openingHours[dayName];
  if (!raw || !Array.isArray(raw) || raw.length === 0) return [];
  const toHHMM = (s) => {
    if (!s || typeof s !== 'string') return '';
    const c = s.replace(':', '').trim();
    if (c === '2359') return '24:00';
    return c.length === 4 ? `${c.slice(0, 2)}:${c.slice(2)}` : s;
  };
  if (Array.isArray(raw[0])) {
    return raw.map((pair) => [toHHMM(pair[0]), toHHMM(pair[1])]);
  }
  if (raw.length === 2 && typeof raw[0] === 'string') {
    return [[toHHMM(raw[0]), toHHMM(raw[1])]];
  }
  return [];
}

export function formatHours(r) {
  if (!r) return 'Hours unavailable';
  const days = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
  const nowSG = getSingaporeDate();
  const todayIdx = nowSG.getDay();
  const yesterdayName = days[(todayIdx + 6) % 7];
  const todayName = days[todayIdx];
  const tomorrowName = days[(todayIdx + 1) % 7];

  if (r.today_hours) {
    const raw = r.today_hours.trim();
    if (raw.toLowerCase() === 'open 24 hours') return 'Open 24 Hours';
    if (raw.toLowerCase() === 'closed today') return 'Closed today';
    if (raw.toLowerCase() === 'hours unavailable') {
      return r.open_now ? 'Open Now (Hours unlisted)' : 'Hours unavailable';
    }

    let pairs = raw.split(',').map((part) => {
      const pieces = part.trim().split(/\s*[–-]\s*/);
      return pieces.length === 2 ? [pieces[0].trim(), pieces[1].trim()] : null;
    }).filter(Boolean);

    if (pairs.length > 0) {
      const morningIdx = pairs.findIndex((p) => p[0] === '00:00');
      const eveningIdx = pairs.findIndex((p) => p[1] === '24:00' || p[1] === '23:59');

      if (morningIdx !== -1 && eveningIdx !== -1 && morningIdx !== eveningIdx) {
        const overnightStart = pairs[eveningIdx][0];
        const overnightEnd = pairs[morningIdx][1];
        const merged = [];
        pairs.forEach((p, idx) => {
          if (idx === morningIdx) return;
          if (idx === eveningIdx) merged.push([overnightStart, overnightEnd]);
          else merged.push(p);
        });
        pairs = merged;
      } else if (eveningIdx !== -1 && morningIdx === -1) {
        const tomorrowPairs = getNormalizedDayPairs(r.opening_hours, tomorrowName);
        const tomMorning = tomorrowPairs.find((p) => p[0] === '00:00');
        if (tomMorning) pairs[eveningIdx] = [pairs[eveningIdx][0], tomMorning[1]];
      } else if (morningIdx !== -1 && eveningIdx === -1 && pairs.length === 1) {
        const yesterdayPairs = getNormalizedDayPairs(r.opening_hours, yesterdayName);
        const yestEvening = yesterdayPairs.find((p) => p[1] === '24:00' || p[1] === '23:59');
        if (yestEvening) pairs[0] = [yestEvening[0], pairs[0][1]];
      }
      return pairs.map((p) => `${to12Hour(p[0])} – ${to12Hour(p[1])}`).join(', ');
    }
  }

  const todayPairs = getNormalizedDayPairs(r.opening_hours, todayName);
  if (todayPairs.length === 0) {
    return r.open_now ? 'Open Now (Hours unlisted)' : 'Closed today';
  }
  if (todayPairs.length === 1 && todayPairs[0][0] === '00:00' && todayPairs[0][1] === '24:00') {
    return 'Open 24 Hours';
  }
  return todayPairs.map((p) => `${to12Hour(p[0])} – ${to12Hour(p[1])}`).join(', ');
}

export function getTravelMinutes(r, mode = state.activeSearchMode) {
  if (!r) return null;
  let val = null;
  if (mode === 'drive') {
    val = r.drive_minutes ?? r.transit_minutes ?? r.walk_minutes;
  } else if (mode === 'transit') {
    val = r.transit_minutes ?? r.walk_minutes ?? r.drive_minutes;
  } else {
    val = r.walk_minutes ?? r.transit_minutes ?? r.drive_minutes;
  }
  return typeof val === 'number' && !Number.isNaN(val) ? val : null;
}

export function formatRouteBadge(r, mode = state.activeSearchMode) {
  if (!r) return '';
  const candidates = mode === 'drive'
    ? [['drive_minutes', '🚗', 'drive'], ['transit_minutes', '🚆', 'transit'], ['walk_minutes', '🚶', 'walk']]
    : mode === 'transit'
      ? [['transit_minutes', '🚆', 'transit'], ['drive_minutes', '🚗', 'drive'], ['walk_minutes', '🚶', 'walk']]
      : [['walk_minutes', '🚶', 'walk'], ['drive_minutes', '🚗', 'drive'], ['transit_minutes', '🚆', 'transit']];

  for (const [key, icon, label] of candidates) {
    if (typeof r[key] === 'number' && !Number.isNaN(r[key])) {
      return `${icon} ${Math.round(r[key])} mins ${label}`;
    }
  }
  return '';
}

export function getRatingValue(r) {
  const raw = r.rating ?? r.g_rating;
  const num = parseFloat(raw);
  return !Number.isNaN(num) && num > 0 ? num : null;
}

export function getReviewsValue(r) {
  const raw = r.rating_count ?? r.g_no_reviews;
  const num = parseInt(raw, 10);
  return !Number.isNaN(num) && num >= 0 ? num : 0;
}

const TIER_PRICE_ESTIMATES = {
  inexpensive: 10,
  moderate: 28,
  expensive: 65,
  very_expensive: 140,
};

const TIER_PRICE_BADGES = {
  inexpensive: '$ · Budget',
  moderate: '$$ · Casual Dining',
  expensive: '$$$ · Upscale',
  very_expensive: '$$$$ · Fine Dining',
};

function normalizePriceBand(r) {
  if (!r) return '';
  return String(r.price_level || r.price_band || '')
    .replace(/^PRICE_LEVEL_/i, '')
    .trim()
    .toLowerCase();
}

export function getPriceValue(r) {
  if (!r) return null;
  if (typeof r.avg_price === 'number' && !Number.isNaN(r.avg_price)) return r.avg_price;
  const s = typeof r.price_start === 'number' ? r.price_start : null;
  const e = typeof r.price_end === 'number' ? r.price_end : null;
  if (s !== null && e !== null) return (s + e) / 2;
  if (s !== null) return s;
  if (e !== null) return e;
  if (typeof r.estimated_price === 'number' && !Number.isNaN(r.estimated_price)) return r.estimated_price;
  const band = normalizePriceBand(r);
  return Object.prototype.hasOwnProperty.call(TIER_PRICE_ESTIMATES, band) ? TIER_PRICE_ESTIMATES[band] : null;
}

export function formatPriceBadge(r) {
  if (!r) return '';
  if (r.price_range) return `💰 ${r.price_range}`;
  if (typeof r.avg_price === 'number' && !Number.isNaN(r.avg_price)) {
    return `💰 ~SGD ${Math.round(r.avg_price)}`;
  }
  const band = normalizePriceBand(r);
  if (Object.prototype.hasOwnProperty.call(TIER_PRICE_BADGES, band)) {
    return `💰 ${TIER_PRICE_BADGES[band]}`;
  }
  if (typeof r.estimated_price === 'number' && !Number.isNaN(r.estimated_price)) {
    return `💰 ~SGD ${Math.round(r.estimated_price)}`;
  }
  return '';
}

function compareItems(a, b, sortBy, matchesFirst) {
  if (matchesFirst && a.isMatch !== b.isMatch) {
    return a.isMatch ? -1 : 1;
  }
  if (sortBy === 'ai') return a.originalIndex - b.originalIndex;

  const rA = a.restaurant || {};
  const rB = b.restaurant || {};

  if (sortBy === 'travel_asc') {
    const tA = getTravelMinutes(rA);
    const tB = getTravelMinutes(rB);
    if (tA === null && tB === null) return a.originalIndex - b.originalIndex;
    if (tA === null) return 1;
    if (tB === null) return -1;
    if (tA !== tB) return tA - tB;
    return (getRatingValue(rB) || 0) - (getRatingValue(rA) || 0);
  }

  if (sortBy === 'rating_desc') {
    const ratA = getRatingValue(rA);
    const ratB = getRatingValue(rB);
    if (ratA === null && ratB === null) return a.originalIndex - b.originalIndex;
    if (ratA === null) return 1;
    if (ratB === null) return -1;
    if (ratB !== ratA) return ratB - ratA;
    return getReviewsValue(rB) - getReviewsValue(rA);
  }

  if (sortBy === 'reviews_desc') {
    const revA = getReviewsValue(rA);
    const revB = getReviewsValue(rB);
    if (revB !== revA) return revB - revA;
    return (getRatingValue(rB) || 0) - (getRatingValue(rA) || 0);
  }

  if (sortBy === 'price_asc' || sortBy === 'price_desc') {
    const pA = getPriceValue(rA);
    const pB = getPriceValue(rB);
    if (pA === null && pB === null) return a.originalIndex - b.originalIndex;
    if (pA === null) return 1;
    if (pB === null) return -1;
    if (pA !== pB) return sortBy === 'price_asc' ? pA - pB : pB - pA;
    return (getRatingValue(rB) || 0) - (getRatingValue(rA) || 0);
  }

  if (sortBy === 'name_asc') {
    return String(rA.name || '').toLowerCase().localeCompare(String(rB.name || '').toLowerCase());
  }

  return a.originalIndex - b.originalIndex;
}

export function computeDistanceKm(lat1, lng1, lat2, lng2) {
  if (typeof lat1 !== 'number' || typeof lng1 !== 'number' || typeof lat2 !== 'number' || typeof lng2 !== 'number') {
    return null;
  }
  const R = 6371;
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * (Math.sin(dLng / 2) ** 2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function passesQuickFilters(item) {
  const r = item.restaurant || {};
  const qf = state.quickFilters;
  if (qf.openNow && !r.open_now) return false;
  if (qf.muisHalal) {
    const isOfficial = r.halal_certification === 'official' || (r.muis_check && r.muis_check.status === 'verified');
    if (!isOfficial) return false;
  }
  if (qf.vegetarian && !r.serves_vegetarian_food) return false;
  if (qf.withinBudget && state.activeBudgetLimit != null && !state.activeBudgetIsPlus) {
    const price = getPriceValue(r);
    if (price !== null && price > state.activeBudgetLimit) return false;
  }
  return true;
}

function updateQuickFilterChipsUI() {
  document.querySelectorAll('.qf-chip').forEach((btn) => {
    const key = btn.dataset.qf;
    const active = Boolean(state.quickFilters[key]);
    btn.className = active
      ? 'qf-chip px-2.5 py-1 rounded-full text-[11px] font-bold bg-brand-600 text-white border border-brand-600 shadow-sm transition flex items-center gap-1'
      : 'qf-chip px-2.5 py-1 rounded-full text-[11px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:border-brand-300 border border-slate-200 dark:border-slate-700 transition flex items-center gap-1';
  });
}

export function resetResultsDisplay() {
  state.lastOrigin = null;
  state.lastInputOrigins = [];
  state.lastMatches = [];
  state.lastAlternatives = [];
  state.displayedItems = [];
  state.activeBudgetLimit = null;
  state.activeBudgetIsPlus = false;
  state.compareKeys.clear();
  Object.keys(state.quickFilters).forEach((key) => {
    state.quickFilters[key] = false;
  });
  updateQuickFilterChipsUI();
  renderCompareTray();

  document.getElementById('statusBanner')?.classList.add('hidden');
  document.getElementById('resultsHeader')?.classList.add('hidden');
  document.getElementById('mapSection')?.classList.add('hidden');
  const resultsList = document.getElementById('resultsList');
  if (resultsList) resultsList.innerHTML = '';
  document.getElementById('emptyState')?.classList.remove('hidden');
}

export function updateResultsSkeletonModel(modelLabel = 'Gemini AI') {
  const stepEl = document.getElementById('pipelineModelStepLabel');
  if (stepEl) {
    stepEl.textContent = `Scoring & ranking with ${modelLabel}`;
  }
}

export function renderResultsSkeleton(modelLabel = 'Gemini AI') {
  const container = document.getElementById('resultsList');
  if (!container) return;
  const steps = [
    { label: 'Resolving starting location(s)' },
    { label: 'Querying Google Places & route ETAs' },
    { label: 'Verifying official MUIS Halal records' },
    { label: `Scoring & ranking with ${modelLabel}`, id: 'pipelineModelStepLabel' },
  ];

  const stepsHtml = steps.map((step) => `
    <div class="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 font-medium">
      <span class="w-2 h-2 rounded-full bg-brand-500/75 animate-pulse shrink-0"></span>
      <span${step.id ? ` id="${step.id}"` : ''}>${escapeHtml(step.label)}</span>
    </div>
  `).join('');

  const spinnerIcon = '<svg class="animate-spin w-3.5 h-3.5 text-brand-600 dark:text-brand-400 shrink-0" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';

  const skeletonCard = `
    <div class="bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 space-y-3 animate-pulse">
      <div class="flex justify-between items-start gap-4">
        <div class="space-y-2 flex-1">
          <div class="h-4 bg-slate-200 dark:bg-slate-800 rounded w-1/2"></div>
          <div class="h-3 bg-slate-100 dark:bg-slate-800/70 rounded w-2/3"></div>
        </div>
        <div class="h-7 w-14 bg-slate-200 dark:bg-slate-800 rounded-lg"></div>
      </div>
      <div class="h-8 bg-slate-100 dark:bg-slate-800/70 rounded-xl w-full"></div>
      <div class="flex gap-2">
        <div class="h-6 w-24 bg-slate-100 dark:bg-slate-800 rounded-lg"></div>
        <div class="h-6 w-20 bg-slate-100 dark:bg-slate-800 rounded-lg"></div>
      </div>
    </div>
  `;

  container.innerHTML = `
    <div id="pipelineProgressCard" class="bg-white dark:bg-slate-900 p-5 rounded-2xl border border-brand-200 dark:border-brand-800/70 shadow-sm space-y-3">
      <div class="flex items-center justify-between gap-2">
        <span class="text-xs font-extrabold uppercase tracking-wider text-brand-600 dark:text-brand-400 flex items-center gap-2">
          ${spinnerIcon}
          <span>Searching BiteFinder Pipeline</span>
        </span>
        <span class="text-[11px] font-semibold text-slate-400">Request in progress</span>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">${stepsHtml}</div>
    </div>
    ${skeletonCard}
    ${skeletonCard}
  `;
  refreshIcons(container);
}

export function renderResults(matches, alternatives) {
  const container = document.getElementById('resultsList');
  if (!container) return;
  container.innerHTML = '';
  updateQuickFilterChipsUI();

  const sortSelect = document.getElementById('sortSelect');
  const matchesFirstCheck = document.getElementById('matchesFirstCheck');
  const sortBy = sortSelect ? sortSelect.value : 'ai';
  const matchesFirst = matchesFirstCheck ? matchesFirstCheck.checked : true;

  const combined = [
    ...matches.map((m, idx) => ({ ...m, isMatch: true, originalIndex: idx })),
    ...alternatives.map((a, idx) => ({ ...a, isMatch: false, originalIndex: matches.length + idx })),
  ];

  const filtered = combined.filter(passesQuickFilters);
  filtered.sort((a, b) => compareItems(a, b, sortBy, matchesFirst));
  state.displayedItems = filtered;

  const countEl = document.getElementById('resultsCount');
  if (countEl && combined.length > 0) {
    countEl.textContent = filtered.length === combined.length
      ? `${combined.length} Restaurant Recommendation${combined.length === 1 ? '' : 's'}`
      : `Showing ${filtered.length} of ${combined.length} Recommendations`;
  }

  if (filtered.length === 0) {
    const mapSection = document.getElementById('mapSection');
    if (mapSection) mapSection.classList.add('hidden');
    const isClientFiltered = combined.length > 0;
    container.innerHTML = `
      <div class="bg-white dark:bg-slate-900 p-8 rounded-2xl border border-slate-200 dark:border-slate-800 text-center space-y-3">
        <p class="text-sm font-semibold text-slate-700 dark:text-slate-200">
          ${isClientFiltered ? 'No restaurants match the active quick filter chips.' : 'No restaurants matched all constraints.'}
        </p>
        <p class="text-xs text-slate-400">
          ${isClientFiltered ? 'Toggle off a quick filter chip above or reset all quick filters to see your recommendations.' : 'Try expanding your travel time limit or budget.'}
        </p>
        ${isClientFiltered ? `
          <div class="pt-1">
            <button type="button" id="clearQuickFiltersBtn"
              class="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-white bg-brand-600 hover:bg-brand-700 shadow-sm transition">
              <i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i>
              <span>Clear Quick Filters</span>
            </button>
          </div>
        ` : ''}
      </div>
    `;
    document.getElementById('clearQuickFiltersBtn')?.addEventListener('click', () => {
      Object.keys(state.quickFilters).forEach((key) => {
        state.quickFilters[key] = false;
      });
      renderResults(state.lastMatches, state.lastAlternatives);
    });
    refreshIcons(container);
    return;
  }

  updateInteractiveMap(filtered);
  renderCompareTray();

  filtered.forEach((item, displayIdx) => {
    const r = item.restaurant || {};
    const reasons = item.reasons || [];
    const isOfficialHalal = r.halal_certification === 'official' || (r.muis_check && r.muis_check.status === 'verified');
    const isGoogleHalal = r.halal_hint || (r.dietary_requirements && r.dietary_requirements.includes('halal'));
    const hoursText = formatHours(r);
    const rankNumber = displayIdx + 1;
    const placeKey = getPlaceKey(r);
    const isFav = state.favoriteKeys.has(placeKey);
    const isCompared = state.compareKeys.has(placeKey);

    const card = document.createElement('div');
    card.id = `resCard-${displayIdx}`;
    card.className = 'bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md hover:border-brand-300 dark:hover:border-brand-700 transition flex flex-col gap-3';

    card.addEventListener('mouseenter', () => highlightMapPin(displayIdx, true));
    card.addEventListener('mouseleave', () => highlightMapPin(displayIdx, false));

    let multiPersonDistancesHtml = '';
    if (state.lastInputOrigins && state.lastInputOrigins.length > 1 && typeof r.lat === 'number' && typeof r.lng === 'number') {
      const pills = state.lastInputOrigins.map((orig, pIdx) => {
        const distKm = computeDistanceKm(orig.latitude, orig.longitude, r.lat, r.lng);
        if (distKm === null) return '';
        const shortName = orig.query || `Location ${pIdx + 1}`;
        return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-indigo-50 dark:bg-indigo-950/70 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800 text-[11px] font-semibold">
          <span>👤 ${escapeHtml(shortName)}:</span>
          <span class="font-extrabold">${distKm.toFixed(1)} km</span>
        </span>`;
      }).filter(Boolean).join('');
      if (pills) {
        multiPersonDistancesHtml = `
          <div class="flex flex-wrap items-center gap-1.5 pt-0.5">
            <span class="text-[10px] font-bold uppercase tracking-wider text-indigo-500 dark:text-indigo-400 mr-0.5">🎯 Distance per person:</span>
            ${pills}
          </div>
        `;
      }
    }

    const routeStr = formatRouteBadge(r, state.activeSearchMode);
    const priceBadgeStr = formatPriceBadge(r);
    const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${r.name || ''} ${r.address || 'Singapore'}`)}`;

    const reasonsHtml = reasons.map((rawReason) => {
      const trimmed = String(rawReason || '').trim();
      const isUnmet = trimmed.startsWith('!');
      const cleanText = isUnmet ? trimmed.replace(/^!\s*/, '') : trimmed;
      if (isUnmet) {
        return `
          <li class="flex items-start gap-2 px-2.5 py-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-800/70 text-rose-700 dark:text-rose-300 font-medium">
            <i data-lucide="x-circle" class="w-3.5 h-3.5 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5"></i>
            <span>${escapeHtml(cleanText)}</span>
          </li>
        `;
      }
      return `
        <li class="flex items-start gap-2 px-2.5 py-1.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800/70 text-emerald-700 dark:text-emerald-300 font-medium">
          <i data-lucide="check-circle-2" class="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5"></i>
          <span>${escapeHtml(cleanText)}</span>
        </li>
      `;
    }).join('');

    card.innerHTML = `
      <div class="flex items-start justify-between gap-4">
        <div>
          <div class="flex flex-wrap items-center gap-2">
            <span class="w-6 h-6 rounded-full text-xs font-extrabold flex items-center justify-center text-white shrink-0 ${item.isMatch ? 'bg-emerald-600' : 'bg-amber-600'}">${rankNumber}</span>
            <h3 class="text-base font-bold text-slate-900 dark:text-white">${escapeHtml(r.name || 'Restaurant')}</h3>
            ${item.isMatch
        ? '<span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">Match</span>'
        : '<span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800">Alternative</span>'}
            ${item.matched_cuisine
        ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-brand-50 dark:bg-brand-950/80 text-brand-700 dark:text-brand-300 border border-brand-200 dark:border-brand-800 capitalize">🍽️ ${escapeHtml(formatCuisineLabel(item.matched_cuisine))}</span>`
        : ''}
          </div>
          <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 flex items-center gap-1">
            <i data-lucide="map-pin" class="w-3.5 h-3.5 text-slate-400"></i>
            ${escapeHtml(r.address || 'Singapore')}
          </p>
        </div>

        <div class="flex flex-col items-end shrink-0">
          <div class="flex items-center gap-1 bg-amber-50 dark:bg-amber-950/70 px-2 py-1 rounded-lg border border-amber-200 dark:border-amber-800">
            <i data-lucide="star" class="w-3.5 h-3.5 text-amber-500 fill-amber-500"></i>
            <span class="text-xs font-bold text-amber-800 dark:text-amber-300">${escapeHtml(r.rating || r.g_rating || 'N/A')}</span>
          </div>
          ${r.rating_count ? `<span class="text-[10px] text-slate-400 mt-0.5">${escapeHtml(r.rating_count)} reviews</span>` : ''}
        </div>
      </div>

      <div class="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-200 bg-slate-50 dark:bg-slate-800/70 px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700">
        <i data-lucide="clock" class="w-3.5 h-3.5 text-slate-400 shrink-0"></i>
        <span class="font-bold text-slate-800 dark:text-slate-100">Hours Today:</span>
        <span class="text-slate-600 dark:text-slate-300 font-medium">${escapeHtml(hoursText)}</span>
        ${r.open_now
        ? '<span class="ml-auto text-[10px] font-bold text-emerald-700 dark:text-emerald-300 bg-emerald-100 dark:bg-emerald-950 px-2.5 py-0.5 rounded-full border border-emerald-300 dark:border-emerald-800 shrink-0">Open Now</span>'
        : '<span class="ml-auto text-[10px] font-bold text-rose-700 dark:text-rose-300 bg-rose-100 dark:bg-rose-950 px-2.5 py-0.5 rounded-full border border-rose-300 dark:border-rose-800 shrink-0">Closed</span>'}
      </div>

      <div class="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-100 dark:border-slate-800">
        ${isOfficialHalal
        ? `<span class="text-xs font-semibold px-2.5 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 flex items-center gap-1">
               <i data-lucide="shield-check" class="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400"></i> Official MUIS Halal
             </span>`
        : isGoogleHalal
          ? `<span class="text-xs font-semibold px-2.5 py-1 rounded-lg bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800 flex items-center gap-1">
                 <i data-lucide="info" class="w-3.5 h-3.5 text-amber-600 dark:text-amber-400"></i> Halal (Google Indicated)
               </span>`
          : ''}
        ${r.serves_vegetarian_food
        ? `<span class="text-xs font-semibold px-2.5 py-1 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800 flex items-center gap-1">
               <i data-lucide="leaf" class="w-3.5 h-3.5 text-blue-600 dark:text-blue-400"></i> Vegetarian
             </span>`
        : ''}
        ${routeStr ? `<span class="text-xs font-medium px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${escapeHtml(routeStr)}</span>` : ''}
        ${priceBadgeStr ? `<span class="text-xs font-medium px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${escapeHtml(priceBadgeStr)}</span>` : ''}
      </div>

      ${multiPersonDistancesHtml}

      ${reasons && reasons.length ? `
        <div class="bg-slate-50 dark:bg-slate-800/50 p-3 rounded-xl border border-slate-100 dark:border-slate-800 text-xs">
          <span class="font-bold text-slate-700 dark:text-slate-200 block mb-2">Why this matches:</span>
          <ul class="space-y-1.5">${reasonsHtml}</ul>
        </div>
      ` : ''}

      <div class="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
        <div class="flex flex-wrap items-center gap-1.5">
          <button type="button" data-action="locate"
            class="px-2.5 py-1.5 rounded-xl text-xs font-bold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-brand-50 dark:hover:bg-slate-700 hover:text-brand-600 dark:hover:text-brand-400 border border-slate-200 dark:border-slate-700 transition flex items-center gap-1.5">
            <i data-lucide="map-pin" class="w-3.5 h-3.5 text-brand-600 dark:text-brand-400"></i>
            Locate
          </button>
          <button type="button" data-action="route"
            class="px-2.5 py-1.5 rounded-xl text-xs font-bold bg-brand-50 dark:bg-brand-500/15 text-brand-700 dark:text-brand-300 hover:bg-brand-100 dark:hover:bg-brand-500/25 border border-brand-200 dark:border-brand-500/30 transition flex items-center gap-1.5">
            <i data-lucide="navigation" class="w-3.5 h-3.5"></i>
            Route
          </button>
          <button type="button" id="favBtn-${displayIdx}" data-action="fav"
            class="px-2.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 border ${isFav
        ? 'bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-300 border-rose-200 dark:border-rose-800'
        : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-rose-50 dark:hover:bg-slate-700 hover:text-rose-600 border-slate-200 dark:border-slate-700'}">
            <i data-lucide="heart" class="w-3.5 h-3.5 ${isFav ? 'text-rose-500 fill-rose-500' : 'text-rose-500'}"></i>
            <span>${isFav ? 'Saved' : 'Save'}</span>
          </button>
          <button type="button" data-action="compare"
            class="px-2.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 border ${isCompared
        ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
        : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-indigo-50 dark:hover:bg-slate-700 hover:text-indigo-600 border-slate-200 dark:border-slate-700'}">
            <i data-lucide="columns-2" class="w-3.5 h-3.5"></i>
            <span>${isCompared ? 'Comparing' : 'Compare'}</span>
          </button>
        </div>
        <a href="${mapsUrl}" target="_blank" rel="noopener noreferrer"
          class="text-xs font-semibold text-brand-600 dark:text-brand-400 hover:text-brand-700 dark:hover:text-brand-300 flex items-center gap-1 hover:underline">
          Google Maps <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
        </a>
      </div>
    `;

    card.querySelector('[data-action="locate"]')?.addEventListener('click', () => focusRestaurantOnMap(displayIdx));
    card.querySelector('[data-action="route"]')?.addEventListener('click', () => openRouteDrawer(displayIdx));
    card.querySelector('[data-action="fav"]')?.addEventListener('click', () => favoriteToggleHandler(displayIdx));
    card.querySelector('[data-action="compare"]')?.addEventListener('click', () => toggleCompareItem(displayIdx));

    container.appendChild(card);
  });

  refreshIcons(container);
}

export function initResultsControls() {
  setMapFormatters({ formatHours, getTravelMinutes });
  setCompareHelpers({
    onCompareChange: () => {
      if (state.lastMatches.length || state.lastAlternatives.length) {
        renderResults(state.lastMatches, state.lastAlternatives);
      }
    },
    formatHours,
    getTravelMinutes,
    getRatingValue,
    getReviewsValue,
    getPriceValue,
  });

  document.getElementById('sortSelect')?.addEventListener('change', () => {
    renderResults(state.lastMatches, state.lastAlternatives);
  });

  document.getElementById('matchesFirstCheck')?.addEventListener('change', () => {
    renderResults(state.lastMatches, state.lastAlternatives);
  });

  document.querySelectorAll('.qf-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const key = chip.dataset.qf;
      if (!key || !(key in state.quickFilters)) return;
      state.quickFilters[key] = !state.quickFilters[key];
      renderResults(state.lastMatches, state.lastAlternatives);
    });
  });

  document.getElementById('surpriseMeBtn')?.addEventListener('click', () => {
    if (!state.displayedItems || state.displayedItems.length === 0) return;
    const pool = state.displayedItems.map((item, idx) => ({ item, idx })).filter((e) => e.item.isMatch);
    const candidates = pool.length > 0 ? pool : state.displayedItems.map((item, idx) => ({ item, idx }));
    const chosen = candidates[Math.floor(Math.random() * candidates.length)];
    if (!chosen) return;

    document.querySelectorAll('.surprise-winner-card').forEach((el) => {
      el.classList.remove('surprise-winner-card', 'ring-2', 'ring-brand-500', 'bg-amber-50/40', 'dark:bg-amber-950/20');
      el.querySelector('.surprise-winner-badge')?.remove();
    });

    const winnerCard = document.getElementById(`resCard-${chosen.idx}`);
    if (winnerCard) {
      winnerCard.classList.add('surprise-winner-card', 'ring-2', 'ring-brand-500', 'bg-amber-50/40', 'dark:bg-amber-950/20');
      const banner = document.createElement('div');
      banner.className = 'surprise-winner-badge px-3 py-1.5 rounded-xl bg-gradient-to-r from-brand-600 to-amber-500 text-white text-xs font-extrabold flex items-center justify-between shadow-sm';
      banner.innerHTML = `<span>🎉 BiteFinder Random Pick Winner!</span><span class="text-[11px] opacity-90">Rank #${chosen.idx + 1}</span>`;
      winnerCard.prepend(banner);
      winnerCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    flyToMarkerForItem(chosen.idx, true);
  });
}
