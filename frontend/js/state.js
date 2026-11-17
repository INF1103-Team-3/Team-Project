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
  'qwer', 'wert', 'qwrt', 'erty', 'tyui', 'uiop',
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

const NON_LOCATION_SLANG_WORDS = new Set([
  'lol', 'lmao', 'lmfao', 'rofl', 'wtf', 'wth', 'omg', 'omfg',
  'idk', 'imo', 'tbh', 'brb', 'yolo', 'fomo', 'bruh', 'yeet',
  'idiot', 'stupid', 'dumb', 'moron', 'retard', 'loser', 'clown',
  'trash', 'garbage', 'rubbish', 'nonsense', 'gibberish',
  'cb', 'ccb', 'knn', 'knnb', 'knnbccb', 'lampa', 'lanjiao',
  'cheebai', 'chibai', 'kanina', 'nabei', 'pukimak', 'kontol',
  'babi', 'anjing', 'bodoh', 'sial', 'cibai',
  'fuck', 'fucking', 'shit', 'bitch', 'asshole', 'dick', 'cock',
  'pussy', 'cunt', 'bastard', 'whore', 'slut',
  'test', 'testing', 'hello', 'hi', 'hey', 'bye', 'none',
  'nothing', 'anything', 'whatever', 'random', 'stuff',
  'null', 'undefined', 'nan', 'blorp', 'foobar', 'foo', 'baz', 'qwerty',
]);

const STRICT_PROFANITY_LOCATION_WORDS = new Set([
  'cb', 'ccb', 'knn', 'knnb', 'knnbccb', 'lampa', 'lanjiao',
  'cheebai', 'chibai', 'kanina', 'nabei', 'pukimak', 'kontol',
  'babi', 'anjing', 'cibai', 'fuck', 'fucking', 'shit', 'bitch',
  'asshole', 'dick', 'cunt', 'bastard', 'whore', 'slut',
]);

const ORDINAL_DIGIT_WORD_REGEX = /^\d+(?:st|nd|rd|th)$/;
const MIXED_GIBBERISH_TOKEN_REGEX = /^(?:[a-z]+\d{2,}[a-z]+|\d{2,}[a-z]{2,}\d*)$/;

