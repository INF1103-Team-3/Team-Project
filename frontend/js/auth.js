import {
  authHeaders,
  escapeHtml,
  getAuthToken,
  isUserProfileIncomplete,
  normalizeWishText,
  RECENT_KEY,
  refreshIcons,
  setAuthToken,
  state,
  validateEnglishWishesInput,
} from './state.js?v=20261114-12';
export { validateEnglishWishesInput };
import { apiJson } from './api.js?v=20261114-12';
import { openModal, closeModal } from './modals.js?v=20261114-12';
import { showToast } from './toast.js?v=20261114-12';
import {
  applyFiltersToSearchForm,
  applyUserToSearchForm,
  createRatingSliderController,
  getUserRecentKey,
  initRecentSearches,
  renderRecentSearches,
} from './filters.js?v=20261114-12';
import { formatHours, renderResults } from './results.js?v=20261114-12';

const EMAIL_REGEX = /^[A-Za-z0-9!#$%&'*+\/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+\/=?^_`{|}~-]+)*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;
const PASSWORD_ALLOWED_REGEX = /^[A-Za-z0-9.,?!$]+$/;

export function validateEmailFormat(email) {
  const trimmed = String(email || '').trim();
  const atIdx = trimmed.indexOf('@');
  if (!trimmed || trimmed.length > 254 || atIdx <= 0 || atIdx > 64 || !EMAIL_REGEX.test(trimmed)) {
    return 'Enter a valid email address.';
  }
  return '';
}

export function validateNewPassword(password) {
  const val = String(password || '');
  if (val.length < 8 || val.length > 30) {
    return 'Password must be 8–30 characters.';
  }
  if (!PASSWORD_ALLOWED_REGEX.test(val)) {
    return 'Password may only contain letters, numbers, and .,?!$.';
  }
  return '';
}

const COORD_PAIR_REGEX = /^\s*[+-]?\d+(?:\.\d+)?\s*,\s*[+-]?\d+(?:\.\d+)?\s*$/;

let pendingAuthEmail = '';
let resendCooldownTimer = null;

let chatCallbacks = {
  startOnboardingInChat: () => {},
  refreshGreetingIfIdle: () => {},
  resetChatThread: () => {},
  updateGuestHintBanner: () => {},
};

export function setAuthChatCallbacks(cbs) {
  chatCallbacks = { ...chatCallbacks, ...cbs };
}

export function updateAuthUI() {
  const authOpenBtn = document.getElementById('authOpenBtn');
  const userNavGroup = document.getElementById('userNavGroup');
  const profileUsername = document.getElementById('profileUsername');
  if (!authOpenBtn || !userNavGroup || !profileUsername) return;

  if (state.currentUser) {
    authOpenBtn.classList.add('hidden');
    userNavGroup.classList.remove('hidden');
    userNavGroup.classList.add('flex');
    profileUsername.textContent = state.currentUser.username || 'User';
  } else {
    authOpenBtn.classList.remove('hidden');
    userNavGroup.classList.add('hidden');
    userNavGroup.classList.remove('flex');
  }
  chatCallbacks.updateGuestHintBanner();
  const favBtn = document.getElementById('favoritesOpenBtn');
  const histBtn = document.getElementById('historyOpenBtn');
  if (favBtn) {
    favBtn.title = state.currentUser ? 'View Saved Restaurants' : 'Sign in to sync your saved restaurants across devices';
  }
  if (histBtn) {
    histBtn.title = state.currentUser ? 'View Search History & Re-run Past Searches' : 'Sign in to access your search history';
  }
  refreshIcons(document.querySelector('header'));
}

function showAuthAlert(msg, isError = true) {
  const authAlert = document.getElementById('authAlert');
  if (!authAlert) return;
  authAlert.textContent = msg;
  authAlert.className = isError
    ? 'mx-6 mt-4 p-3 rounded-xl text-xs font-medium border bg-rose-50 dark:bg-rose-950/60 border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300'
    : 'mx-6 mt-4 p-3 rounded-xl text-xs font-medium border bg-emerald-50 dark:bg-emerald-950/60 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300';
}

function resetPasswordVisibilityToggles() {
  document.querySelectorAll('[data-toggle-password]').forEach((btn) => {
    const input = document.getElementById(btn.dataset.togglePassword);
    if (input) input.type = 'password';
    btn.setAttribute('aria-pressed', 'false');
    btn.setAttribute('aria-label', 'Show password');
    const icon = btn.querySelector('i');
    if (icon) icon.setAttribute('data-lucide', 'eye');
    refreshIcons(btn);
  });
}

export function switchAuthTab(mode) {
  resetPasswordVisibilityToggles();
  const authAlert = document.getElementById('authAlert');
  const authTabsContainer = document.getElementById('authTabsContainer');
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const otpVerificationView = document.getElementById('otpVerificationView');
  const tabLoginBtn = document.getElementById('tabLoginBtn');
  const tabRegisterBtn = document.getElementById('tabRegisterBtn');

  authAlert?.classList.add('hidden');
  authTabsContainer?.classList.remove('hidden');
  otpVerificationView?.classList.add('hidden');

  const activeCls = 'py-2 text-xs font-bold rounded-lg bg-white dark:bg-slate-700 text-brand-600 dark:text-brand-400 shadow-sm transition';
  const inactiveCls = 'py-2 text-xs font-bold rounded-lg text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition';

  if (mode === 'login') {
    loginForm?.classList.remove('hidden');
    registerForm?.classList.add('hidden');
    if (tabLoginBtn) tabLoginBtn.className = activeCls;
    if (tabRegisterBtn) tabRegisterBtn.className = inactiveCls;
  } else {
    loginForm?.classList.add('hidden');
    registerForm?.classList.remove('hidden');
    if (tabRegisterBtn) tabRegisterBtn.className = activeCls;
    if (tabLoginBtn) tabLoginBtn.className = inactiveCls;
  }
}

function showOtpView(email, message) {
  pendingAuthEmail = email;
  document.getElementById('authTabsContainer')?.classList.add('hidden');
  document.getElementById('loginForm')?.classList.add('hidden');
  document.getElementById('registerForm')?.classList.add('hidden');
  document.getElementById('otpVerificationView')?.classList.remove('hidden');
  const targetEmail = document.getElementById('otpTargetEmail');
  if (targetEmail) targetEmail.textContent = email;
  const codeInput = document.getElementById('otpCodeInput');
  if (codeInput) codeInput.value = '';
  showAuthAlert(message || `A 6-digit verification code was emailed to ${email}.`, false);
  setTimeout(() => { codeInput?.focus(); }, 80);
  refreshIcons(document.getElementById('authModal'));
}

export function openAuthModalWithNotice(noticeMsg = '') {
  const authModal = document.getElementById('authModal');
  switchAuthTab('login');
  if (noticeMsg) showAuthAlert(noticeMsg, true);
  openModal(authModal, '#loginEmail');
}

export async function loadFavorites() {
  const badge = document.getElementById('favoritesCountBadge');
  if (!state.currentUser) {
    state.favoriteKeys = new Set();
    state.favoritesList = [];
    if (badge) badge.textContent = '0';
    return;
  }
  try {
    const data = await apiJson('/api/favorites');
    state.favoritesList = data.favorites || [];
    state.favoriteKeys = new Set(state.favoritesList.map((f) => f.place_key));
    if (badge) badge.textContent = String(state.favoritesList.length);
    if (state.lastMatches.length > 0 || state.lastAlternatives.length > 0) {
      renderResults(state.lastMatches, state.lastAlternatives);
    }
  } catch (err) {
    console.warn('Could not load favorites:', err);
  }
}

export async function toggleFavoriteByIndex(displayIdx) {
  if (!state.currentUser) {
    openAuthModalWithNotice('Please sign in to bookmark favorite restaurants to your account.');
    return;
  }
  const item = state.displayedItems[displayIdx];
  if (!item || !item.restaurant) return;
  try {
    const wasFav = state.favoriteKeys.has(item.restaurant.place_key || '');
    await apiJson('/api/favorites', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ restaurant: item.restaurant }),
    });
    await loadFavorites();
    showToast(
      wasFav ? 'Updated saved restaurant.' : `Saved ${item.restaurant.name || 'restaurant'}!`,
      'success',
      2800,
    );
  } catch (err) {
    showToast(`Could not save favorite: ${err.message}`, 'error');
  }
}

