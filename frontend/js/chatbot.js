import {
  escapeHtml,
  formatCuisineLabel,
  getSingaporeDate,
  refreshIcons,
  state,
} from './state.js?v=20261114-9';
import { apiJson } from './api.js?v=20261114-9';
import { authHeaders } from './state.js?v=20261114-9';
import {
  applyFiltersToSearchForm,
  applyUserToSearchForm,
  collectCurrentFormPayload,
  isBudgetPlusDisplay,
} from './filters.js?v=20261114-9';
import { getPriceValue, getRatingValue, getTravelMinutes, resetResultsDisplay } from './results.js?v=20261114-9';
import { flyToMarkerForItem } from './map.js?v=20261114-9';
import { showToast } from './toast.js?v=20261114-9';

let authCallbacks = {
  onProfileSaved: () => {},
  openAuthModal: () => {},
};

export function setChatbotAuthCallbacks(cbs) {
  authCallbacks = { ...authCallbacks, ...cbs };
}

export function setLeftPanelMode(mode) {
  const chatbotPanel = document.getElementById('chatbotPanel');
  const filtersPanel = document.getElementById('filtersPanel');
  const tabChatModeBtn = document.getElementById('tabChatModeBtn');
  const tabFiltersModeBtn = document.getElementById('tabFiltersModeBtn');
  if (!chatbotPanel || !filtersPanel || !tabChatModeBtn || !tabFiltersModeBtn) return;

  const isChat = mode === 'chat';
  chatbotPanel.classList.toggle('hidden', !isChat);
  filtersPanel.classList.toggle('hidden', isChat);

  const activeCls = 'py-2 px-3 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 bg-white dark:bg-slate-700 text-brand-600 dark:text-brand-300 shadow-sm transition';
  const inactiveCls = 'py-2 px-3 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition';
  tabChatModeBtn.className = isChat ? activeCls : inactiveCls;
  tabFiltersModeBtn.className = isChat ? inactiveCls : activeCls;

  renderChatFilterSummary();
  const chatInput = document.getElementById('chatInput');
  if (isChat && chatInput) {
    chatInput.focus();
  }
  refreshIcons(document.getElementById('leftPanelColumn'));
}

export function updateGuestHintBanner() {
  const banner = document.getElementById('guestHintBanner');
  if (!banner) return;
  if (state.currentUser) {
    banner.classList.add('hidden');
  } else {
    banner.classList.remove('hidden');
  }
}

export function updateOnboardingProgressUI(step = null, total = 7) {
  const bar = document.getElementById('onboardingProgressBar');
  const label = document.getElementById('onboardingProgressLabel');
  const fill = document.getElementById('onboardingProgressFill');
  if (!bar || !label || !fill) return;

  if (!state.onboardingActive || !step) {
    bar.classList.add('hidden');
    return;
  }

  const safeTotal = Math.max(1, Number(total) || 7);
  const safeStep = Math.min(safeTotal, Math.max(1, Number(step) || 1));
  const pct = Math.round((safeStep / safeTotal) * 100);
  label.textContent = `Profile setup • Step ${safeStep} of ${safeTotal}`;
  fill.style.width = `${pct}%`;
  bar.classList.remove('hidden');
}

