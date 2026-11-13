import { escapeHtml, refreshIcons, state } from './state.js';
import { openModal, closeModal } from './modals.js';
import { apiJson } from './api.js';

let mapInstance = null;
let mapTileLayer = null;
let mapMarkersLayer = null;
let mapRouteLine = null;
let itemMarkers = [];
let mapBoundsPoints = [];
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

export function refreshMapTheme() {
  if (mapInstance && mapTileLayer) {
    mapTileLayer.setUrl(getTileUrl());
  }
}

export function drawOriginToRestaurantLine(r, customOrigin = null) {
  const activeOrigin = customOrigin || state.lastOrigin;
  if (!mapInstance || !activeOrigin || typeof r.lat !== 'number' || typeof r.lng !== 'number') return;
  if (mapRouteLine) {
    mapInstance.removeLayer(mapRouteLine);
  }
  mapRouteLine = window.L.polyline(
    [[activeOrigin.latitude, activeOrigin.longitude], [r.lat, r.lng]],
    { color: '#ea580c', weight: 4, dashArray: '8, 8', opacity: 0.9 },
  ).addTo(mapInstance);
}

export function highlightMapPin(idx, active) {
  const marker = itemMarkers[idx];
  if (!marker) return;
  const el = marker.getElement();
  if (!el) return;
  const pin = el.querySelector('.bf-pin');
  if (pin) {
    pin.classList.toggle('bf-pin-hovered', Boolean(active));
  }
  if (typeof marker.setZIndexOffset === 'function') {
    marker.setZIndexOffset(active ? 1200 : 0);
  }
}

export function flyToMarkerForItem(idx, openPopup = true) {
  const item = state.displayedItems[idx];
  const marker = itemMarkers[idx];
  if (!item || !marker || !mapInstance) return;
  const r = item.restaurant || {};
  if (typeof r.lat !== 'number' || typeof r.lng !== 'number') return;
  drawOriginToRestaurantLine(r);
  mapInstance.flyTo([r.lat, r.lng], 16, { duration: 0.6 });
  if (openPopup) {
    setTimeout(() => marker.openPopup(), 400);
  }
}

export function focusRestaurantOnMap(idx) {
  const item = state.displayedItems[idx];
  const marker = itemMarkers[idx];
  if (!item || !marker || !mapInstance) return;
  const mapEl = document.getElementById('resultsMap');
  if (mapEl && mapEl.classList.contains('hidden')) {
    mapEl.classList.remove('hidden');
    const toggleBtn = document.getElementById('toggleMapBtn');
    if (toggleBtn) toggleBtn.textContent = 'Hide Map';
    mapInstance.invalidateSize();
  }
  const mapSection = document.getElementById('mapSection');
  if (mapSection) mapSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
  flyToMarkerForItem(idx, true);
}

