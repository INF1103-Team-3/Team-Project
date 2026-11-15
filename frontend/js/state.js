export const TOKEN_KEY = 'bitefinder_auth_token';
export const RECENT_KEY = 'bitefinder_recent_searches';
export const THEME_KEY = 'bitefinder_theme';

export const state = {
  currentMode: 'walk',
  activeSearchMode: 'walk',
  currentLimitType: 'time',
  isTravelSet: false,
  isBudgetSet: false,
  isBudgetPlus: false,

  preferredCuisines: new Set(),
  dislikedCuisines: new Set(),

  lastOrigin: null,
  lastInputOrigins: [],
  lastMatches: [],
  lastAlternatives: [],
  displayedItems: [],
  lastSearchPayload: null,
  lastSearchBudgetIsPlus: false,
  refreshSeenRestaurants: [],
  refreshSeenKeys: new Set(),
  quickFilters: {
    openNow: false,
    muisHalal: false,
    vegetarian: false,
    withinBudget: false,
  },
  activeBudgetLimit: null,
  activeBudgetIsPlus: false,

  compareKeys: new Map(), // place_key -> { item, displayIdx }

  currentUser: null,
  favoriteKeys: new Set(),
  favoritesList: [],
  searchHistoryEntries: [],

  chatHistory: [],
  chatHasUserTurn: false,
  onboardingActive: false,
  awaitingChatField: null,
  searchTriggeredFromChat: false,
  pendingChatSearchBubble: null,
};