async function removeFavoriteByKey(placeKey) {
  try {
    await apiJson(`/api/favorites?place_key=${encodeURIComponent(placeKey)}`, {
      method: 'DELETE',
    });
    await loadFavorites();
    renderFavoritesModalList();
    showToast('Removed from Saved.', 'info', 2500);
  } catch (err) {
    showToast(`Remove favorite failed: ${err.message}`, 'error');
  }
}

function renderFavoritesModalList() {
  const container = document.getElementById('favoritesListContainer');
  if (!container) return;

  if (!state.currentUser) {
    container.innerHTML = `
      <div class="p-8 text-center text-slate-500 dark:text-slate-400">
        <i data-lucide="lock" class="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto mb-2"></i>
        <p class="font-bold text-slate-700 dark:text-slate-200">Sign in to view your saved restaurants</p>
        <p class="mt-1">Saved favorites are private and tied to your personal BiteFinder account.</p>
      </div>
    `;
    refreshIcons(container);
    return;
  }

  if (!state.favoritesList || state.favoritesList.length === 0) {
    container.innerHTML = `
      <div class="p-8 text-center text-slate-500 dark:text-slate-400">
        <i data-lucide="heart" class="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto mb-2"></i>
        <p class="font-bold text-slate-700 dark:text-slate-200">No saved restaurants yet</p>
        <p class="mt-1">Click the <strong>Save</strong> button on any restaurant recommendation card to bookmark it here.</p>
      </div>
    `;
    refreshIcons(container);
    return;
  }

  container.innerHTML = state.favoritesList.map((fav) => {
    const r = fav.restaurant || {};
    const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${r.name || 'Restaurant'} ${r.address || 'Singapore'}`)}`;
    const hours = formatHours(r);
    return `
      <div class="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/70 border border-slate-200 dark:border-slate-700 flex flex-col gap-2">
        <div class="flex items-start justify-between gap-2">
          <div>
            <h4 class="text-sm font-bold text-slate-900 dark:text-white">${escapeHtml(r.name || 'Restaurant')}</h4>
            <p class="text-[11px] text-slate-500 dark:text-slate-400">${escapeHtml(r.address || 'Singapore')}</p>
          </div>
          <span class="px-2 py-0.5 rounded-lg bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 font-bold border border-amber-200 dark:border-amber-800 shrink-0">
            ★ ${escapeHtml(r.rating || r.g_rating || 'N/A')}
          </span>
        </div>
        <div class="text-[11px] text-slate-600 dark:text-slate-300 flex items-center gap-2">
          <span>🕒 ${escapeHtml(hours)}</span>
          ${r.price_range ? `<span>• 💰 ${escapeHtml(r.price_range)}</span>` : ''}
        </div>
        <div class="flex items-center justify-between pt-2 border-t border-slate-200/70 dark:border-slate-700/70">
          <button type="button" data-remove-fav="${escapeHtml(fav.place_key)}"
            class="text-rose-600 dark:text-rose-400 hover:underline font-bold flex items-center gap-1">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i> Remove
          </button>
          <a href="${mapsUrl}" target="_blank" rel="noopener noreferrer"
            class="text-brand-600 dark:text-brand-400 hover:underline font-bold flex items-center gap-1">
            Open in Google Maps <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
          </a>
        </div>
      </div>
    `;
  }).join('');

  container.querySelectorAll('[data-remove-fav]').forEach((btn) => {
    btn.addEventListener('click', () => removeFavoriteByKey(btn.dataset.removeFav));
  });
  refreshIcons(container);
}