export function renderChatFilterSummary() {
  const summaryEl = document.getElementById('chatFilterSummary');
  if (!summaryEl) return;

  const p = collectCurrentFormPayload(true);
  const pills = [];
  const hasLoc = Boolean((p.locations && p.locations.length) || p.location);
  const locLabel = (p.locations && p.locations.length)
    ? p.locations.join(' + ')
    : (p.location || 'Location not set');
  pills.push({ text: `📍 ${locLabel}`, missing: !hasLoc });

  const modeIcon = p.mode === 'drive' ? '🚗 Drive' : (p.mode === 'transit' ? '🚆 Transit' : '🚶 Walk');
  if (p.max_distance_km != null) {
    pills.push({ text: `${modeIcon} · ${p.max_distance_km} km`, missing: false });
  } else if (p.max_travel_minutes != null) {
    pills.push({ text: `${modeIcon} · ${Math.round(p.max_travel_minutes)} mins`, missing: false });
  } else {
    pills.push({ text: '🚶 Travel not set', missing: true });
  }

  if (p.budget_per_person != null) {
    const roundedBud = Math.round(p.budget_per_person * 100) / 100;
    const budLabel = isBudgetPlusDisplay(roundedBud, true) ? '$100+' : `$${roundedBud}`;
    pills.push({ text: `💰 ${budLabel}`, missing: false });
  } else {
    pills.push({ text: '💰 Budget not set', missing: true });
  }

  if (
    !state.onboardingActive
    && (
      (state.awaitingChatField === 'location' && hasLoc)
      || (state.awaitingChatField === 'budget_per_person' && p.budget_per_person != null)
      || (state.awaitingChatField === 'travel' && (p.max_distance_km != null || p.max_travel_minutes != null))
    )
  ) {
    state.awaitingChatField = null;
  }

  (p.dietary_requirements || []).forEach((d) => {
    pills.push({ text: d === 'halal' ? '🕌 Halal' : '🥗 Vegetarian', missing: false });
  });
  if (p.liked_cuisines && p.liked_cuisines.length) {
    pills.push({ text: `🍽️ ${p.liked_cuisines.map(formatCuisineLabel).join(', ')}`, missing: false });
  }
  if (p.disliked_cuisines && p.disliked_cuisines.length) {
    pills.push({ text: `🚫 No ${p.disliked_cuisines.map(formatCuisineLabel).join(', ')}`, missing: false });
  }
  if (p.other_preferences && p.other_preferences.length) {
    pills.push({ text: `✨ ${p.other_preferences.join(', ')}`, missing: false });
  }

  summaryEl.innerHTML = pills.map((pill) => {
    const cls = pill.missing
      ? 'px-2 py-0.5 rounded-md text-[10px] font-semibold bg-amber-50/70 dark:bg-amber-950/30 border border-dashed border-amber-300 dark:border-amber-700/70 text-amber-700 dark:text-amber-300 hover:border-brand-400 transition'
      : 'px-2 py-0.5 rounded-md text-[10px] font-semibold bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:border-brand-400 transition';
    return `<button type="button" data-open-filters="1" class="${cls}">${escapeHtml(pill.text)}</button>`;
  }).join('');

  summaryEl.querySelectorAll('[data-open-filters]').forEach((btn) => {
    btn.addEventListener('click', () => setLeftPanelMode('filters'));
  });
}

