/** Offline ES-module contracts. Run with Node 22+; see tests/README.md. */
import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import * as filters from '../../frontend/js/filters.js?v=20261116-1';
import * as results from '../../frontend/js/results.js?v=20261116-1';
import { state } from '../../frontend/js/state.js?v=20261116-1';

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

test('reset clears shared UI refresh state without an HTTP request', () => {
  results.resetResultsDisplay();
  assert.equal(state.lastSearchPayload, null);
  assert.deepEqual(state.refreshSeenRestaurants, []);
  assert.equal(state.refreshSeenKeys.size, 0);
  assert.deepEqual(requests, []);
});