function rerunHistoryItem(idx) {
  const item = state.searchHistoryEntries[idx];
  if (!item) return;
  const savedLocs = Array.isArray(item.locations) && item.locations.length
    ? item.locations
    : (item.query ? String(item.query).split(' + ').map((s) => s.trim()).filter(Boolean) : ['Compass One']);

  const histLiked = Array.isArray(item.liked_cuisines) && item.liked_cuisines.length
    ? item.liked_cuisines
    : (item.cuisine ? String(item.cuisine).split(',').map((s) => s.trim()).filter(Boolean) : []);

  applyFiltersToSearchForm({
    location: savedLocs[0],
    locations: savedLocs,
    mode: item.mode || 'walk',
    traffic_aware: Boolean(item.traffic_aware),
    max_travel_minutes: item.max_travel_minutes ?? null,
    max_distance_km: item.max_distance_km ?? null,
    budget_per_person: item.budget_per_person ?? 30,
    dietary_requirements: item.dietary_requirements || [],
    liked_cuisines: histLiked,
    disliked_cuisines: item.disliked_cuisines || [],
    other_preferences: item.other_preferences || [],
  });

  closeModal(document.getElementById('historyModal'));
  document.getElementById('searchForm')?.requestSubmit();
}

async function loadAndRenderHistory() {
  const container = document.getElementById('historyListContainer');
  const clearBtn = document.getElementById('clearHistoryBtn');
  if (!container) return;

  if (!state.currentUser) {
    state.searchHistoryEntries = [];
    clearBtn?.classList.add('hidden');
    container.innerHTML = `
      <div class="p-8 text-center text-slate-500 dark:text-slate-400">
        <i data-lucide="lock" class="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto mb-2"></i>
        <p class="font-bold text-slate-700 dark:text-slate-200">Sign in to view your search history</p>
        <p class="mt-1">Search history is privately tied to your BiteFinder account so each user only sees their own past searches.</p>
      </div>
    `;
    refreshIcons(container);
    return;
  }

  clearBtn?.classList.remove('hidden');
  container.innerHTML = '<div class="py-6 text-center text-slate-400">Loading search history from MongoDB...</div>';

  try {
    const data = await apiJson('/api/history');
    state.searchHistoryEntries = data.history || [];

    if (state.searchHistoryEntries.length === 0) {
      container.innerHTML = `
        <div class="p-8 text-center text-slate-500 dark:text-slate-400">
          <i data-lucide="history" class="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto mb-2"></i>
          <p class="font-bold text-slate-700 dark:text-slate-200">No search history recorded yet</p>
          <p class="mt-1">Every restaurant search is automatically logged in MongoDB so you can re-run it with one click.</p>
        </div>
      `;
      refreshIcons(container);
      return;
    }

    container.innerHTML = state.searchHistoryEntries.map((item, idx) => {
      const ts = item.timestamp ? new Date(item.timestamp).toLocaleString('en-SG', { dateStyle: 'medium', timeStyle: 'short' }) : '';
      const dietBadges = (item.dietary_requirements || []).map((d) => (
        `<span class="px-2 py-0.5 rounded-md bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 font-semibold uppercase text-[10px]">${escapeHtml(d)}</span>`
      )).join(' ');
      return `
        <div class="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/70 border border-slate-200 dark:border-slate-700 flex items-center justify-between gap-3">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="text-sm font-bold text-slate-900 dark:text-white">📍 ${escapeHtml(item.query || 'Singapore')}</span>
              <span class="px-2 py-0.5 rounded-full bg-brand-50 dark:bg-brand-500/15 text-brand-700 dark:text-brand-300 text-[10px] font-bold">${escapeHtml(item.results_count || 0)} found</span>
            </div>
            <div class="text-[11px] text-slate-500 dark:text-slate-400 flex flex-wrap items-center gap-2">
              <span class="capitalize">🚶 Mode: <strong>${escapeHtml(item.mode || 'walk')}</strong></span>
              <span>• ⏱️ Max ${escapeHtml(item.max_travel_minutes || 30)}m</span>
              <span>• 💰 SGD $${item.budget_per_person != null && Number(item.budget_per_person) > 100 ? '100+' : escapeHtml(item.budget_per_person || 30)}</span>
              ${item.cuisine ? `<span>• 🍽️ ${escapeHtml(item.cuisine)}</span>` : ''}
              ${dietBadges}
            </div>
            ${ts ? `<div class="text-[10px] text-slate-400">${escapeHtml(ts)}</div>` : ''}
          </div>
          <button type="button" data-rerun-idx="${idx}"
            class="px-3 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-brand-600 to-amber-600 hover:from-brand-700 hover:to-amber-700 shadow-sm shrink-0 flex items-center gap-1.5 transition">
            <i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i>
            <span>Re-Run</span>
          </button>
        </div>
      `;
    }).join('');

    container.querySelectorAll('[data-rerun-idx]').forEach((btn) => {
      btn.addEventListener('click', () => rerunHistoryItem(Number(btn.dataset.rerunIdx)));
    });
    refreshIcons(container);
  } catch (err) {
    container.innerHTML = `<div class="p-4 text-rose-500 text-center">Failed to load history: ${escapeHtml(err.message)}</div>`;
  }
}