export function appendChatBubble(role, text, options = {}) {
  const chatMessagesEl = document.getElementById('chatMessages');
  if (!chatMessagesEl) return null;

  const isUser = role === 'user';
  const wrapper = document.createElement('div');
  wrapper.className = `flex ${isUser ? 'justify-end' : 'justify-start'}`;

  const bubble = document.createElement('div');
  bubble.className = isUser
    ? 'max-w-[88%] px-3.5 py-2.5 rounded-2xl rounded-br-sm text-xs leading-relaxed bg-gradient-to-r from-brand-600 to-amber-600 text-white shadow-sm'
    : 'max-w-[92%] px-3.5 py-2.5 rounded-2xl rounded-bl-sm text-xs leading-relaxed bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-100 shadow-sm space-y-2';

  const textEl = document.createElement('div');
  textEl.className = options.pending ? 'flex items-center gap-2 text-slate-500 dark:text-slate-400 italic' : 'whitespace-pre-line';
  if (options.pending) {
    textEl.innerHTML = `<svg class="animate-spin h-3.5 w-3.5 text-brand-600 shrink-0" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg><span>${escapeHtml(text)}</span>`;
  } else {
    textEl.textContent = text;
  }
  bubble.appendChild(textEl);

  if (Array.isArray(options.changes) && options.changes.length) {
    const changesWrap = document.createElement('div');
    changesWrap.className = 'flex flex-wrap gap-1 pt-0.5';
    changesWrap.innerHTML = options.changes.map((c) => (
      `<span class="px-1.5 py-0.5 rounded bg-brand-50 dark:bg-brand-500/15 text-brand-700 dark:text-brand-300 border border-brand-200 dark:border-brand-500/30 text-[10px] font-semibold">${escapeHtml(c)}</span>`
    )).join('');
    bubble.appendChild(changesWrap);
  }

  if (Array.isArray(options.topPicks) && options.topPicks.length) {
    const picksWrap = document.createElement('div');
    picksWrap.className = 'space-y-1.5 pt-1';
    options.topPicks.forEach((pick) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'w-full text-left p-2 rounded-xl bg-slate-50 dark:bg-slate-800/80 hover:bg-brand-50 dark:hover:bg-brand-500/10 border border-slate-200 dark:border-slate-700 transition flex items-center justify-between gap-2';
      btn.innerHTML = `
        <div class="min-w-0">
          <div class="font-bold text-slate-900 dark:text-white truncate">${escapeHtml(pick.name)}</div>
          <div class="text-[10px] text-slate-500 dark:text-slate-400 truncate">${escapeHtml(pick.meta)}</div>
        </div>
        <span class="text-[10px] font-bold text-brand-600 dark:text-brand-400 shrink-0">${pick.isMatch ? 'Match' : 'Alt'} →</span>
      `;
      btn.addEventListener('click', () => {
        if (typeof pick.idx === 'number') {
          const card = document.getElementById(`resCard-${pick.idx}`);
          if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
          flyToMarkerForItem(pick.idx, true);
        }
      });
      picksWrap.appendChild(btn);
    });
    bubble.appendChild(picksWrap);
  }

  if (Array.isArray(options.quickReplies) && options.quickReplies.length) {
    const qrWrap = document.createElement('div');
    qrWrap.className = 'flex flex-wrap gap-1.5 pt-1';
    options.quickReplies.forEach((promptText) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      const isPrimaryConfirm = Boolean(options.isConfirm) && /^yes,\s*search/i.test(String(promptText));
      chip.className = isPrimaryConfirm
        ? 'px-3 py-1 rounded-full text-[11px] font-bold bg-gradient-to-r from-brand-600 to-amber-500 hover:from-brand-700 hover:to-amber-600 text-white shadow-sm transition'
        : 'px-2.5 py-1 rounded-full text-[11px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-brand-100 dark:hover:bg-brand-500/20 hover:text-brand-700 dark:hover:text-brand-300 border border-slate-200 dark:border-slate-700 transition';
      chip.textContent = promptText;
      chip.addEventListener('click', () => submitChatMessage(promptText));
      qrWrap.appendChild(chip);
    });
    bubble.appendChild(qrWrap);
  }

  wrapper.appendChild(bubble);
  chatMessagesEl.appendChild(wrapper);
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
  return wrapper;
}

