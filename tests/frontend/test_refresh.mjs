/** Offline ES-module contracts. Run with Node 22+; see tests/README.md. */
import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import { readFileSync } from 'node:fs';

// Resolve the actual browser module URLs, including cache versions. Hardcoded
// queries create a second state singleton when the application version changes.
const mainSource = readFileSync(new URL('../../frontend/js/main.js', import.meta.url), 'utf8');
function importApplicationModule(name) {
  const specifier = mainSource.match(new RegExp(`['"](\\./${name}\\.js[^'"]*)['"]`))?.[1];
  assert.ok(specifier, `main.js must import ${name}.js`);
  return import(new URL(`../../frontend/js/${specifier.slice(2)}`, import.meta.url));
}
const [filters, results, stateModule] = await Promise.all([
  importApplicationModule('filters'),
  importApplicationModule('results'),
  importApplicationModule('state'),
]);
const { parseProfileLocationsInput, state, validateLocationSyntax } = stateModule;

const elements = new Map();
const requests = [];
let searchResponse;
let searchStatus;

function element() {
  return {
    textContent: '', innerHTML: '', disabled: false,
    classList: { add() {}, remove() {}, toggle() {} },
    listeners: new Map(),
    addEventListener(event, callback) { this.listeners.set(event, callback); },
  };
}

function item(id) {
  return { restaurant: { google_place_id: id, name: id, address: '1 Road' } };
}

beforeEach(() => {
  elements.clear();
  requests.length = 0;
  searchStatus = 200;
  searchResponse = { matches: [], alternatives: [], exhausted_previous: true };
  globalThis.window = {};
  globalThis.document = {
    getElementById: id => elements.get(id) || null,
    querySelectorAll: () => [],
  };
  globalThis.fetch = async (url, options) => {
    assert.match(url, /^\/api\//, 'frontend must call the BIS HTTP boundary');
    requests.push({ url, options });
    const status = url === '/api/search' ? searchStatus : 200;
    const body = url === '/api/search' ? searchResponse : { active_model: 'fixture' };
    return { ok: status < 400, status, text: async () => JSON.stringify(body) };
  };
  results.resetResultsDisplay();
  state.lastSearchPayload = {
    location: 'Orchard', locations: ['Orchard'], mode: 'walk',
    confirmation_token: 'already-consumed', confirm_only: true,
  };
  state.lastMatches = [item('seen')];
  state.refreshSeenRestaurants = [item('seen').restaurant];
  state.refreshSeenKeys.add('seen');
  elements.set('refreshResultsBtn', element());
});

test('refresh exports capabilities while implementation helpers stay module-local', () => {
  assert.equal(typeof filters.refreshSearchResults, 'function');
  assert.equal(typeof results.setRefreshResultsHandler, 'function');
  for (const name of ['executeSearchRequest', 'cloneSearchPayload',
    'appendRefreshSeen', 'filterUnseenItems', 'resetRefreshAndSearch']) {
    assert.equal(Object.hasOwn(filters, name), false, name);
  }
});

test('refresh sends a bounded seen list through BIS and removes duplicates', async () => {
  searchResponse = {
    matches: [item('seen'), item('fresh')],
    alternatives: [item('fresh'), item('alternative')],
    exhausted_previous: false,
  };
  await filters.refreshSearchResults();
  const payload = JSON.parse(requests.find(r => r.url === '/api/search').options.body);
  assert.equal(payload.strict_exclude, true);
  assert.deepEqual(payload.previous_restaurants, [item('seen').restaurant]);
  assert.equal(Object.hasOwn(payload, 'confirmation_token'), false);
  assert.equal(Object.hasOwn(payload, 'confirm_only'), false);
  assert.deepEqual(state.lastMatches.map(r => r.restaurant.google_place_id), ['fresh']);
  assert.deepEqual(state.lastAlternatives.map(r => r.restaurant.google_place_id), ['alternative']);
  assert.deepEqual([...state.refreshSeenKeys], ['seen', 'fresh', 'alternative']);
  assert.equal(elements.get('refreshResultsBtn').disabled, false);
});

test('refresh limits the request to 200 previous venues', async () => {
  state.refreshSeenRestaurants = Array.from({ length: 205 }, (_, n) => item(`id-${n}`).restaurant);
  await filters.refreshSearchResults();
  const payload = JSON.parse(requests.find(r => r.url === '/api/search').options.body);
  assert.equal(payload.previous_restaurants.length, 200);
  assert.equal(payload.previous_restaurants[0].google_place_id, 'id-5');
});

test('exhaustion shows the reset action and preserves seen history', async () => {
  elements.set('resultsList', element());
  elements.set('resetRefreshSeenBtn', element());
  await filters.refreshSearchResults();
  assert.match(elements.get('resultsList').innerHTML, /All Matching Restaurants Already Shown/);
  assert.equal(typeof elements.get('resetRefreshSeenBtn').listeners.get('click'), 'function');
  assert.deepEqual(state.refreshSeenRestaurants, [item('seen').restaurant]);
  assert.deepEqual(state.lastMatches, []);
});

test('provider outage keeps the previous search usable and restores controls', async () => {
  searchStatus = 503;
  searchResponse = { detail: 'Restaurant search is unavailable.' };
  await filters.refreshSearchResults();
  assert.deepEqual(state.refreshSeenRestaurants, [item('seen').restaurant]);
  assert.equal(state.lastSearchPayload.location, 'Orchard');
  assert.equal(elements.get('refreshResultsBtn').disabled, false);
});

test('cancel aborts the browser request and restores previous results and controls', async () => {
  const previous = state.lastMatches;
  let started;
  const requestStarted = new Promise((resolve) => { started = resolve; });
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url.includes('active-model')) {
      return { ok: true, json: async () => ({ active_model: 'fixture' }) };
    }
    return new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        reject(new DOMException('Cancelled', 'AbortError'));
      }, { once: true });
      started();
    });
  };
  const pending = filters.refreshSearchResults();
  await requestStarted;
  filters.cancelActiveSearch();
  await pending;
  assert.equal(requests.find((r) => r.url === '/api/search').options.signal.aborted, true);
  assert.deepEqual(state.lastMatches, previous);
  assert.equal(elements.get('refreshResultsBtn').disabled, false);
  assert.deepEqual(state.refreshSeenRestaurants, [item('seen').restaurant]);
});

test('reset clears shared UI refresh state without an HTTP request', () => {
  results.resetResultsDisplay();
  assert.equal(state.lastSearchPayload, null);
  assert.deepEqual(state.refreshSeenRestaurants, []);
  assert.equal(state.refreshSeenKeys.size, 0);
  assert.deepEqual(requests, []);
});

test('location syntax validator and profile parser allow valid SG locations and block gibberish', () => {
  for (const good of ['Bugis', 'Compass One', '545078', 'Singapore 828761', '1.352, 103.944', 'Liberty St', 'NUS', 'T2']) {
    assert.equal(validateLocationSyntax(good), '', `expected '${good}' to pass`);
  }
  for (const bad of ['', '   ', 'asdfghjkl', 'qwrty', '12345', '999999', '000000', 'Singapore', 'xx', 'zzzzzz', '1.90, 103.80']) {
    assert.notEqual(validateLocationSyntax(bad), '', `expected '${bad}' to fail`);
  }
  assert.deepEqual(parseProfileLocationsInput('1.352, 103.944, Bugis'), ['1.352, 103.944', 'Bugis']);
  assert.deepEqual(parseProfileLocationsInput('Compass One, Tampines'), ['Compass One', 'Tampines']);
});
