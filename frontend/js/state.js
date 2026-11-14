export const TOKEN_KEY = 'bitefinder_auth_token';
export const RECENT_KEY = 'bitefinder_recent_searches';
export const THEME_KEY = 'bitefinder_theme';

export const state = {
  currentMode: 'walk',
  activeSearchMode: 'walk',
  currentLimitType: 'time',
  isTravelSet: false,
  isBudgetSet: false,

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