export async function checkSession(triggerOnboarding = true) {
  const token = getAuthToken();
  if (!token) {
    updateAuthUI();
    initRecentSearches();
    return;
  }
  try {
    const data = await apiJson('/api/auth/me');
    state.currentUser = data.user;
    updateAuthUI();
    applyUserToSearchForm(state.currentUser);
    initRecentSearches();
    loadFavorites();
    if (triggerOnboarding && !state.onboardingActive && isUserProfileIncomplete(state.currentUser)) {
      chatCallbacks.startOnboardingInChat();
    } else {
      chatCallbacks.refreshGreetingIfIdle();
    }
  } catch {
    setAuthToken('');
    state.currentUser = null;
    updateAuthUI();
    initRecentSearches();
  }
}

export function initAuthAndModals() {
  const authModal = document.getElementById('authModal');
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const otpForm = document.getElementById('otpForm');
  const profileModal = document.getElementById('profileModal');
  const profileAlert = document.getElementById('profileAlert');
  const favoritesModal = document.getElementById('favoritesModal');
  const historyModal = document.getElementById('historyModal');

  document.getElementById('authOpenBtn')?.addEventListener('click', () => openAuthModalWithNotice(''));
  document.getElementById('closeAuthModalBtn')?.addEventListener('click', () => {
    resetPasswordVisibilityToggles();
    closeModal(authModal);
  });
  document.getElementById('tabLoginBtn')?.addEventListener('click', () => switchAuthTab('login'));
  document.getElementById('tabRegisterBtn')?.addEventListener('click', () => switchAuthTab('register'));

  document.querySelectorAll('[data-toggle-password]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.togglePassword;
      const input = targetId ? document.getElementById(targetId) : null;
      if (!input) return;
      const revealing = input.type === 'password';
      input.type = revealing ? 'text' : 'password';
      btn.setAttribute('aria-pressed', revealing ? 'true' : 'false');
      btn.setAttribute('aria-label', revealing ? 'Hide password' : 'Show password');
      const icon = btn.querySelector('i');
      if (icon) {
        icon.setAttribute('data-lucide', revealing ? 'eye-off' : 'eye');
        refreshIcons(btn);
      }
      input.focus();
    });
  });

  // Sign In Submit
  loginForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    document.getElementById('authAlert')?.classList.add('hidden');
    const email = document.getElementById('loginEmail')?.value.trim() || '';
    const password = document.getElementById('loginPassword')?.value || '';
    const emailErr = validateEmailFormat(email);
    if (emailErr) {
      showAuthAlert(emailErr, true);
      return;
    }

    try {
      const data = await apiJson('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (data.otp_required) {
        showOtpView(data.email || email, data.message);
        return;
      }

      setAuthToken(data.token);
      state.currentUser = data.user;
      updateAuthUI();
      applyUserToSearchForm(state.currentUser);
      initRecentSearches();
      loadFavorites();
      closeModal(authModal);
      loginForm.reset();
      showToast(`Welcome back, ${state.currentUser.username || 'User'}!`, 'success');
      if (isUserProfileIncomplete(state.currentUser)) {
        chatCallbacks.startOnboardingInChat();
      } else {
        chatCallbacks.refreshGreetingIfIdle();
      }
    } catch (err) {
      showAuthAlert(err.message, true);
    }
  });

  // Register Submit
  registerForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    document.getElementById('authAlert')?.classList.add('hidden');
    const username = document.getElementById('registerUsername')?.value.trim() || '';
    const email = document.getElementById('registerEmail')?.value.trim() || '';
    const password = document.getElementById('registerPassword')?.value || '';
    const emailErr = validateEmailFormat(email);
    if (emailErr) {
      showAuthAlert(emailErr, true);
      return;
    }
    const passwordErr = validateNewPassword(password);
    if (passwordErr) {
      showAuthAlert(passwordErr, true);
      return;
    }

    try {
      const data = await apiJson('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, email, password }),
      });

      if (data.otp_required) {
        showOtpView(data.email || email, data.message);
        return;
      }

      setAuthToken(data.token);
      state.currentUser = data.user;
      updateAuthUI();
      applyUserToSearchForm(state.currentUser);
      initRecentSearches();
      loadFavorites();
      closeModal(authModal);
      registerForm.reset();
      showToast('Account created! Let us tailor your dining profile.', 'success');
      chatCallbacks.startOnboardingInChat();
    } catch (err) {
      showAuthAlert(err.message, true);
    }
  });

  // OTP Verification Submit
  otpForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    document.getElementById('authAlert')?.classList.add('hidden');
    const code = document.getElementById('otpCodeInput')?.value.trim() || '';
    if (!code || !pendingAuthEmail) {
      showAuthAlert('Please enter the 6-digit verification code.', true);
      return;
    }

    const submitBtn = document.getElementById('verifyOtpSubmitBtn');
    const origHtml = submitBtn ? submitBtn.innerHTML : '';
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<svg class="animate-spin w-4 h-4 text-white inline-block mr-1.5" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg> <span>Verifying...</span>';
    }

    try {
      const data = await apiJson('/api/auth/verify-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: pendingAuthEmail, code }),
      });

      setAuthToken(data.token);
      state.currentUser = data.user;
      updateAuthUI();
      applyUserToSearchForm(state.currentUser);
      initRecentSearches();
      loadFavorites();
      closeModal(authModal);
      loginForm?.reset();
      registerForm?.reset();
      otpForm.reset();
      switchAuthTab('login');
      showToast('Verified! Signed in to BiteFinder.', 'success');
      if (isUserProfileIncomplete(state.currentUser)) {
        chatCallbacks.startOnboardingInChat();
      } else {
        chatCallbacks.refreshGreetingIfIdle();
      }
    } catch (err) {
      showAuthAlert(err.message, true);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = origHtml;
      }
    }
  });

  // Resend OTP
  document.getElementById('resendOtpBtn')?.addEventListener('click', async () => {
    if (!pendingAuthEmail) return;
    const resendBtn = document.getElementById('resendOtpBtn');
    if (resendBtn) resendBtn.disabled = true;
    try {
      const data = await apiJson('/api/auth/resend-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: pendingAuthEmail }),
      });
      showAuthAlert(data.message || 'A new verification code was sent to your email.', false);

      let remaining = 60;
      if (resendBtn) resendBtn.textContent = `Resend in ${remaining}s`;
      if (resendCooldownTimer) clearInterval(resendCooldownTimer);
      resendCooldownTimer = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
          clearInterval(resendCooldownTimer);
          if (resendBtn) {
            resendBtn.disabled = false;
            resendBtn.textContent = 'Resend Code';
          }
        } else if (resendBtn) {
          resendBtn.textContent = `Resend in ${remaining}s`;
        }
      }, 1000);
    } catch (err) {
      if (resendBtn) resendBtn.disabled = false;
      showAuthAlert(err.message, true);
    }
  });

  document.getElementById('cancelOtpBtn')?.addEventListener('click', () => {
    pendingAuthEmail = '';
    switchAuthTab('login');
  });

  // Sign Out
  document.getElementById('logoutBtn')?.addEventListener('click', async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST', headers: authHeaders() });
    } catch { }
    setAuthToken('');
    state.currentUser = null;
    state.favoriteKeys = new Set();
    state.favoritesList = [];
    state.searchHistoryEntries = [];
    const badge = document.getElementById('favoritesCountBadge');
    if (badge) badge.textContent = '0';
    updateAuthUI();
    initRecentSearches();
    if (state.lastMatches.length > 0 || state.lastAlternatives.length > 0) {
      renderResults(state.lastMatches, state.lastAlternatives);
    }
    chatCallbacks.resetChatThread(true);
    showToast('Signed out.', 'info');
  });

  // Profile Modal
  const PROFILE_DIST_MAX = 50;
  const PROFILE_TIME_MAX = 150;
  const PROFILE_BUDGET_MIN = 1;
  const PROFILE_BUDGET_MAX_EXACT = 100;
  const PROFILE_BUDGET_PLUS_BACKEND = 1000;
  const profDistInput = document.getElementById('profDistInput');
  const profTimeInput = document.getElementById('profTimeInput');
  const profBudgetInput = document.getElementById('profBudgetInput');

  const bindProfileMaxClamp = (inputEl, maxVal) => {
    if (!inputEl) return;
    inputEl.addEventListener('input', (e) => {
      const raw = String(e.target.value || '').trim();
      if (!raw) return;
      const num = parseFloat(raw);
      if (Number.isFinite(num) && num > maxVal) {
        e.target.value = String(maxVal);
      }
    });
    inputEl.addEventListener('change', (e) => {
      const raw = String(e.target.value || '').trim();
      if (!raw) {
        e.target.value = '';
        return;
      }
      const num = parseFloat(raw);
      if (!Number.isFinite(num)) return;
      if (num > maxVal) {
        e.target.value = String(maxVal);
      } else if (num > 0) {
        e.target.value = String(Math.round(num * 100) / 100);
      }
    });
  };

  bindProfileMaxClamp(profDistInput, PROFILE_DIST_MAX);
  bindProfileMaxClamp(profTimeInput, PROFILE_TIME_MAX);

  const formatProfileBudgetDisplay = (rawBudget) => {
    if (rawBudget == null || rawBudget === '') return '';
    const num = Number(rawBudget);
    if (!Number.isFinite(num)) return '';
    if (num > PROFILE_BUDGET_MAX_EXACT) return '100+';
    return String(Math.round(num * 100) / 100);
  };

  const normalizeProfileBudgetInput = (raw) => {
    const str = String(raw || '').trim();
    if (!str) return '';
    const hasPlus = /\+$/.test(str);
    let seenDot = false;
    const cleaned = str
      .replace(/[^\d.]/g, '')
      .replace(/\./g, () => {
        if (seenDot) return '';
        seenDot = true;
        return '.';
      });
    if (!cleaned) return '';
    if (cleaned === '.') return '.';
    const num = parseFloat(cleaned);
    if (Number.isFinite(num) && (num > PROFILE_BUDGET_MAX_EXACT || (hasPlus && num >= PROFILE_BUDGET_MAX_EXACT))) {
      return '100+';
    }
    return cleaned;
  };

  const parseProfileBudgetValue = (raw) => {
    const trimmed = String(raw || '').trim();
    if (!trimmed) return { value: null, isPlus: false };
    const normalized = normalizeProfileBudgetInput(trimmed);
    if (normalized === '100+') return { value: PROFILE_BUDGET_PLUS_BACKEND, isPlus: true };
    const num = parseFloat(normalized);
    if (!Number.isFinite(num)) return { value: NaN, isPlus: false };
    if (num > PROFILE_BUDGET_MAX_EXACT) return { value: PROFILE_BUDGET_PLUS_BACKEND, isPlus: true };
    return { value: Math.round(num * 100) / 100, isPlus: false };
  };

  profBudgetInput?.addEventListener('input', (e) => {
    const normalized = normalizeProfileBudgetInput(e.target.value);
    if (normalized !== e.target.value) {
      e.target.value = normalized;
    }
  });

  profBudgetInput?.addEventListener('change', (e) => {
    const normalized = normalizeProfileBudgetInput(e.target.value);
    if (normalized === '' || normalized === '.') {
      e.target.value = '';
      return;
    }
    if (normalized === '100+') {
      e.target.value = '100+';
      return;
    }
    const num = parseFloat(normalized);
    e.target.value = Number.isFinite(num)
      ? (num > PROFILE_BUDGET_MAX_EXACT ? '100+' : String(Math.round(num * 100) / 100))
      : '';
  });

  document.getElementById('profileBtn')?.addEventListener('click', async () => {
    if (!state.currentUser) return;
    profileAlert?.classList.add('hidden');
    try {
      const meData = await apiJson('/api/auth/me');
      if (meData.user) {
        state.currentUser = meData.user;
        applyUserToSearchForm(state.currentUser);
      }
    } catch { }
    const emailDisplay = document.getElementById('profileEmailDisplay');
    if (emailDisplay) emailDisplay.textContent = `Signed in as ${state.currentUser.email || ''}`;
    document.getElementById('profUsernameInput').value = state.currentUser.username || '';
    document.getElementById('profLocationInput').value = Array.isArray(state.currentUser.location) ? state.currentUser.location.join(', ') : (state.currentUser.location || '');
    document.getElementById('profDistInput').value = state.currentUser.max_distance_km ?? '';
    document.getElementById('profTimeInput').value = state.currentUser.max_travel_time_minutes ?? '';
    if (profBudgetInput) profBudgetInput.value = formatProfileBudgetDisplay(state.currentUser.budget_per_person);
    const diet = state.currentUser.dietary_requirements || [];
    document.getElementById('profHalalCheck').checked = diet.includes('halal');
    document.getElementById('profVegCheck').checked = diet.includes('vegetarian');
    document.getElementById('profLikedInput').value = (state.currentUser.liked_cuisines || []).join(', ');
    document.getElementById('profDislikedInput').value = (state.currentUser.disliked_cuisines || []).join(', ');
    document.getElementById('profOtherInput').value = (state.currentUser.other_preferences || []).join(', ');
    profRatingControl?.syncFromWishes();
    openModal(profileModal, '#profUsernameInput');
  });

  const profRatingControl = createRatingSliderController({
    wrapId: 'profRatingDisplayWrap',
    inputId: 'profRatingInput',
    unitId: 'profRatingUnitLabel',
    clearBtnId: 'profRatingClearBtn',
    sliderId: 'profRatingSlider',
    scaleMinId: 'profRatingScaleMin',
    wishInputId: 'profOtherInput',
  });

  document.getElementById('closeProfileModalBtn')?.addEventListener('click', () => closeModal(profileModal));
  document.getElementById('cancelProfileBtn')?.addEventListener('click', () => closeModal(profileModal));

  document.getElementById('profileForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!state.currentUser) return;
    profileAlert?.classList.add('hidden');
    const diet = [];
    if (document.getElementById('profHalalCheck')?.checked) diet.push('halal');
    if (document.getElementById('profVegCheck')?.checked) diet.push('vegetarian');
    const likedRaw = document.getElementById('profLikedInput')?.value.trim() || '';
    const likedList = likedRaw ? likedRaw.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean) : [];
    const dislikedRaw = document.getElementById('profDislikedInput')?.value.trim() || '';
    const dislikedList = dislikedRaw ? dislikedRaw.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean) : [];
    const otherRaw = document.getElementById('profOtherInput')?.value.trim() || '';
    const otherList = otherRaw ? otherRaw.split(',').map(normalizeWishText).filter(Boolean) : [];
    const locVal = document.getElementById('profLocationInput')?.value.trim() || '';
    const distVal = document.getElementById('profDistInput')?.value.trim() || '';
    const timeVal = document.getElementById('profTimeInput')?.value.trim() || '';
    const budgetVal = profBudgetInput?.value.trim() || '';

    const showProfileError = (msg) => {
      if (profileAlert) {
        profileAlert.textContent = msg;
        profileAlert.className = 'mx-6 mt-4 p-3 rounded-xl text-xs font-medium border bg-rose-50 dark:bg-rose-950/60 border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300';
      }
    };

    const usernameVal = document.getElementById('profUsernameInput')?.value.trim() || '';
    if (!usernameVal) {
      showProfileError('Username cannot be empty.');
      return;
    }

    let parsedDist = distVal !== '' ? parseFloat(distVal) : null;
    let parsedTime = timeVal !== '' ? parseFloat(timeVal) : null;
    const { value: parsedBudget, isPlus: isBudgetPlus } = parseProfileBudgetValue(budgetVal);
    if (isBudgetPlus && profBudgetInput) {
      profBudgetInput.value = '100+';
    }
    if (parsedDist !== null && Number.isFinite(parsedDist) && parsedDist > PROFILE_DIST_MAX) {
      parsedDist = PROFILE_DIST_MAX;
      if (profDistInput) profDistInput.value = String(PROFILE_DIST_MAX);
    }
    if (parsedTime !== null && Number.isFinite(parsedTime) && parsedTime > PROFILE_TIME_MAX) {
      parsedTime = PROFILE_TIME_MAX;
      if (profTimeInput) profTimeInput.value = String(PROFILE_TIME_MAX);
    }
    if (parsedDist !== null && (!Number.isFinite(parsedDist) || parsedDist < 0.01 || parsedDist > PROFILE_DIST_MAX)) {
      showProfileError('Max distance must be between 0.01 and 50 km.');
      return;
    }
    if (parsedTime !== null && (!Number.isFinite(parsedTime) || parsedTime < 1 || parsedTime > PROFILE_TIME_MAX)) {
      showProfileError('Max time must be between 1 and 150 mins.');
      return;
    }
    if (parsedBudget !== null && (!Number.isFinite(parsedBudget) || parsedBudget < PROFILE_BUDGET_MIN || parsedBudget > PROFILE_BUDGET_PLUS_BACKEND)) {
      showProfileError('Budget must be between SGD $1 and $100+.');
      return;
    }
    const wishesErr = validateEnglishWishesInput(otherList, 'Default special wishes');
    if (wishesErr) {
      showProfileError(wishesErr);
      return;
    }

    let locations = [];
    if (locVal) {
      locations = COORD_PAIR_REGEX.test(locVal)
        ? [locVal]
        : locVal.split(',').map((s) => s.trim()).filter(Boolean);
    }

    const body = {
      user_id: state.currentUser.user_id,
      username: usernameVal,
      email: state.currentUser.email,
      location: locations,
      max_distance_km: parsedDist,
      max_travel_time_minutes: parsedTime,
      budget_per_person: parsedBudget,
      dietary_requirements: diet,
      liked_cuisines: likedList,
      disliked_cuisines: dislikedList,
      other_preferences: otherList,
    };

    try {
      const data = await apiJson('/api/profile', {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(body),
      });
      state.currentUser = data.user || body;
      updateAuthUI();
      applyUserToSearchForm(state.currentUser);
      chatCallbacks.refreshGreetingIfIdle();
      if (profileAlert) {
        profileAlert.textContent = 'Preferences saved to MongoDB and applied to your search!';
        profileAlert.className = 'mx-6 mt-4 p-3 rounded-xl text-xs font-medium border bg-emerald-50 dark:bg-emerald-950/60 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300';
      }
      showToast('Profile preferences saved.', 'success');
      setTimeout(() => closeModal(profileModal), 750);
    } catch (err) {
      showProfileError(err.message);
    }
  });

  // Favorites & History Modals
  document.getElementById('favoritesOpenBtn')?.addEventListener('click', async () => {
    await loadFavorites();
    renderFavoritesModalList();
    openModal(favoritesModal);
  });
  document.getElementById('closeFavoritesModalBtn')?.addEventListener('click', () => closeModal(favoritesModal));
  document.getElementById('closeFavoritesFooterBtn')?.addEventListener('click', () => closeModal(favoritesModal));

  document.getElementById('historyOpenBtn')?.addEventListener('click', () => {
    loadAndRenderHistory();
    openModal(historyModal);
  });
  document.getElementById('closeHistoryModalBtn')?.addEventListener('click', () => closeModal(historyModal));
  document.getElementById('closeHistoryFooterBtn')?.addEventListener('click', () => closeModal(historyModal));

  document.getElementById('clearHistoryBtn')?.addEventListener('click', async () => {
    try {
      await apiJson('/api/history', { method: 'DELETE' });
      const key = getUserRecentKey();
      if (key) {
        try { localStorage.removeItem(key); } catch { }
      }
      try { localStorage.removeItem(RECENT_KEY); } catch { }
      renderRecentSearches([]);
      loadAndRenderHistory();
      showToast('Search history cleared.', 'info');
    } catch (err) {
      showToast(`Could not clear history: ${err.message}`, 'error');
    }
  });
}
