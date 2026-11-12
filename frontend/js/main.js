import { refreshIcons, THEME_KEY, updateThemeUI } from './state.js';
import { initModalAccessibility } from './modals.js';
import { initMapControls, refreshMapTheme, setMapFormatters } from './map.js';
import { initCompareControls } from './compare.js';
import {
  formatHours,
  getTravelMinutes,
  initResultsControls,
  setFavoriteToggleHandler,
} from './results.js';
import { initFiltersControls, setFilterChatCallbacks } from './filters.js';
import {
  initChatbotControls,
  postChatSearchOutcome,
  refreshGreetingIfIdle,
  renderChatFilterSummary,
  resetChatThread,
  runChatQuickStart,
  setChatbotAuthCallbacks,
  startOnboardingInChat,
  updateGuestHintBanner,
} from './chatbot.js';
import {
  checkSession,
  initAuthAndModals,
  openAuthModalWithNotice,
  setAuthChatCallbacks,
  toggleFavoriteByIndex,
} from './auth.js';

function initThemeToggle() {
  updateThemeUI();
  document.getElementById('themeToggleBtn')?.addEventListener('click', () => {
    const isDark = document.documentElement.classList.toggle('dark');
    try {
      localStorage.setItem(THEME_KEY, isDark ? 'dark' : 'light');
    } catch { }
    updateThemeUI();
    refreshMapTheme();
  });
}

function initQuickStartCards() {
  document.querySelectorAll('.quick-start-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const prompt = btn.dataset.prompt || '';
      if (prompt) runChatQuickStart(prompt);
    });
  });
}

function bootstrap() {
  setMapFormatters({ formatHours, getTravelMinutes });
  setFavoriteToggleHandler(toggleFavoriteByIndex);
  setFilterChatCallbacks({
    renderSummary: renderChatFilterSummary,
    refreshGreetingIfIdle,
    postSearchOutcome: postChatSearchOutcome,
  });
  setChatbotAuthCallbacks({
    onProfileSaved: () => checkSession(false),
    openAuthModal: () => openAuthModalWithNotice(''),
  });
  setAuthChatCallbacks({
    startOnboardingInChat,
    refreshGreetingIfIdle,
    resetChatThread,
    updateGuestHintBanner,
  });

  initThemeToggle();
  initModalAccessibility([
    'authModal',
    'profileModal',
    'favoritesModal',
    'historyModal',
    'routeModal',
    'compareModal',
  ]);
  initMapControls();
  initCompareControls();
  initResultsControls();
  initFiltersControls();
  initChatbotControls();
  initAuthAndModals();
  initQuickStartCards();

  checkSession(true);
  refreshIcons();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap);
} else {
  bootstrap();
}