export function updateInteractiveMap(allItems) {
  const mapSection = document.getElementById('mapSection');
  if (!mapSection || !window.L) return;
  mapSection.classList.remove('hidden');

  if (!mapInstance) {
    mapInstance = window.L.map('resultsMap', { zoomControl: true, maxBoundsViscosity: 1.0 }).setView([1.3521, 103.8198], 13);
    mapTileLayer = window.L.tileLayer(getTileUrl(), {
      attribution: '&copy; <a href="https://www.onemap.gov.sg" target="_blank">OneMap</a> &copy; SLA &copy; OpenStreetMap',
      maxZoom: 19,
      minZoom: 11,
      detectRetina: true,
    }).addTo(mapInstance);
    mapMarkersLayer = window.L.layerGroup().addTo(mapInstance);
  }

  setTimeout(() => mapInstance.invalidateSize(), 60);
  mapMarkersLayer.clearLayers();
  if (mapRouteLine) {
    mapInstance.removeLayer(mapRouteLine);
    mapRouteLine = null;
  }

  itemMarkers = [];
  mapBoundsPoints = [];

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
            <div class="text-xs">
              <div class="font-extrabold text-indigo-600">Location ${pIdx + 1}: ${escapeHtml(personOrigin.query || 'Address')}</div>
              <div class="text-slate-600 mt-0.5">${escapeHtml(personOrigin.label || '')}</div>
            </div>
          `);
        mapMarkersLayer.addLayer(personMarker);

        const midConnector = window.L.polyline([[pLat, pLng], [oLat, oLng]], {
          color: '#6366f1',
          weight: 2.5,
          dashArray: '5, 6',
          opacity: 0.75,
        });
        mapMarkersLayer.addLayer(midConnector);
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
        <div class="text-xs">
          <div class="font-extrabold text-blue-600">${isMidpoint ? '🎯 Meet-in-the-Middle Center' : 'Starting Location'}</div>
          <div class="text-slate-600 mt-0.5">${escapeHtml(state.lastOrigin.label || state.lastOrigin.query || 'Your Origin')}</div>
        </div>
      `);
    mapMarkersLayer.addLayer(originMarker);
  }

  allItems.forEach((item, idx) => {
    const r = item.restaurant || {};
    if (typeof r.lat !== 'number' || typeof r.lng !== 'number') {
      itemMarkers.push(null);
      return;
    }
    mapBoundsPoints.push([r.lat, r.lng]);
    const pinClass = item.isMatch ? 'bf-pin-match' : 'bf-pin-alt';
    const badgeLabel = item.isMatch ? 'Match' : 'Alternative';
    const icon = window.L.divIcon({
      className: '',
      html: `<div class="bf-pin ${pinClass}" style="width:28px;height:28px;">${idx + 1}</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
      popupAnchor: [0, -14],
    });

    const travelMins = getTravelMinutesFn(r, state.activeSearchMode);
    const modeLabel = state.activeSearchMode === 'drive' ? 'drive' : state.activeSearchMode === 'transit' ? 'transit' : 'walk';
    const travelLabel = travelMins !== null ? `${Math.round(travelMins)} mins (${modeLabel})` : '';

    const marker = window.L.marker([r.lat, r.lng], { icon })
      .bindPopup(`
        <div class="text-xs space-y-1 min-w-[180px]">
          <div class="font-extrabold text-slate-900">${idx + 1}. ${escapeHtml(r.name || 'Restaurant')}</div>
          <div class="text-[11px] text-slate-500">${badgeLabel} • ★ ${escapeHtml(r.rating || r.g_rating || 'N/A')} ${travelLabel ? '• ' + escapeHtml(travelLabel) : ''}</div>
          <div class="text-[11px] text-slate-600">🕒 ${escapeHtml(formatHoursFn(r))}</div>
          <div class="pt-1">
            <button type="button" onclick="openRouteDrawer(${idx})"
              class="w-full py-1 px-2 rounded-lg font-bold text-[11px] text-white bg-orange-600 hover:bg-orange-700 transition">
              View Step-by-Step Route
            </button>
          </div>
        </div>
      `);

    marker.on('click', () => drawOriginToRestaurantLine(r));
    mapMarkersLayer.addLayer(marker);
    itemMarkers.push(marker);
  });

  if (mapBoundsPoints.length > 0) {
    mapInstance.fitBounds(mapBoundsPoints, { padding: [36, 36], maxZoom: 16 });
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

  drawOriginToRestaurantLine(r, selectedOrigin);

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
  try {
    const data = await apiJson('/api/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        origin_lat: selectedOrigin.latitude,
        origin_lng: selectedOrigin.longitude,
        dest_lat: r.lat,
        dest_lng: r.lng,
        name: r.name || 'Restaurant',
        mode: effectiveMode,
        traffic_aware: effectiveMode === 'drive' && Boolean(trafficCheck && trafficCheck.checked),
      }),
    });

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
    if (mapInstance && mapBoundsPoints.length > 0) {
      mapInstance.fitBounds(mapBoundsPoints, { padding: [36, 36], maxZoom: 16 });
    }
  });

  document.getElementById('toggleMapBtn')?.addEventListener('click', () => {
    const mapEl = document.getElementById('resultsMap');
    const btn = document.getElementById('toggleMapBtn');
    if (!mapEl || !btn) return;
    const isHidden = mapEl.classList.toggle('hidden');
    btn.textContent = isHidden ? 'Show Map' : 'Hide Map';
    if (!isHidden && mapInstance) {
      setTimeout(() => mapInstance.invalidateSize(), 60);
    }
  });

  window.focusRestaurantOnMap = focusRestaurantOnMap;
  window.openRouteDrawer = openRouteDrawer;
}