export function buildGreetingState() {
  const sgHour = getSingaporeDate().getHours();
  let mealPrompt = 'Lunch';
  let timeGreeting = 'Good afternoon';
  let supperTip = 'Halal Japanese under $20';
  if (sgHour >= 5 && sgHour < 11) {
    timeGreeting = 'Good morning';
    mealPrompt = 'Breakfast / Kopi';
    supperTip = 'Breakfast cafes or kopitiam under $12';
  } else if (sgHour >= 11 && sgHour < 15) {
    timeGreeting = 'Good afternoon';
    mealPrompt = 'Lunch';
    supperTip = 'Quick Halal lunch under $15';
  } else if (sgHour >= 15 && sgHour < 17) {
    timeGreeting = 'Good afternoon';
    mealPrompt = 'Afternoon tea / Cafe';
    supperTip = 'Cozy dessert cafes under $18';
  } else if (sgHour >= 17 && sgHour < 22) {
    timeGreeting = 'Good evening';
    mealPrompt = 'Dinner';
    supperTip = 'Halal Japanese dinner under $25';
  } else {
    timeGreeting = 'Late night in SG';
    mealPrompt = 'Supper';
    supperTip = 'Late-night supper spots open now under $18';
  }

  if (state.currentUser && state.currentUser.username) {
    const prefs = state.currentUser;
    const locs = Array.isArray(prefs.location) && prefs.location.length
      ? prefs.location.join(' + ')
      : 'Singapore';
    const budget = prefs.budget_per_person != null
      ? (Number(prefs.budget_per_person) > 100 ? 'SGD $100+' : `SGD $${prefs.budget_per_person}`)
      : 'Budget not set';
    return {
      text: `${timeGreeting}, ${prefs.username}! Your saved defaults (${locs}, ${budget}) are loaded. Ready for ${mealPrompt.toLowerCase()}? Tell me what you're craving and I'll double-check before searching.`,
      quickReplies: [
        `Search near ${locs}`,
        supperTip,
        'Meet between Tampines and Jurong East',
        'At least 4.5 stars',
      ],
    };
  }

  return {
    text: `${timeGreeting}! I'm your BiteFinder assistant. Where in Singapore would you like to search for ${mealPrompt.toLowerCase()}? (You can also share your location, budget, and travel time together — I'll confirm everything with you before searching.)`,
    quickReplies: [
      'Bugis Junction',
      'Compass One',
      `${supperTip} near Bugis, 15 mins walk`,
      'Help',
    ],
  };
}

export function resetChatThread(resetFilters = false) {
  const chatMessagesEl = document.getElementById('chatMessages');
  state.onboardingActive = false;
  state.awaitingChatField = null;
  updateOnboardingProgressUI(null);

  if (resetFilters) {
    resetResultsDisplay();
    if (state.currentUser) {
      applyUserToSearchForm(state.currentUser);
    } else {
      applyFiltersToSearchForm({
        location: '',
        locations: [],
        mode: 'walk',
        traffic_aware: false,
        max_travel_minutes: null,
        max_distance_km: null,
        budget_per_person: null,
        dietary_requirements: [],
        liked_cuisines: [],
        disliked_cuisines: [],
        other_preferences: [],
      });
    }
  }

  state.chatHistory = [];
  state.chatHasUserTurn = false;
  if (chatMessagesEl) chatMessagesEl.innerHTML = '';

  const greeting = buildGreetingState();
  if (!state.currentUser) {
    state.awaitingChatField = 'location';
  }
  appendChatBubble('assistant', greeting.text, { quickReplies: greeting.quickReplies });
  renderChatFilterSummary();
  updateGuestHintBanner();
}

export function refreshGreetingIfIdle() {
  if (!state.chatHasUserTurn && !state.onboardingActive) {
    resetChatThread(false);
  } else {
    updateGuestHintBanner();
  }
}

export async function startOnboardingInChat() {
  if (!state.currentUser) return;
  const chatMessagesEl = document.getElementById('chatMessages');
  setLeftPanelMode('chat');
  state.onboardingActive = true;
  state.awaitingChatField = null;
  state.chatHistory = [];
  state.chatHasUserTurn = true;
  if (chatMessagesEl) chatMessagesEl.innerHTML = '';
  updateGuestHintBanner();

  const thinkingBubble = appendChatBubble('assistant', 'Preparing your BiteFinder profile setup...', { pending: true });
  try {
    const data = await apiJson('/api/chat', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        message: '__start_onboarding__',
        onboarding: true,
        current_filters: collectCurrentFormPayload(true),
        history: [],
      }),
    });
    if (thinkingBubble) thinkingBubble.remove();

    state.awaitingChatField = data.awaiting_field || null;
    if (data.action !== 'onboarding') {
      state.onboardingActive = false;
    }
    updateOnboardingProgressUI(data.onboarding_step, data.onboarding_total);
    if (data.action === 'reset' && state.currentUser && data.filters) {
      applyFiltersToSearchForm({
        ...data.filters,
        max_distance_km: state.currentUser.max_distance_km ?? data.filters.max_distance_km ?? null,
        max_travel_minutes: state.currentUser.max_travel_time_minutes ?? data.filters.max_travel_minutes ?? null,
      });
    } else if (data.filters) {
      const hasTravelChange = (data.changes || []).some((c) => /km|\d+\s*(?:mins?|m)\b|Walk|Drive|Transit/i.test(String(c)));
      const hasBudgetChange = (data.changes || []).some((c) => /budget|SGD\s*\$|\$\s*\d/i.test(String(c)));
      applyFiltersToSearchForm(data.filters, {
        preserveBudgetPlus: state.isBudgetPlus && !hasBudgetChange,
        preserveInactiveTravel: !hasTravelChange,
      });
    }
    appendChatBubble('assistant', data.reply, {
      quickReplies: data.quick_replies || [],
      isConfirm: data.action === 'confirm',
    });
    state.chatHistory.push({ role: 'assistant', text: data.reply });
  } catch {
    if (thinkingBubble) thinkingBubble.remove();
    state.onboardingActive = false;
    updateOnboardingProgressUI(null);
    resetChatThread(false);
  }
}

