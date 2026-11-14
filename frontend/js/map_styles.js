export const GOOGLE_MAP_LIGHT_STYLES = [
  {
    featureType: 'poi.business',
    stylers: [{ visibility: 'off' }],
  },
];

export const GOOGLE_MAP_DARK_STYLES = [
  { elementType: 'geometry', stylers: [{ color: '#172338' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#0b1220' }, { weight: 3 }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#cbd5e1' }] },
  {
    featureType: 'administrative.locality',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#f8fafc' }],
  },
  {
    featureType: 'administrative.neighborhood',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#a5b4fc' }],
  },
  {
    featureType: 'landscape.man_made',
    elementType: 'geometry.fill',
    stylers: [{ color: '#1e2e49' }],
  },
  {
    featureType: 'landscape.man_made',
    elementType: 'geometry.stroke',
    stylers: [{ color: '#2a3e61' }],
  },
  {
    featureType: 'landscape.natural',
    elementType: 'geometry.fill',
    stylers: [{ color: '#13303a' }],
  },
  {
    featureType: 'poi.business',
    stylers: [{ visibility: 'off' }],
  },
  {
    featureType: 'poi.park',
    elementType: 'geometry',
    stylers: [{ color: '#134e3a' }],
  },
  {
    featureType: 'poi.park',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#5eead4' }],
  },
  {
    featureType: 'poi.attraction',
    elementType: 'geometry',
    stylers: [{ color: '#213758' }],
  },
  {
    featureType: 'poi.attraction',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#c4b5fd' }],
  },
  {
    featureType: 'poi.school',
    elementType: 'geometry',
    stylers: [{ color: '#1d3250' }],
  },
  {
    featureType: 'poi.school',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#93c5fd' }],
  },
  {
    featureType: 'poi.medical',
    elementType: 'geometry',
    stylers: [{ color: '#29274c' }],
  },
  {
    featureType: 'poi.medical',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#f9a8d4' }],
  },
  {
    featureType: 'road',
    elementType: 'geometry',
    stylers: [{ color: '#2b3e5e' }],
  },
  {
    featureType: 'road',
    elementType: 'geometry.stroke',
    stylers: [{ color: '#131d2f' }],
  },
  {
    featureType: 'road',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#e2e8f0' }],
  },
  {
    featureType: 'road.local',
    elementType: 'geometry',
    stylers: [{ color: '#253652' }],
  },
  {
    featureType: 'road.local',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#94a3b8' }],
  },
  {
    featureType: 'road.arterial',
    elementType: 'geometry',
    stylers: [{ color: '#395580' }],
  },
  {
    featureType: 'road.highway',
    elementType: 'geometry.fill',
    stylers: [{ color: '#8f5b1e' }],
  },
  {
    featureType: 'road.highway',
    elementType: 'geometry.stroke',
    stylers: [{ color: '#b87b2d' }],
  },
  {
    featureType: 'road.highway',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#fde68a' }],
  },
  {
    featureType: 'transit.line',
    elementType: 'geometry',
    stylers: [{ color: '#3b628f' }],
  },
  {
    featureType: 'transit.station',
    elementType: 'geometry',
    stylers: [{ color: '#1b3b5f' }],
  },
  {
    featureType: 'transit.station',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#67e8f9' }],
  },
  {
    featureType: 'water',
    elementType: 'geometry',
    stylers: [{ color: '#0c3b6e' }],
  },
  {
    featureType: 'water',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#7dd3fc' }],
  },
];

export function buildPinMarkerIcon(gmaps, { color, scale = 13, strokeWeight = 2 }) {
  return {
    path: gmaps.SymbolPath.CIRCLE,
    scale,
    fillColor: color,
    fillOpacity: 1,
    strokeColor: '#ffffff',
    strokeWeight,
  };
}

export function buildPolylineOptions(gmaps, styleKind, path) {
  const base = { path, geodesic: false };
  if (styleKind === 'walk') {
    return {
      ...base,
      strokeOpacity: 0,
      zIndex: 55,
      icons: [{
        icon: {
          path: gmaps.SymbolPath.CIRCLE,
          fillColor: '#0284c7',
          fillOpacity: 1,
          strokeColor: '#ffffff',
          strokeWeight: 1,
          scale: 3.4,
        },
        offset: '0',
        repeat: '12px',
      }],
    };
  }
  if (styleKind === 'transit') {
    return {
      ...base,
      strokeColor: '#7c3aed',
      strokeOpacity: 0.92,
      strokeWeight: 5,
      zIndex: 52,
    };
  }
  if (styleKind === 'drive') {
    return {
      ...base,
      strokeColor: '#2563eb',
      strokeOpacity: 0.92,
      strokeWeight: 5,
      zIndex: 50,
    };
  }
  if (styleKind === 'midpoint') {
    return {
      ...base,
      strokeOpacity: 0,
      zIndex: 30,
      icons: [{
        icon: {
          path: 'M 0,-1 0,1',
          strokeColor: '#6366f1',
          strokeOpacity: 0.75,
          strokeWeight: 2.5,
          scale: 2.5,
        },
        offset: '0',
        repeat: '11px',
      }],
    };
  }
  return {
    ...base,
    strokeOpacity: 0,
    zIndex: 45,
    icons: [{
      icon: {
        path: 'M 0,-1 0,1',
        strokeColor: '#ea580c',
        strokeOpacity: 0.9,
        strokeWeight: 3,
        scale: 3,
      },
      offset: '0',
      repeat: '14px',
    }],
  };
}
