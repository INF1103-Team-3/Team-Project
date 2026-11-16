import { refreshIcons, THEME_KEY, updateThemeUI } from './state.js?v=20261116-4';
import { initModalAccessibility } from './modals.js?v=20261116-4';
import { initMapControls, refreshMapTheme, setMapFormatters } from './map.js?v=20261116-4';
import { initCompareControls } from './compare.js?v=20261116-4';
import {
  formatHours,
  getTravelMinutes,
  initResultsControls,
  setFavoriteToggleHandler,
  setRefreshResultsHandler,
} from './results.js?v=20261116-4';
import { initFiltersControls, refreshSearchResults, setFilterChatCallbacks } from './filters.js?v=20261117-2';
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
} from './chatbot.js?v=20261117-2';
import {
  checkSession,
  initAuthAndModals,
  openAuthModalWithNotice,
  setAuthChatCallbacks,
  toggleFavoriteByIndex,
} from './auth.js?v=20261117-2';

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
  setRefreshResultsHandler(refreshSearchResults);
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