export const RECOGNIZED_CUISINES = new Set([
  'chinese', 'malay', 'indian', 'peranakan', 'indonesian', 'thai',
  'vietnamese', 'filipino', 'japanese', 'korean', 'western', 'italian',
  'french', 'american', 'mexican', 'turkish', 'middle eastern',
  'mediterranean', 'fusion', 'lebanese',
  'spanish', 'greek', 'brazilian', 'ethiopian', 'german', 'british',
  'pakistani', 'bangladeshi', 'nepalese', 'sri lankan', 'cambodian',
  'laotian', 'burmese', 'taiwanese', 'singaporean',
  'portuguese', 'swiss', 'austrian', 'belgian', 'dutch', 'irish', 'scottish',
  'polish', 'russian', 'ukrainian', 'georgian', 'armenian', 'hungarian',
  'czech', 'swedish', 'norwegian', 'danish', 'finnish', 'scandinavian',
  'nordic', 'moroccan', 'tunisian', 'egyptian', 'nigerian', 'south african',
  'african', 'persian', 'iranian', 'iraqi', 'syrian', 'jordanian', 'yemeni',
  'israeli', 'arab', 'arabic', 'afghan', 'uzbek', 'tibetan', 'mongolian',
  'hong kong', 'macanese', 'cantonese', 'sichuan', 'szechuan', 'hunan',
  'shanghainese', 'beijing', 'teochew', 'hokkien', 'hakka', 'hainanese',
  'fujian', 'dongbei', 'xinjiang', 'uyghur', 'okinawan', 'kyushu', 'hokkaido',
  'north indian', 'south indian', 'punjabi', 'gujarati', 'kerala',
  'chettinad', 'kashmiri', 'bengali', 'goan', 'hyderabadi', 'mughlai',
  'javanese', 'padang', 'sundanese', 'balinese', 'nonya', 'nyonya',
  'eurasian', 'malaysian', 'asian', 'southeast asian', 'east asian',
  'south asian', 'european', 'latin', 'latin american', 'south american',
  'caribbean', 'jamaican', 'cuban', 'peruvian', 'argentinian', 'argentine',
  'colombian', 'chilean', 'australian', 'aussie', 'new zealand', 'kiwi',
  'canadian', 'hawaiian', 'cajun', 'creole', 'tex mex', 'tex-mex',
  'southern', 'soul food', 'seafood', 'fast food', 'hawker', 'zi char',
  'tze char', 'kopitiam', 'mamak', 'local', 'ramen', 'sushi', 'sashimi',
  'izakaya', 'udon', 'soba', 'tonkatsu', 'katsu', 'tempura', 'yakitori',
  'teppanyaki', 'yakiniku', 'donburi', 'omakase', 'matcha', 'dim sum',
  'yum cha', 'hotpot', 'hot pot', 'steamboat', 'mala', 'mala xiang guo',
  'bbq', 'kbbq', 'korean bbq', 'charcoal bbq', 'mookata', 'lok lok',
  'satay', 'laksa', 'chicken rice', 'bak kut teh', 'nasi lemak',
  'nasi padang', 'briyani', 'biryani', 'prata', 'roti prata', 'murtabak',
  'thosai', 'dosai', 'dosa', 'tandoori', 'naan', 'curry', 'banh mi', 'pho',
  'pad thai', 'tom yum', 'som tam', 'pizza', 'pasta', 'burger', 'burgers',
  'steak', 'steakhouse', 'grill', 'wings', 'fried chicken', 'sandwich',
  'sandwiches', 'wraps', 'salad', 'salads', 'poke', 'acai', 'tapas',
  'paella', 'risotto', 'gelato', 'ice cream', 'bakery', 'cafe', 'cafes',
  'coffee', 'brunch', 'breakfast', 'dessert', 'desserts', 'pastry',
  'pastries', 'cake', 'cakes', 'boba', 'bubble tea', 'noodle', 'noodles',
  'wanton mee', 'bak chor mee', 'char kway teow', 'hokkien mee',
  'roast meat', 'duck', 'roast duck', 'porridge', 'congee', 'soup',
  'dumpling', 'dumplings', 'gyoza', 'rice bowl', 'bento', 'tacos', 'burrito',
  'burritos', 'quesadilla', 'kebab', 'kebabs', 'shawarma', 'falafel',
  'hummus', 'gyros', 'vegan', 'vegetarian', 'plant based', 'plant-based',
  'healthy', 'organic', 'buffet', 'fine dining', 'bistro', 'bar', 'pub',
  'gastropub', 'supper', 'street food', 'comfort food', 'home style',
  'homestyle',
]);

const CUISINE_ACRONYMS = new Set(['bbq', 'kbbq']);
const INVALID_CUISINE_WORDS = new Set([
  'none', 'any', 'all', 'nothing', 'something', 'anything', 'whatever',
  'random', 'stuff', 'thing', 'things', 'test', 'testing', 'hello', 'hi',
  'hey', 'bye', 'ok', 'okay', 'yes', 'no', 'maybe', 'null', 'undefined',
  'nan', 'blorp', 'foobar', 'foo', 'bar', 'baz', 'xyz', 'abc', 'qwerty',
  'food', 'foods', 'cuisine', 'cuisines', 'restaurant', 'restaurants',
  'meal', 'meals', 'dish', 'dishes', 'eat', 'eating',
  'lol', 'lmao', 'lmfao', 'rofl', 'wtf', 'wth', 'omg', 'omfg', 'idk',
  'imo', 'tbh', 'brb', 'yolo', 'fomo', 'uwu', 'owo', 'sus', 'yeet',
  'bruh', 'bro', 'sis', 'idiot', 'stupid', 'dumb', 'moron', 'retard',
  'loser', 'clown', 'trash', 'garbage', 'rubbish', 'nonsense', 'gibberish',
  'poop', 'fart', 'cb', 'ccb', 'knn', 'knnb', 'knnbccb', 'lampa',
  'lanjiao', 'lj', 'cheebai', 'chibai', 'kanina', 'nabei', 'limpeh',
  'pukimak', 'kontol', 'babi', 'anjing', 'bodoh', 'sial', 'cibai',
  'fuck', 'fucking', 'shit', 'bitch', 'ass', 'asshole', 'dick', 'cock',
  'pussy', 'cunt', 'bastard', 'whore', 'slut', 'damn', 'crap', 'hell',
  'suck', 'porn', 'sex',
]);