export function escapeHtml(value) {
  const entities = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(value ?? '').replace(/[&<>"']/g, (ch) => entities[ch]);
}

export function formatCuisineLabel(cuisine) {
  return String(cuisine || '')
    .split(' ')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export function getPlaceKey(r) {
  if (!r) return '';
  const pid = String(r.google_place_id || '').trim();
  if (pid) return pid;
  const name = String(r.name || 'restaurant').trim().toLowerCase();
  const addr = String(r.address || 'singapore').trim().toLowerCase();
  return `${name}|${addr}`;
}

export function getAuthToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

export function setAuthToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { }
}

export function authHeaders(extra = {}) {
  const token = getAuthToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

export function isUserProfileIncomplete(user) {
  if (!user) return false;
  const hasBudget = typeof user.budget_per_person === 'number' && user.budget_per_person > 0;
  const hasTravel = Boolean(user.max_travel_time_minutes || user.max_distance_km);
  return !(hasBudget && hasTravel);
}

export function getSingaporeDate() {
  return new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Singapore' }));
}

export function refreshIcons(root = null) {
  if (!window.lucide || typeof window.lucide.createIcons !== 'function') return;
  if (root instanceof Element) {
    const nodes = root.querySelectorAll('[data-lucide]');
    if (nodes.length > 0) {
      window.lucide.createIcons({ nodes });
    }
    return;
  }
  window.lucide.createIcons();
}

export function updateThemeUI() {
  const isDark = document.documentElement.classList.contains('dark');
  const iconEl = document.getElementById('themeIcon');
  const labelEl = document.getElementById('themeLabel');
  if (iconEl) iconEl.setAttribute('data-lucide', isDark ? 'sun' : 'moon');
  if (labelEl) labelEl.textContent = isDark ? 'Light Mode' : 'Dark Mode';
  refreshIcons(document.getElementById('themeToggleBtn'));
}

export const WISH_ACRONYMS = new Set(['bbq', 'byob', 'msg', 'cbd', 'mrt', 'hrs', 'gym', 'nth', 'sgd', 'ac', 'tv', 'vip', 'wfh']);
export const WISH_KEYBOARD_MASH = [
  'asdf', 'sdfg', 'dfgh', 'fghj', 'ghjk', 'hjkl',
  'qwer', 'wert', 'erty', 'tyui', 'uiop',
  'zxcv', 'xcvb', 'cvbn', 'vbnm',
];

const RATING_WISH_SOURCE = (
  '(?:\\b(?:minimum|min\\.?|at least|no less than|above|over)\\b|>=?)\\s*'
  + '(?:google\\s*)?(?:(?:rating|rated)\\s*(?:of\\s*|is\\s*)?(\\d+(?:\\.\\d+)?|\\.\\d+)'
  + '(?:\\s*(?:\\+\\s*)?(?:stars?|\\/\\s*5|\\+))?'
  + '|(\\d+(?:\\.\\d+)?|\\.\\d+)\\s*(?:\\+\\s*)?(?:stars?|\\/\\s*5|rating\\b|rated\\b))'
  + '|\\b(?:google\\s*)?(?:rating|rated)\\s*(?:of\\s*|is\\s*|at\\s*)?'
  + '(?:>=?|at least|minimum|min\\.?|no less than|above|over)?\\s*'
  + '(\\d+(?:\\.\\d+)?|\\.\\d+)(?:\\s*(?:\\+\\s*)?(?:stars?|\\/\\s*5)|\\s*\\+(?!\\w)|(?=[,.;!?\\s]|$))'
  + '|\\b(\\d+(?:\\.\\d+)?|\\.\\d+)\\s*(?:\\+\\s*)?(?:stars?|\\/\\s*5)(?!\\w)'
  + '(?:\\s*(?:or higher|or above|and up|or better|minimum|min\\.?|\\+)(?!\\w))?'
  + '|\\b(\\d+(?:\\.\\d+)?|\\.\\d+)\\s*(?:\\+\\s*)?(?:rating|rated)\\b'
  + '(?:\\s*(?:or higher|or above|and up|or better|minimum|min\\.?|\\+)(?!\\w))?'
);

export function normalizeWishText(raw) {
  return String(raw || '')
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/\b(\d+)\s*\.\s*(\d+)\b/g, '$1.$2');
}

export function extractRatingWishes(text) {
  const normalized = normalizeWishText(text);
  const rx = new RegExp(RATING_WISH_SOURCE, 'gi');
  const values = [];
  let match;
  while ((match = rx.exec(normalized)) !== null) {
    const rawNum = match.slice(1).find((g) => g !== undefined);
    if (rawNum === undefined) continue;
    const rating = parseFloat(rawNum);
    if (!Number.isFinite(rating) || rating < 1 || rating > 5) {
      throw new Error('Google star ratings must be between 1 and 5 stars.');
    }
    values.push(rating);
  }
  return values;
}

export function stripRatingClauses(text) {
  const normalized = normalizeWishText(text);
  const rx = new RegExp(RATING_WISH_SOURCE, 'gi');
  return normalized
    .replace(rx, ' ')
    .replace(/^(?:\s*(?:and|with|&|,|\/)\b\s*)+/gi, '')
    .replace(/(?:\s*\b(?:and|with)\s*|\s*[,&/]\s*)+$/gi, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/^[\s,;/\-]+|[\s,;/\-]+$/g, '')
    .trim();
}

export function getActiveRatingFilterValue(rawText) {
  const tokens = String(rawText || '').split(',').map(normalizeWishText).filter(Boolean);
  const found = [];
  for (const token of tokens) {
    try {
      found.push(...extractRatingWishes(token));
    } catch {
      return null;
    }
  }
  if (!found.length) return '';
  return Math.round(Math.max(...found) * 100) / 100;
}

export function applyRatingFilterToWishesRaw(rawText, ratingValue) {
  const tokens = String(rawText || '').split(',').map(normalizeWishText).filter(Boolean);
  const kept = [];
  for (const token of tokens) {
    const rem = stripRatingClauses(token);
    if (rem) kept.push(rem);
  }
  const num = ratingValue !== '' && ratingValue != null ? Number(ratingValue) : NaN;
  if (Number.isFinite(num) && num >= 1 && num <= 5) {
    const rounded = Math.round(num * 100) / 100;
    const labelNum = Number.isInteger(rounded)
      ? rounded.toFixed(1)
      : String(rounded);
    kept.unshift(`at least ${labelNum} stars`);
  }
  return kept.join(', ');
}

export function validateEnglishWishesInput(items, fieldLabel = 'Special requests') {
  for (const raw of (items || [])) {
    const text = normalizeWishText(raw);
    if (!text) continue;
    if (text.length > 100 || !/^[A-Za-z0-9][A-Za-z0-9 ,.'!?/&()+\-=>]*$/.test(text)) {
      return `${fieldLabel} must use proper English letters and words (e.g. quiet seating, spicy food).`;
    }
    let ratings = [];
    try {
      ratings = extractRatingWishes(text);
    } catch (err) {
      return `${fieldLabel}: ${err.message}`;
    }
    const remainder = stripRatingClauses(text);
    if (ratings.length && !remainder) {
      continue;
    }
    const checkText = remainder || text;
    const words = checkText.match(/[A-Za-z]+/g) || [];
    if (!words.length || !words.some((w) => w.length > 1)) {
      return `${fieldLabel} must contain meaningful English words (e.g. quiet seating, spicy food).`;
    }
    for (const word of words) {
      const low = word.toLowerCase();
      if (/(.)\1\1/.test(low) || WISH_KEYBOARD_MASH.some((seq) => low.includes(seq))) {
        return `${fieldLabel} must contain proper English words, not '${word}'.`;
      }
      if (low.length >= 3 && !WISH_ACRONYMS.has(low) && !/[aeiouy]/.test(low)) {
        return `${fieldLabel} must contain proper English words, not '${word}'.`;
      }
      if (/[bcdfghjklmnpqrstvwxz]{6,}/.test(low)) {
        return `${fieldLabel} must contain proper English words, not '${word}'.`;
      }
    }
  }
  return '';
}

const LOCATION_COORD_PAIR_REGEX = /^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$/;
const LOCATION_NUMERIC_REGEX = /^-?\d+(?:\.\d+)?$/;
const LOCATION_KEYBOARD_MASH = [
  'asdf', 'sdfg', 'dfgh', 'fghj', 'ghjk', 'hjkl', 'jklm',
  'qwer', 'wert', 'qwrt', 'tyui', 'uiop',
  'zxcv', 'xcvb', 'cvbn', 'vbnm',
  'qazw', 'wsxc', 'edcr', 'rfvt',
];
const KNOWN_SG_LOCATION_ABBRS = new Set([
  'amk', 'bb', 'bldg', 'blk', 'bm', 'bp', 'bt', 'cbd', 'cck', 'chij', 'ctrl',
  'gl', 'hdb', 'imm', 'jem', 'jln', 'lrg', 'mbs', 'mrt', 'nex', 'np', 'ntu',
  'nus', 'nyp', 'plq', 'qt', 'rp', 'sim', 'sit', 'smu', 'sp', 'sutd',
  't1', 't2', 't3', 't4', 'tg', 'tp', 'tpy', 'yck', 'iii',
]);

export function parseProfileLocationsInput(raw) {
  const trimmed = String(raw || '').trim();
  if (!trimmed) return [];
  if (LOCATION_COORD_PAIR_REGEX.test(trimmed)) return [trimmed];
  const parts = trimmed.split(',').map((s) => s.trim()).filter(Boolean);
  const parsed = [];
  for (let i = 0; i < parts.length; i += 1) {
    if (
      i + 1 < parts.length
      && LOCATION_NUMERIC_REGEX.test(parts[i])
      && LOCATION_NUMERIC_REGEX.test(parts[i + 1])
    ) {
      parsed.push(`${parts[i]}, ${parts[i + 1]}`);
      i += 1;
    } else {
      parsed.push(parts[i]);
    }
  }
  return parsed;
}

export function validateLocationSyntax(raw, label = 'Location') {
  const clean = String(raw || '').replace(/\s+/g, ' ').trim();
  if (!clean) return `${label} cannot be empty.`;
  if (/[\x00-\x1f]/.test(String(raw || ''))) return `${label} contains invalid characters.`;
  if (clean.length > 160) return `${label} is too long (maximum 160 characters).`;

  const coordMatch = clean.match(LOCATION_COORD_PAIR_REGEX);
  if (coordMatch) {
    const lat = parseFloat(coordMatch[1]);
    const lng = parseFloat(coordMatch[2]);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || lat < 1.15 || lat > 1.48 || lng < 103.6 || lng > 104.1) {
      return 'Enter coordinates within Singapore.';
    }
    return '';
  }

  const normalizedPostal = clean.replace(/[.,;]+$/, '');
  let postalDigits = null;
  const bareDigits = normalizedPostal.match(/^\s*(\d+)\s*$/);
  const prefixedDigits = normalizedPostal.match(/^(?:singapore|sg|s\s*\(?)\s*(\d+)\)?$/i);
  if (bareDigits) postalDigits = bareDigits[1];
  else if (prefixedDigits) postalDigits = prefixedDigits[1];

  if (postalDigits !== null) {
    if (postalDigits.length !== 6) {
      return `${label} postal code must be 6 Singapore digits (e.g. 545078).`;
    }
    const sector = parseInt(postalDigits.slice(0, 2), 10);
    if (sector < 1 || sector > 83) {
      return `${label} '${postalDigits}' is not a valid Singapore postal code (e.g. 545078).`;
    }
    return '';
  }

  if (/^(?:singapore|s'?pore|sg)$/i.test(clean.replace(/[.,;!? ]+$/g, ''))) {
    return `${label} 'Singapore' is too broad. Please enter a specific Singapore area, MRT, landmark, or 6-digit postal code.`;
  }

  if (/[?!<>{};]/.test(clean)) {
    return `Please enter a valid Singapore location, area, MRT, or 6-digit postal code for ${label.toLowerCase()}.`;
  }

  const lowered = clean.toLowerCase();
  if (LOCATION_KEYBOARD_MASH.some((seq) => lowered.includes(seq))) {
    return `'${clean}' does not look like a real Singapore location (e.g. Bugis, Compass One, 545078).`;
  }
  if (/(?!iii\b)([a-z])\1\1/.test(lowered)) {
    return `'${clean}' does not look like a real Singapore location (e.g. Bugis, Compass One, 545078).`;
  }

  const tokens = lowered.match(/[a-z0-9]+/g) || [];
  const alphaCount = (lowered.match(/[a-z]/g) || []).length;
  const digitCount = (lowered.match(/[0-9]/g) || []).length;
  if ((!tokens.length || alphaCount + digitCount < 3) && !KNOWN_SG_LOCATION_ABBRS.has(lowered)) {
    return 'Please enter a specific Singapore location, MRT station, or 6-digit postal code (e.g. Bugis, Compass One, 545078).';
  }

  for (const tok of tokens) {
    const letters = tok.replace(/[^a-z]/g, '');
    if (!letters || KNOWN_SG_LOCATION_ABBRS.has(letters)) continue;
    const vowels = (letters.match(/[aeiouy]/g) || []).length;
    if (letters.length >= 4 && vowels === 0) {
      return `'${clean}' does not look like a real Singapore location (e.g. Bugis, Compass One, 545078).`;
    }
    if (letters.length >= 6 && vowels / letters.length < 0.18) {
      return `'${clean}' does not look like a real Singapore location (e.g. Bugis, Compass One, 545078).`;
    }
  }
  return '';
}
