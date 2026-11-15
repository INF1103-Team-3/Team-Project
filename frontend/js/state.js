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
