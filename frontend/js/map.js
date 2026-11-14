import { escapeHtml, getPlaceKey, refreshIcons, state } from './state.js';
import { openModal, closeModal } from './modals.js';
import { apiJson } from './api.js';
import {
  buildPinMarkerIcon,
  buildPolylineOptions,
  GOOGLE_MAP_DARK_STYLES,
  GOOGLE_MAP_LIGHT_STYLES,
} from './map_styles.js';

let activeEngine = null; // 'google' | 'leaflet' | null
let mapConfigPromise = null;
let googleSdkPromise = null;
let googleAuthFailed = false;

let googleMap = null;
let googleInfoWindow = null;
let googleMarkersLayer = [];

let leafletMap = null;
let leafletTileLayer = null;
let leafletMarkersLayer = null;

let activeRouteLayers = [];
let itemMarkers = [];
let mapBoundsPoints = [];
let lastRenderedItems = [];
let lastOriginSignature = '';
let selectedRouteTarget = null;
let mapRenderGeneration = 0;
let activeRouteRequestId = 0;
let activePopupSeq = 0;

const routeCache = new Map();
const routeInflight = new Map();
const photoCache = new Map();
const photoInflight = new Map();
const MAX_CACHED_PHOTOS = 100;

let formatHoursFn = () => '';
let getTravelMinutesFn = () => null;

export function setMapFormatters({ formatHours, getTravelMinutes }) {
  if (typeof formatHours === 'function') formatHoursFn = formatHours;
  if (typeof getTravelMinutes === 'function') getTravelMinutesFn = getTravelMinutes;
}

export function getTileUrl() {
  const isDark = document.documentElement.classList.contains('dark');
  return isDark
    ? 'https://www.onemap.gov.sg/maps/tiles/Night/{z}/{x}/{y}.png'
    : 'https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png';
}

function getEffectiveRouteContext(customOrigin = null) {
  const mode = state.activeSearchMode || state.currentMode || 'walk';
  const trafficCheck = document.getElementById('trafficAwareCheck');
  const trafficAware = mode === 'drive' && Boolean(trafficCheck && trafficCheck.checked);
  const origin = customOrigin || state.lastOrigin;
  return { origin, mode, trafficAware };
}

function getOriginSignature() {
  const o = state.lastOrigin;
  if (!o || typeof o.latitude !== 'number' || typeof o.longitude !== 'number') return '';
  const extras = (state.lastInputOrigins || [])
    .map((p) => `${p.latitude?.toFixed?.(5) ?? ''},${p.longitude?.toFixed?.(5) ?? ''}`)
    .join(';');
  return `${o.latitude.toFixed(5)},${o.longitude.toFixed(5)}|${extras}`;
}

function getRouteCacheKey(origin, restaurant, mode, trafficAware) {
  return [
    Number(origin.latitude).toFixed(6),
    Number(origin.longitude).toFixed(6),
    Number(restaurant.lat).toFixed(6),
    Number(restaurant.lng).toFixed(6),
    mode,
    trafficAware ? '1' : '0',
  ].join('|');
}

function setMapRouteStatus(text = '') {
  const el = document.getElementById('mapRouteStatus');
  if (!el) return;
  if (!text) {
    el.classList.add('hidden');
    el.textContent = '';
    return;
  }
  el.textContent = text;
  el.classList.remove('hidden');
}

function formatModeStatusLabel(mode, route) {
  const name = mode === 'drive' ? 'Drive' : mode === 'transit' ? 'Transit' : 'Walk';
  const metrics = [];
  if (route?.duration_min !== undefined) metrics.push(`${route.duration_min} mins`);
  if (route?.distance_m !== undefined) {
    metrics.push(route.distance_m >= 1000
      ? `${(route.distance_m / 1000).toFixed(2)} km`
      : `${route.distance_m} m`);
  }
  const detail = metrics.length ? ` (${metrics.join(' · ')})` : '';
  if (mode === 'transit') return `Google Transit path${detail} — dotted: walk`;
  return `Google ${name} path${detail}`;
}

async function fetchMapConfig() {
  if (!mapConfigPromise) {
    mapConfigPromise = apiJson('/api/map-config').catch(() => ({
      provider: 'leaflet',
      google_maps_api_key: '',
    }));
  }
  return mapConfigPromise;
}

function teardownMapEngines() {
  clearRouteLines();
  clearAllMarkers();
  if (leafletMap) {
    leafletMap.remove();
    leafletMap = null;
    leafletTileLayer = null;
    leafletMarkersLayer = null;
  }
  if (googleInfoWindow) {
    googleInfoWindow.close();
    googleInfoWindow = null;
  }
  googleMap = null;
  const mapEl = document.getElementById('resultsMap');
  if (mapEl) mapEl.innerHTML = '';
}