export function normalizeCuisineToken(raw) {
  const text = String(raw || '').replace(/\s+/g, ' ').trim().toLowerCase();
  if (!text) return '';
  const stripped = text.replace(/\s+cuisines?$/i, '').trim();
  return stripped || text;
}

export function isRecognizedCuisine(raw) {
  return RECOGNIZED_CUISINES.has(normalizeCuisineToken(raw));
}

export function validateCuisineSyntax(raw, label = 'Cuisine') {
  const input = String(raw || '').trim();
  if (!input) return { err: '', items: [], unknownItems: [] };
  const parts = input.split(',');
  const items = [];
  const unknownItems = [];
  for (const part of parts) {
    const cleaned = part.trim();
    if (!cleaned) continue;
    if (/[\x00-\x1f]/.test(part)) {
      return { err: `${label} contains invalid control characters.`, items: [], unknownItems: [] };
    }
    if (cleaned.length > 40) {
      return { err: `${label}: '${cleaned}' is too long (maximum 40 characters).`, items: [], unknownItems: [] };
    }
    const token = normalizeCuisineToken(cleaned);
    if (!token || ['none', 'any', 'any cuisine', 'all'].includes(token)) {
      return {
        err: `${label}: enter a real cuisine or leave it blank (e.g. Japanese, Spanish, Seafood).`,
        items: [],
        unknownItems: [],
      };
    }
    if (token === 'halal') {
      return {
        err: `${label}: Halal is a dietary requirement — use the MUIS Halal option instead.`,
        items: [],
        unknownItems: [],
      };
    }
    if (!/^[a-z]+(?:[ '\-&/][a-z]+)*$/.test(token)) {
      return {
        err: `${label}: '${cleaned}' is not a valid cuisine name (letters only, e.g. Japanese, Spanish, Dim Sum).`,
        items: [],
        unknownItems: [],
      };
    }
    const words = token.match(/[a-z]+/g) || [];
    const totalLetters = words.reduce((sum, w) => sum + w.length, 0);
    if (!words.length || words.length > 4 || totalLetters < 3) {
      return {
        err: `${label}: '${cleaned}' is not a valid cuisine name (e.g. Japanese, Spanish, Seafood).`,
        items: [],
        unknownItems: [],
      };
    }
    const recognized = RECOGNIZED_CUISINES.has(token);
    if (INVALID_CUISINE_WORDS.has(token) || (!recognized && words.some((w) => INVALID_CUISINE_WORDS.has(w)))) {
      return {
        err: `${label}: '${cleaned}' is not a valid cuisine name (e.g. Japanese, Spanish, Seafood).`,
        items: [],
        unknownItems: [],
      };
    }
    if (!recognized) {
      for (const word of words) {
        if (
          /(.)\1\1/.test(word)
          || WISH_KEYBOARD_MASH.some((seq) => word.includes(seq))
          || (word.length >= 3 && !CUISINE_ACRONYMS.has(word) && !/[aeiouy]/.test(word))
          || /[bcdfghjklmnpqrstvwxz]{6,}/.test(word)
        ) {
          return {
            err: `${label}: '${cleaned}' is not a valid cuisine name (e.g. Japanese, Spanish, Seafood).`,
            items: [],
            unknownItems: [],
          };
        }
      }
    }
    if (!items.includes(token)) {
      items.push(token);
      if (!recognized) unknownItems.push(token);
    }
  }
  return { err: '', items, unknownItems };
}

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
    if (STRICT_PROFANITY_LOCATION_WORDS.has(tok)) {
      return `'${clean}' does not look like a real Singapore location (e.g. Bugis, Compass One, 545078).`;
    }
    if (
      !tok.startsWith('blk')
      && !ORDINAL_DIGIT_WORD_REGEX.test(tok)
      && MIXED_GIBBERISH_TOKEN_REGEX.test(tok)
    ) {
      return `'${clean}' does not look like a real Singapore location (e.g. Bugis, Compass One, 545078).`;
    }
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
  const contentTokens = tokens.filter((t) => t !== 'singapore' && t !== 'sg');
  const checkTokens = contentTokens.length ? contentTokens : tokens;
  if (checkTokens.length <= 2 && checkTokens.every((t) => NON_LOCATION_SLANG_WORDS.has(t))) {
    return `'${clean}' does not look like a real Singapore location (e.g. Bugis, Compass One, 545078).`;
  }
  return '';
}
