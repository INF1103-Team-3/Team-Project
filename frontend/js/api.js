import { authHeaders } from './state.js';

export async function apiJson(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: authHeaders(options.headers || {}),
  });

  const rawText = await res.text();
  let data = null;
  try {
    data = rawText ? JSON.parse(rawText) : {};
  } catch {
    if (res.status === 504) {
      throw new Error('Search timed out while BRC was warming up official MUIS records. Please retry shortly.');
    }
    throw new Error(`Server error (${res.status})`);
  }

  if (!res.ok) {
    throw new Error(data.detail || data.error || `Request failed (${res.status})`);
  }
  return data;
}