export function postChatSearchOutcome({ matches = [], alternatives = [], modelUsed = '', emptyMessage = '', errorMessage = '', fromChat = false }) {
  if (state.pendingChatSearchBubble) {
    state.pendingChatSearchBubble.remove();
    state.pendingChatSearchBubble = null;
  }
  if (errorMessage) {
    appendChatBubble('assistant', `Search hit a snag: ${errorMessage}`, {
      quickReplies: ['Retry search', 'Help'],
    });
    return;
  }
  if (emptyMessage && matches.length === 0 && alternatives.length === 0) {
    appendChatBubble('assistant', emptyMessage, {
      quickReplies: ['Rivervale Plaza', 'Jewel Changi', 'Under $40', 'Max 45 mins'],
    });
    return;
  }

  const picks = [];
  state.displayedItems.slice(0, 3).forEach((item, idx) => {
    const r = item.restaurant || {};
    const rating = getRatingValue(r);
    const mins = getTravelMinutes(r);
    const price = getPriceValue(r);
    const parts = [];
    if (rating) parts.push(`${rating.toFixed(1)}★`);
    if (mins !== null) parts.push(`${Math.round(mins)} mins`);
    if (price !== null) parts.push(`~$${Math.round(price)}`);
    if (r.halal_certification === 'official') parts.push('MUIS Halal');
    picks.push({
      idx,
      name: r.name || 'Restaurant',
      meta: parts.join(' • ') || (r.address || ''),
      isMatch: Boolean(item.isMatch),
    });
  });

  const summaryText = `Found ${matches.length} direct match${matches.length === 1 ? '' : 'es'} and ${alternatives.length} close alternative${alternatives.length === 1 ? '' : 's'}${modelUsed ? ` (ranked by ${modelUsed})` : ''}. Click a top pick below or refine your search:`;
  const followUps = ['Under $15', 'At least 4.5 stars', 'Switch to transit'];
  if (state.currentUser) followUps.push('Save to profile');

  appendChatBubble('assistant', summaryText, {
    topPicks: picks,
    quickReplies: followUps.slice(0, 4),
  });
  if (!fromChat) {
    state.chatHistory.push({ role: 'assistant', text: summaryText });
  }
}