function loadGoogleMapsSdk(apiKey) {
  if (window.google?.maps?.Map) return Promise.resolve(true);
  if (googleAuthFailed || !apiKey) return Promise.resolve(false);
  if (googleSdkPromise) return googleSdkPromise;

  googleSdkPromise = new Promise((resolve) => {
    const callbackName = '__bfInitGoogleMapsSdk';
    let settled = false;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      delete window[callbackName];
      if (!ok) googleSdkPromise = null;
      resolve(ok);
    };

    const previousAuthHandler = window.gm_authFailure;
    window.gm_authFailure = () => {
      googleAuthFailed = true;
      if (typeof previousAuthHandler === 'function') {
        try { previousAuthHandler(); } catch { }
      }
      if (activeEngine === 'google') {
        activeEngine = 'leaflet';
        teardownMapEngines();
        if (lastRenderedItems.length > 0) {
          updateInteractiveMap(lastRenderedItems);
        }
      }
      finish(false);
    };

    window[callbackName] = () => finish(Boolean(window.google?.maps?.Map));
    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&v=weekly&callback=${callbackName}`;
    script.async = true;
    script.defer = true;
    script.onerror = () => finish(false);
    document.head.appendChild(script);

    setTimeout(() => {
      if (!settled) finish(Boolean(window.google?.maps?.Map));
    }, 10000);
  });

  return googleSdkPromise;
}

async function ensureMapEngine() {
  if (activeEngine === 'google' && !googleAuthFailed && window.google?.maps?.Map) {
    return 'google';
  }
  if (activeEngine === 'leaflet') {
    return window.L ? 'leaflet' : null;
  }

  const cfg = await fetchMapConfig();
  if (cfg?.provider === 'google' && cfg.google_maps_api_key && !googleAuthFailed) {
    const loaded = await loadGoogleMapsSdk(cfg.google_maps_api_key);
    if (loaded && !googleAuthFailed) {
      activeEngine = 'google';
      return 'google';
    }
  }

  if (window.L) {
    activeEngine = 'leaflet';
    return 'leaflet';
  }
  return null;
}

export function refreshMapTheme() {
  const isDark = document.documentElement.classList.contains('dark');
  if (googleMap) {
    googleMap.setOptions({ styles: isDark ? GOOGLE_MAP_DARK_STYLES : GOOGLE_MAP_LIGHT_STYLES });
  }
  if (leafletMap && leafletTileLayer) {
    leafletTileLayer.setUrl(getTileUrl());
  }
}

function clearRouteLines() {
  activeRouteLayers.forEach((layer) => {
    if (typeof layer.setMap === 'function') {
      layer.setMap(null);
    } else if (leafletMap && typeof leafletMap.removeLayer === 'function') {
      leafletMap.removeLayer(layer);
    }
  });
  activeRouteLayers = [];
}

function clearAllMarkers() {
  if (googleInfoWindow) googleInfoWindow.close();
  googleMarkersLayer.forEach((entry) => {
    if (typeof entry.setMap === 'function') entry.setMap(null);
  });
  googleMarkersLayer = [];
  if (leafletMarkersLayer) leafletMarkersLayer.clearLayers();
  itemMarkers = [];
  mapBoundsPoints = [];
}

async function fetchRouteForOrigin(origin, restaurant, mode, trafficAware) {
  const cacheKey = getRouteCacheKey(origin, restaurant, mode, trafficAware);
  if (routeCache.has(cacheKey)) {
    return routeCache.get(cacheKey);
  }
  if (routeInflight.has(cacheKey)) {
    return routeInflight.get(cacheKey);
  }

  const reqPromise = apiJson('/api/route', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      origin_lat: origin.latitude,
      origin_lng: origin.longitude,
      dest_lat: restaurant.lat,
      dest_lng: restaurant.lng,
      name: restaurant.name || 'Restaurant',
      mode,
      traffic_aware: trafficAware,
    }),
  }).then((data) => {
    routeCache.set(cacheKey, data);
    routeInflight.delete(cacheKey);
    return data;
  }).catch((err) => {
    routeInflight.delete(cacheKey);
    throw err;
  });

  routeInflight.set(cacheKey, reqPromise);
  return reqPromise;
}

function drawStraightLine(origin, restaurant) {
  clearRouteLines();
  if (activeEngine === 'google' && googleMap && window.google?.maps) {
    const gmaps = window.google.maps;
    const path = [
      { lat: origin.latitude, lng: origin.longitude },
      { lat: restaurant.lat, lng: restaurant.lng },
    ];
    const poly = new gmaps.Polyline(buildPolylineOptions(gmaps, 'estimate', path));
    poly.setMap(googleMap);
    activeRouteLayers.push(poly);
    return;
  }
  if (activeEngine === 'leaflet' && leafletMap && window.L) {
    const poly = window.L.polyline(
      [[origin.latitude, origin.longitude], [restaurant.lat, restaurant.lng]],
      { color: '#ea580c', weight: 4, dashArray: '8, 8', opacity: 0.9 },
    ).addTo(leafletMap);
    activeRouteLayers.push(poly);
  }
}

function drawGoogleRouteSegments(route, fallbackMode) {
  if (!googleMap || !window.google?.maps) return false;
  const gmaps = window.google.maps;
  const rawSegments = Array.isArray(route?.segments) && route.segments.length > 0
    ? route.segments
    : (Array.isArray(route?.path) && route.path.length > 1
      ? [{ mode: fallbackMode, path: route.path }]
      : []);

  const validSegments = rawSegments.filter((seg) => Array.isArray(seg?.path) && seg.path.length >= 2);
  if (validSegments.length === 0) return false;

  clearRouteLines();
  validSegments.forEach((seg) => {
    const coords = seg.path.map(([lat, lng]) => ({ lat, lng }));
    const poly = new gmaps.Polyline(
      buildPolylineOptions(gmaps, seg.mode || fallbackMode, coords),
    );
    poly.setMap(googleMap);
    activeRouteLayers.push(poly);
  });
  return true;
}

async function drawRouteForRestaurant(r, customOrigin = null, preloadedData = null) {
  const { origin, mode, trafficAware } = getEffectiveRouteContext(customOrigin);
  if (!origin || typeof r?.lat !== 'number' || typeof r?.lng !== 'number') return;

  selectedRouteTarget = { placeKey: getPlaceKey(r), customOrigin };
  const requestId = ++activeRouteRequestId;
  drawStraightLine(origin, r);

  if (activeEngine !== 'google' || !googleMap) {
    setMapRouteStatus('Straight-line preview');
    return;
  }

  if (!preloadedData) {
    setMapRouteStatus(`Loading Google ${mode} path...`);
  }

  try {
    const data = preloadedData || await fetchRouteForOrigin(origin, r, mode, trafficAware);
    if (requestId !== activeRouteRequestId || activeEngine !== 'google' || !googleMap) return;
    if (data?.route && drawGoogleRouteSegments(data.route, mode)) {
      setMapRouteStatus(formatModeStatusLabel(mode, data.route));
      return;
    }
    setMapRouteStatus('Straight-line estimate (live route unavailable)');
  } catch {
    if (requestId !== activeRouteRequestId) return;
    setMapRouteStatus('Straight-line estimate (live route unavailable)');
  }
}

export function drawOriginToRestaurantLine(r, customOrigin = null) {
  void drawRouteForRestaurant(r, customOrigin);
}

export function highlightMapPin(idx, active) {
  const entry = itemMarkers[idx];
  if (!entry) return;
  if (entry.kind === 'google' && window.google?.maps) {
    entry.marker.setIcon(buildPinMarkerIcon(window.google.maps, {
      color: entry.color,
      scale: active ? 16 : 13,
      strokeWeight: active ? 3 : 2,
    }));
    entry.marker.setZIndex(active ? 1200 : idx + 10);
    return;
  }
  if (entry.kind === 'leaflet') {
    const el = entry.marker.getElement();
    if (!el) return;
    const pin = el.querySelector('.bf-pin');
    if (pin) pin.classList.toggle('bf-pin-hovered', Boolean(active));
    if (typeof entry.marker.setZIndexOffset === 'function') {
      entry.marker.setZIndexOffset(active ? 1200 : 0);
    }
  }
}

function getPlacePhotoId(restaurant) {
  return String(restaurant?.google_place_id || restaurant?.place_id || '').trim();
}

function rememberCachedPhoto(placeId, entry) {
  if (!photoCache.has(placeId) && photoCache.size >= MAX_CACHED_PHOTOS) {
    const oldestKey = photoCache.keys().next().value;
    if (oldestKey !== undefined) {
      const oldest = photoCache.get(oldestKey);
      photoCache.delete(oldestKey);
      if (oldest?.objectUrl) URL.revokeObjectURL(oldest.objectUrl);
    }
  }
  photoCache.set(placeId, entry);
  return entry;
}

function fetchPlacePhoto(placeId) {
  if (photoCache.has(placeId)) return Promise.resolve(photoCache.get(placeId));
  if (photoInflight.has(placeId)) return photoInflight.get(placeId);

  const req = fetch(`/api/places/${encodeURIComponent(placeId)}/photo`)
    .then(async (res) => {
      if (res.status === 404) return rememberCachedPhoto(placeId, { status: 'none' });
      if (!res.ok) return { status: 'error' };
      const blob = await res.blob();
      if (!blob || !blob.size || !String(blob.type || '').startsWith('image/')) {
        return rememberCachedPhoto(placeId, { status: 'none' });
      }
      const rawAuthor = res.headers.get('X-Photo-Author') || '';
      let author = '';
      if (rawAuthor) {
        try {
          author = decodeURIComponent(rawAuthor);
        } catch {
          author = rawAuthor;
        }
      }
      return rememberCachedPhoto(placeId, {
        status: 'ok',
        objectUrl: URL.createObjectURL(blob),
        author,
      });
    })
    .catch(() => ({ status: 'error' }))
    .finally(() => {
      photoInflight.delete(placeId);
    });

  photoInflight.set(placeId, req);
  return req;
}

function applyPhotoToWrap(wrap, result) {
  if (!wrap) return;
  const img = wrap.querySelector('.bf-iw-photo-img');
  const credit = wrap.querySelector('.bf-iw-photo-credit');
  if (result?.status === 'ok' && result.objectUrl && img) {
    img.src = result.objectUrl;
    img.classList.remove('hidden');
    wrap.classList.remove('bf-iw-photo-loading');
    if (credit) {
      if (result.author) {
        credit.textContent = `Photo: ${result.author}`;
        credit.classList.remove('hidden');
      } else {
        credit.textContent = '';
        credit.classList.add('hidden');
      }
    }
    return;
  }
  wrap.remove();
}

function hydratePopupPhoto(container, restaurant, popupToken) {
  const wrap = container?.querySelector('[data-photo-place-id]');
  if (!wrap) return;
  const placeId = getPlacePhotoId(restaurant);
  if (!placeId) {
    wrap.remove();
    return;
  }
  const cached = photoCache.get(placeId);
  if (cached) {
    applyPhotoToWrap(wrap, cached);
    return;
  }
  fetchPlacePhoto(placeId).then((res) => {
    if (popupToken !== activePopupSeq) return;
    applyPhotoToWrap(wrap, res);
  });
}

function createPopupElement(html) {
  const holder = document.createElement('div');
  holder.innerHTML = html.trim();
  return holder.firstElementChild || holder;
}

function openMarkerPopup(entry, r) {
  if (!entry) return;
  if (entry.kind === 'google' && googleMap && googleInfoWindow) {
    const popupToken = ++activePopupSeq;
    const popupHtml = buildRestaurantPopupHtml(entry.item, entry.idx);
    const popupEl = createPopupElement(popupHtml);
    googleInfoWindow.setContent(popupEl);
    googleInfoWindow.open({ map: googleMap, anchor: entry.marker });
    hydratePopupPhoto(popupEl, r, popupToken);
    return;
  }
  if (entry.kind === 'leaflet') {
    entry.marker.openPopup();
  }
  void r;
}

export function flyToMarkerForItem(idx, openPopup = true) {
  const item = state.displayedItems[idx];
  const entry = itemMarkers[idx];
  if (!item || !entry) return;
  const r = item.restaurant || {};
  if (typeof r.lat !== 'number' || typeof r.lng !== 'number') return;

  drawOriginToRestaurantLine(r);
  if (entry.kind === 'google' && googleMap) {
    googleMap.panTo({ lat: r.lat, lng: r.lng });
    if ((googleMap.getZoom() || 13) < 16) googleMap.setZoom(16);
    if (openPopup) {
      setTimeout(() => openMarkerPopup(entry, r), 180);
    }
    return;
  }
  if (entry.kind === 'leaflet' && leafletMap) {
    leafletMap.flyTo([r.lat, r.lng], 16, { duration: 0.6 });
    if (openPopup) {
      setTimeout(() => openMarkerPopup(entry, r), 400);
    }
  }
}

export function focusRestaurantOnMap(idx) {
  const item = state.displayedItems[idx];
  const entry = itemMarkers[idx];
  if (!item || !entry) return;
  const mapEl = document.getElementById('resultsMap');
  if (mapEl && mapEl.classList.contains('hidden')) {
    mapEl.classList.remove('hidden');
    const toggleBtn = document.getElementById('toggleMapBtn');
    if (toggleBtn) toggleBtn.textContent = 'Hide Map';
    if (leafletMap) leafletMap.invalidateSize();
    if (googleMap && window.google?.maps) {
      window.google.maps.event.trigger(googleMap, 'resize');
    }
  }
  const mapSection = document.getElementById('mapSection');
  if (mapSection) mapSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
  flyToMarkerForItem(idx, true);
}

function fitMapToBoundsPoints() {
  if (mapBoundsPoints.length === 0) return;
  if (activeEngine === 'google' && googleMap && window.google?.maps) {
    const gmaps = window.google.maps;
    const bounds = new gmaps.LatLngBounds();
    mapBoundsPoints.forEach(([lat, lng]) => bounds.extend({ lat, lng }));
    googleMap.fitBounds(bounds, 36);
    if (mapBoundsPoints.length === 1) googleMap.setZoom(15);
    gmaps.event.addListenerOnce(googleMap, 'bounds_changed', () => {
      if ((googleMap.getZoom() || 0) > 16) googleMap.setZoom(16);
    });
    return;
  }
  if (activeEngine === 'leaflet' && leafletMap) {
    leafletMap.fitBounds(mapBoundsPoints, { padding: [36, 36], maxZoom: 16 });
  }
}

function buildRestaurantPopupHtml(item, idx) {
  const r = item.restaurant || {};
  const badgeLabel = item.isMatch ? 'Match' : 'Alternative';
  const travelMins = getTravelMinutesFn(r, state.activeSearchMode);
  const modeLabel = state.activeSearchMode === 'drive'
    ? 'drive'
    : (state.activeSearchMode === 'transit' ? 'transit' : 'walk');
  const travelLabel = travelMins !== null ? `${Math.round(travelMins)} mins (${modeLabel})` : '';
  const placeId = getPlacePhotoId(r);
  const cachedPhoto = placeId ? photoCache.get(placeId) : null;
  const showPhotoSlot = Boolean(placeId) && cachedPhoto?.status !== 'none';
  const isPhotoHit = cachedPhoto?.status === 'ok' && Boolean(cachedPhoto.objectUrl);
  const photoSlotHtml = showPhotoSlot
    ? `
      <div class="bf-iw-photo-wrap ${isPhotoHit ? '' : 'bf-iw-photo-loading'}" data-photo-place-id="${escapeHtml(placeId)}">
        <img class="bf-iw-photo-img ${isPhotoHit ? '' : 'hidden'}" ${isPhotoHit ? `src="${escapeHtml(cachedPhoto.objectUrl)}"` : ''} alt="${escapeHtml(r.name || 'Restaurant')} photo" />
        <span class="bf-iw-photo-credit ${isPhotoHit && cachedPhoto.author ? '' : 'hidden'}">${isPhotoHit && cachedPhoto.author ? escapeHtml(`Photo: ${cachedPhoto.author}`) : ''}</span>
      </div>
    `
    : '';
  return `
    <div class="bf-iw-card">
      <div class="bf-iw-title">${idx + 1}. ${escapeHtml(r.name || 'Restaurant')}</div>
      ${photoSlotHtml}
      <div class="bf-iw-meta">${badgeLabel} • ★ ${escapeHtml(r.rating || r.g_rating || 'N/A')} ${travelLabel ? '• ' + escapeHtml(travelLabel) : ''}</div>
      <div class="bf-iw-hours">🕒 ${escapeHtml(formatHoursFn(r))}</div>
      <button type="button" onclick="openRouteDrawer(${idx})" class="bf-iw-btn">
        View Step-by-Step Route
      </button>
    </div>
  `;
}

function renderGoogleMapItems(allItems) {
  const gmaps = window.google.maps;
  const isDark = document.documentElement.classList.contains('dark');
  if (!googleMap) {
    const mapEl = document.getElementById('resultsMap');
    if (mapEl) mapEl.innerHTML = '';
    googleMap = new gmaps.Map(mapEl, {
      center: { lat: 1.3521, lng: 103.8198 },
      zoom: 13,
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: true,
      clickableIcons: false,
      styles: isDark ? GOOGLE_MAP_DARK_STYLES : GOOGLE_MAP_LIGHT_STYLES,
    });
    googleInfoWindow = new gmaps.InfoWindow({ maxWidth: 296 });
  }

  clearRouteLines();
  clearAllMarkers();

  if (state.lastOrigin && typeof state.lastOrigin.latitude === 'number' && typeof state.lastOrigin.longitude === 'number') {
    const oLat = state.lastOrigin.latitude;
    const oLng = state.lastOrigin.longitude;
    mapBoundsPoints.push([oLat, oLng]);

    if (state.lastInputOrigins && state.lastInputOrigins.length > 1) {
      state.lastInputOrigins.forEach((personOrigin, pIdx) => {
        if (typeof personOrigin.latitude !== 'number' || typeof personOrigin.longitude !== 'number') return;
        const pLat = personOrigin.latitude;
        const pLng = personOrigin.longitude;
        mapBoundsPoints.push([pLat, pLng]);

        const personMarker = new gmaps.Marker({
          map: googleMap,
          position: { lat: pLat, lng: pLng },
          icon: buildPinMarkerIcon(gmaps, { color: '#6366f1', scale: 13, strokeWeight: 2 }),
          label: { text: `P${pIdx + 1}`, color: '#ffffff', fontWeight: '800', fontSize: '10px' },
          zIndex: 950,
          title: personOrigin.query || `Location ${pIdx + 1}`,
        });
        const personHtml = `
          <div class="bf-iw-card-compact">
            <div class="bf-iw-title bf-iw-title-person">Location ${pIdx + 1}: ${escapeHtml(personOrigin.query || 'Address')}</div>
            <div class="bf-iw-subtext">${escapeHtml(personOrigin.label || '')}</div>
          </div>
        `;
        personMarker.addListener('click', () => {
          googleInfoWindow.setContent(personHtml);
          googleInfoWindow.open({ map: googleMap, anchor: personMarker });
        });
        googleMarkersLayer.push(personMarker);

        const connector = new gmaps.Polyline(buildPolylineOptions(
          gmaps,
          'midpoint',
          [{ lat: pLat, lng: pLng }, { lat: oLat, lng: oLng }],
        ));
        connector.setMap(googleMap);
        googleMarkersLayer.push(connector);
      });
    }

    const isMidpoint = state.lastInputOrigins && state.lastInputOrigins.length > 1;
    const originMarker = new gmaps.Marker({
      map: googleMap,
      position: { lat: oLat, lng: oLng },
      icon: buildPinMarkerIcon(gmaps, { color: '#2563eb', scale: 14, strokeWeight: 2.5 }),
      label: { text: isMidpoint ? 'Mid' : 'You', color: '#ffffff', fontWeight: '800', fontSize: '10px' },
      zIndex: 1000,
      title: isMidpoint ? 'Meet-in-the-Middle Center' : 'Starting Location',
    });
    const originHtml = `
      <div class="bf-iw-card-compact">
        <div class="bf-iw-title bf-iw-title-origin">${isMidpoint ? '🎯 Meet-in-the-Middle Center' : 'Starting Location'}</div>
        <div class="bf-iw-subtext">${escapeHtml(state.lastOrigin.label || state.lastOrigin.query || 'Your Origin')}</div>
      </div>
    `;
    originMarker.addListener('click', () => {
      googleInfoWindow.setContent(originHtml);
      googleInfoWindow.open({ map: googleMap, anchor: originMarker });
    });
    googleMarkersLayer.push(originMarker);
  }

  allItems.forEach((item, idx) => {
    const r = item.restaurant || {};
    if (typeof r.lat !== 'number' || typeof r.lng !== 'number') {
      itemMarkers.push(null);
      return;
    }
    mapBoundsPoints.push([r.lat, r.lng]);
    const pinColor = item.isMatch ? '#059669' : '#d97706';
    const marker = new gmaps.Marker({
      map: googleMap,
      position: { lat: r.lat, lng: r.lng },
      icon: buildPinMarkerIcon(gmaps, { color: pinColor, scale: 13, strokeWeight: 2 }),
      label: { text: String(idx + 1), color: '#ffffff', fontWeight: '800', fontSize: '11px' },
      zIndex: idx + 10,
      title: r.name || 'Restaurant',
    });
    const entry = { kind: 'google', marker, color: pinColor, item, idx };
    marker.addListener('click', () => {
      openMarkerPopup(entry, r);
      void drawRouteForRestaurant(r);
    });
    googleMarkersLayer.push(marker);
    itemMarkers.push(entry);
  });

  fitMapToBoundsPoints();
}

function renderLeafletMapItems(allItems) {
  if (!window.L) return;
  if (!leafletMap) {
    const mapEl = document.getElementById('resultsMap');
    if (mapEl) mapEl.innerHTML = '';
    leafletMap = window.L.map('resultsMap', { zoomControl: true, maxBoundsViscosity: 1.0 })
      .setView([1.3521, 103.8198], 13);
    leafletTileLayer = window.L.tileLayer(getTileUrl(), {
      attribution: '&copy; <a href="https://www.onemap.gov.sg" target="_blank">OneMap</a> &copy; SLA &copy; OpenStreetMap',
      maxZoom: 19,
      minZoom: 11,
      detectRetina: true,
    }).addTo(leafletMap);
    leafletMarkersLayer = window.L.layerGroup().addTo(leafletMap);
  }

  setTimeout(() => leafletMap?.invalidateSize(), 60);
  clearRouteLines();
  clearAllMarkers();

  if (state.lastOrigin && typeof state.lastOrigin.latitude === 'number' && typeof state.lastOrigin.longitude === 'number') {
    const oLat = state.lastOrigin.latitude;
    const oLng = state.lastOrigin.longitude;
    mapBoundsPoints.push([oLat, oLng]);

    if (state.lastInputOrigins && state.lastInputOrigins.length > 1) {
      state.lastInputOrigins.forEach((personOrigin, pIdx) => {
        if (typeof personOrigin.latitude !== 'number' || typeof personOrigin.longitude !== 'number') return;
        const pLat = personOrigin.latitude;
        const pLng = personOrigin.longitude;
        mapBoundsPoints.push([pLat, pLng]);

        const personIcon = window.L.divIcon({
          className: '',
          html: `<div class="bf-pin" style="width:28px;height:28px;background:#6366f1;font-size:12px;" title="Address ${pIdx + 1}">👤</div>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14],
          popupAnchor: [0, -14],
        });
        const personMarker = window.L.marker([pLat, pLng], { icon: personIcon, zIndexOffset: 950 })
          .bindPopup(`
            <div class="bf-iw-card-compact">
              <div class="bf-iw-title bf-iw-title-person">Location ${pIdx + 1}: ${escapeHtml(personOrigin.query || 'Address')}</div>
              <div class="bf-iw-subtext">${escapeHtml(personOrigin.label || '')}</div>
            </div>
          `);
        leafletMarkersLayer.addLayer(personMarker);

        const midConnector = window.L.polyline([[pLat, pLng], [oLat, oLng]], {
          color: '#6366f1',
          weight: 2.5,
          dashArray: '5, 6',
          opacity: 0.75,
        });
        leafletMarkersLayer.addLayer(midConnector);
      });
    }

    const isMidpoint = state.lastInputOrigins && state.lastInputOrigins.length > 1;
    const originIcon = window.L.divIcon({
      className: '',
      html: `<div class="bf-pin bf-pin-origin" style="width:30px;height:30px;">${isMidpoint ? '🎯' : '📍'}</div>`,
      iconSize: [30, 30],
      iconAnchor: [15, 15],
      popupAnchor: [0, -15],
    });
    const originMarker = window.L.marker([oLat, oLng], { icon: originIcon, zIndexOffset: 1000 })
      .bindPopup(`
        <div class="bf-iw-card-compact">
          <div class="bf-iw-title bf-iw-title-origin">${isMidpoint ? '🎯 Meet-in-the-Middle Center' : 'Starting Location'}</div>
          <div class="bf-iw-subtext">${escapeHtml(state.lastOrigin.label || state.lastOrigin.query || 'Your Origin')}</div>
        </div>
      `);
    leafletMarkersLayer.addLayer(originMarker);
  }

  allItems.forEach((item, idx) => {
    const r = item.restaurant || {};
    if (typeof r.lat !== 'number' || typeof r.lng !== 'number') {
      itemMarkers.push(null);
      return;
    }
    mapBoundsPoints.push([r.lat, r.lng]);
    const pinClass = item.isMatch ? 'bf-pin-match' : 'bf-pin-alt';
    const icon = window.L.divIcon({
      className: '',
      html: `<div class="bf-pin ${pinClass}" style="width:28px;height:28px;">${idx + 1}</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
      popupAnchor: [0, -14],
    });
    const marker = window.L.marker([r.lat, r.lng], { icon })
      .bindPopup(() => buildRestaurantPopupHtml(item, idx));
    marker.on('popupopen', (evt) => {
      hydratePopupPhoto(evt?.popup?.getElement?.(), r, ++activePopupSeq);
    });
    marker.on('click', () => { void drawRouteForRestaurant(r); });
    leafletMarkersLayer.addLayer(marker);
    itemMarkers.push({ kind: 'leaflet', marker });
  });

  fitMapToBoundsPoints();
}

export async function updateInteractiveMap(allItems) {
  const mapSection = document.getElementById('mapSection');
  if (!mapSection) return;
  mapSection.classList.remove('hidden');

  const originSig = getOriginSignature();
  const sameSearchOrigin = Boolean(originSig && originSig === lastOriginSignature);
  if (!sameSearchOrigin) {
    selectedRouteTarget = null;
  }
  lastOriginSignature = originSig;
  lastRenderedItems = Array.isArray(allItems) ? allItems : [];
  setMapRouteStatus('');

  const gen = ++mapRenderGeneration;
  const engine = await ensureMapEngine();
  if (gen !== mapRenderGeneration || !engine) return;

  if (engine === 'google') {
    renderGoogleMapItems(lastRenderedItems);
  } else {
    renderLeafletMapItems(lastRenderedItems);
  }

  if (selectedRouteTarget?.placeKey) {
    const matched = lastRenderedItems.find(
      (item) => getPlaceKey(item?.restaurant) === selectedRouteTarget.placeKey,
    );
    if (matched?.restaurant) {
      await drawRouteForRestaurant(matched.restaurant, selectedRouteTarget.customOrigin);
    } else {
      selectedRouteTarget = null;
    }
  }
}

export async function openRouteDrawer(idx, originIndex = -1) {
  const routeModal = document.getElementById('routeModal');
  const item = state.displayedItems[idx];
  if (!item || !state.lastOrigin || !routeModal) return;
  const r = item.restaurant || {};

  const isMulti = state.lastInputOrigins && state.lastInputOrigins.length > 1;
  const selectedOrigin = (isMulti && originIndex >= 0 && state.lastInputOrigins[originIndex])
    ? state.lastInputOrigins[originIndex]
    : state.lastOrigin;

  const selectorBar = document.getElementById('routeOriginSelectorBar');
  if (selectorBar) {
    if (isMulti) {
      selectorBar.classList.remove('hidden');
      const midActive = originIndex === -1;
      let btnsHtml = '<span class="text-[10px] font-extrabold uppercase tracking-wider text-indigo-600 dark:text-indigo-300 mr-1">Route From:</span>';
      btnsHtml += `<button type="button" onclick="openRouteDrawer(${idx}, -1)"
        class="px-2.5 py-1 rounded-lg text-[11px] font-bold transition border ${midActive
          ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
          : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border-indigo-200 dark:border-indigo-800 hover:bg-indigo-100 dark:hover:bg-indigo-900/50'}">
        🎯 Midpoint
      </button>`;
      state.lastInputOrigins.forEach((orig, pIdx) => {
        const isAct = originIndex === pIdx;
        const shortName = orig.query || `Location ${pIdx + 1}`;
        btnsHtml += `<button type="button" onclick="openRouteDrawer(${idx}, ${pIdx})"
          class="px-2.5 py-1 rounded-lg text-[11px] font-bold transition border ${isAct
            ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
            : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border-indigo-200 dark:border-indigo-800 hover:bg-indigo-100 dark:hover:bg-indigo-900/50'}">
          👤 ${escapeHtml(shortName)}
        </button>`;
      });
      selectorBar.innerHTML = btnsHtml;
    } else {
      selectorBar.classList.add('hidden');
      selectorBar.innerHTML = '';
    }
  }

  const effectiveMode = state.activeSearchMode || state.currentMode || 'walk';
  document.getElementById('routeModalTitle').textContent = r.name || 'Restaurant Route';
  document.getElementById('routeModalSubtitle').textContent = `From ${selectedOrigin.label || selectedOrigin.query || 'Starting Location'}`;
  document.getElementById('routeModeBadge').textContent = effectiveMode;

  const estMins = originIndex === -1 ? getTravelMinutesFn(r, effectiveMode) : null;
  document.getElementById('routeDurationBadge').textContent = estMins !== null ? `${Math.round(estMins)} mins` : '...';
  const estMeters = originIndex === -1 ? r[`${effectiveMode}_meters`] : null;
  document.getElementById('routeDistanceBadge').textContent = estMeters
    ? (estMeters >= 1000 ? `${(estMeters / 1000).toFixed(2)} km` : `${estMeters} m`)
    : '...';

  const stepsContainer = document.getElementById('routeStepsContainer');
  stepsContainer.innerHTML = `
    <div class="flex items-center justify-center py-8 text-slate-500 dark:text-slate-400 gap-2">
      <svg class="animate-spin w-4 h-4 text-brand-600" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
      <span>Fetching turn-by-turn directions from Google Routes...</span>
    </div>
  `;

  const fallbackMapsUrl = `https://www.google.com/maps/dir/?api=1&origin=${selectedOrigin.latitude},${selectedOrigin.longitude}&destination=${r.lat},${r.lng}&travelmode=${effectiveMode === 'drive' ? 'driving' : effectiveMode === 'transit' ? 'transit' : 'walking'}`;
  document.getElementById('routeGoogleMapsBtn').href = fallbackMapsUrl;

  openModal(routeModal);
  refreshIcons(routeModal);

  const trafficCheck = document.getElementById('trafficAwareCheck');
  const trafficAware = effectiveMode === 'drive' && Boolean(trafficCheck && trafficCheck.checked);
  try {
    const data = await fetchRouteForOrigin(selectedOrigin, r, effectiveMode, trafficAware);
    void drawRouteForRestaurant(r, selectedOrigin, data);

    if (data.link) {
      document.getElementById('routeGoogleMapsBtn').href = data.link;
    }

    const route = data.route;
    if (route) {
      if (route.duration_min !== undefined) {
        document.getElementById('routeDurationBadge').textContent = `${route.duration_min} mins`;
      }
      if (route.distance_m !== undefined) {
        document.getElementById('routeDistanceBadge').textContent = route.distance_m >= 1000
          ? `${(route.distance_m / 1000).toFixed(2)} km`
          : `${route.distance_m} m`;
      }
      const steps = route.steps || [];
      if (steps.length > 0) {
        stepsContainer.innerHTML = steps.map((stepText, sIdx) => `
          <div class="flex items-start gap-3 p-3 rounded-xl bg-slate-50 dark:bg-slate-800/70 border border-slate-200 dark:border-slate-700/80">
            <span class="w-6 h-6 rounded-full bg-brand-600 text-white font-bold text-[11px] flex items-center justify-center shrink-0 mt-0.5">${sIdx + 1}</span>
            <p class="text-slate-700 dark:text-slate-200 font-medium leading-relaxed">${escapeHtml(stepText)}</p>
          </div>
        `).join('');
        return;
      }
    }

    stepsContainer.innerHTML = `
      <div class="p-4 rounded-xl bg-amber-50 dark:bg-amber-950/50 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 text-center">
        Detailed step-by-step instructions are not available for this route segment. Click <strong>Open in Google Maps</strong> below to launch full navigation.
      </div>
    `;
  } catch (err) {
    void drawRouteForRestaurant(r, selectedOrigin);
    stepsContainer.innerHTML = `
      <div class="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/50 border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300 text-center">
        ${escapeHtml(err.message)}
      </div>
    `;
  }
}

export function initMapControls() {
  const routeModal = document.getElementById('routeModal');
  document.getElementById('closeRouteModalBtn')?.addEventListener('click', () => closeModal(routeModal));
  document.getElementById('closeRouteFooterBtn')?.addEventListener('click', () => closeModal(routeModal));

  document.getElementById('fitMapBoundsBtn')?.addEventListener('click', () => {
    fitMapToBoundsPoints();
  });

  document.getElementById('toggleMapBtn')?.addEventListener('click', () => {
    const mapEl = document.getElementById('resultsMap');
    const btn = document.getElementById('toggleMapBtn');
    if (!mapEl || !btn) return;
    const isHidden = mapEl.classList.toggle('hidden');
    btn.textContent = isHidden ? 'Show Map' : 'Hide Map';
    if (!isHidden) {
      if (leafletMap) setTimeout(() => leafletMap.invalidateSize(), 60);
      if (googleMap && window.google?.maps) {
        setTimeout(() => {
          window.google.maps.event.trigger(googleMap, 'resize');
          fitMapToBoundsPoints();
        }, 60);
      }
    }
  });

  window.focusRestaurantOnMap = focusRestaurantOnMap;
  window.openRouteDrawer = openRouteDrawer;
}