export async function submitChatMessage(rawText) {
  const chatInput = document.getElementById('chatInput');
  const chatSendBtn = document.getElementById('chatSendBtn');
  const message = String(rawText || '').trim();
  if (!message || !chatSendBtn || chatSendBtn.disabled) return;

  setLeftPanelMode('chat');
  state.chatHasUserTurn = true;
  appendChatBubble('user', message);
  state.chatHistory.push({ role: 'user', text: message });
  if (chatInput) chatInput.value = '';

  chatSendBtn.disabled = true;
  const thinkingBubble = appendChatBubble('assistant', 'Understanding your request...', { pending: true });

  try {
    const data = await apiJson('/api/chat', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        message,
        current_filters: collectCurrentFormPayload(true),
        history: state.chatHistory.slice(-6),
        onboarding: state.onboardingActive,
        awaiting_field: state.awaitingChatField,
      }),
    });
    if (thinkingBubble) thinkingBubble.remove();

    state.awaitingChatField = data.awaiting_field || null;
    if (state.onboardingActive && data.action !== 'onboarding') {
      state.onboardingActive = false;
    }
    updateOnboardingProgressUI(
      state.onboardingActive ? data.onboarding_step : null,
      data.onboarding_total,
    );

    if (data.action === 'reset' && state.currentUser && data.filters) {
      applyFiltersToSearchForm({
        ...data.filters,
        max_distance_km: state.currentUser.max_distance_km ?? data.filters.max_distance_km ?? null,
        max_travel_minutes: state.currentUser.max_travel_time_minutes ?? data.filters.max_travel_minutes ?? null,
      });
    } else if (data.filters) {
      const hasTravelChange = (data.changes || []).some((c) => /km|\d+\s*(?:mins?|m)\b|Walk|Drive|Transit/i.test(String(c)));
      const hasBudgetChange = (data.changes || []).some((c) => /budget|SGD\s*\$|\$\s*\d/i.test(String(c)));
      applyFiltersToSearchForm(data.filters, {
        preserveBudgetPlus: state.isBudgetPlus && !hasBudgetChange,
        preserveInactiveTravel: !hasTravelChange,
      });
    }

    const shouldRunSearch = data.action === 'search';
    appendChatBubble('assistant', data.reply, {
      changes: data.changes || [],
      quickReplies: shouldRunSearch ? [] : (data.quick_replies || []),
      isConfirm: data.action === 'confirm',
    });
    state.chatHistory.push({ role: 'assistant', text: data.reply });

    if (data.saved_to_profile && state.currentUser) {
      authCallbacks.onProfileSaved();
      showToast('Preferences saved to your profile.', 'success');
    }

    if (shouldRunSearch) {
      state.pendingChatSearchBubble = appendChatBubble(
        'assistant',
        'Searching Google Places, travel routes & MUIS records...',
        { pending: true },
      );
      state.searchTriggeredFromChat = true;
      document.getElementById('searchForm')?.requestSubmit();
    }
  } catch (err) {
    if (thinkingBubble) thinkingBubble.remove();
    appendChatBubble('assistant', `Sorry — I couldn't process that right now (${err.message}).`, {
      quickReplies: ['Help'],
    });
  } finally {
    chatSendBtn.disabled = false;
  }
}

export function runChatQuickStart(promptText) {
  setLeftPanelMode('chat');
  submitChatMessage(promptText);
}

export function initChatbotControls() {
  document.getElementById('tabChatModeBtn')?.addEventListener('click', () => setLeftPanelMode('chat'));
  document.getElementById('tabFiltersModeBtn')?.addEventListener('click', () => setLeftPanelMode('filters'));
  document.getElementById('chatOpenFiltersBtn')?.addEventListener('click', () => setLeftPanelMode('filters'));
  document.getElementById('chatHelpBtn')?.addEventListener('click', () => submitChatMessage('Help'));
  document.getElementById('navChatFocusBtn')?.addEventListener('click', () => {
    setLeftPanelMode('chat');
    document.getElementById('chatbotPanel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    document.getElementById('chatInput')?.focus();
  });
  document.getElementById('chatResetBtn')?.addEventListener('click', () => resetChatThread(true));
  document.getElementById('skipOnboardingBtn')?.addEventListener('click', () => {
    resetChatThread(false);
    showToast('Profile setup skipped. You can complete it anytime in My Profile.', 'info');
  });
  document.getElementById('guestSignInCtaBtn')?.addEventListener('click', () => {
    authCallbacks.openAuthModal();
  });

  document.getElementById('chatForm')?.addEventListener('submit', (e) => {
    e.preventDefault();
    const chatInput = document.getElementById('chatInput');
    if (chatInput) submitChatMessage(chatInput.value);
  });

  resetChatThread(false);
}
