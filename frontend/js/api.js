const API_BASE = '';

async function _fetchJSON(method, path, body) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const opts = {
    method,
    headers: {},
  };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  if (res.status === 204) return null;
  return res.json().catch(() => null);
}

const api = {
  get(path) {
    return _fetchJSON('GET', path);
  },
  post(path, body) {
    return _fetchJSON('POST', path, body);
  },
  put(path, body) {
    return _fetchJSON('PUT', path, body);
  },
  del(path) {
    return _fetchJSON('DELETE', path);
  },
};

const carLogApi = {
  listSessions(params) {
    const qs = new URLSearchParams();
    if (params.device) qs.set('device', params.device);
    if (params.vin) qs.set('vin', params.vin);
    if (params.date_from) qs.set('date_from', params.date_from);
    if (params.date_to) qs.set('date_to', params.date_to);
    if (params.has_gps) qs.set('has_gps', 'true');
    if (params.has_wifi) qs.set('has_wifi', 'true');
    if (params.q) qs.set('q', params.q);
    if (params.skip) qs.set('skip', String(params.skip));
    if (params.limit) qs.set('limit', String(params.limit));
    const query = qs.toString();
    return api.get(`/api/car-logs/sessions${query ? '?' + query : ''}`);
  },
  getSession(sessionId) {
    return api.get(`/api/car-logs/sessions/${encodeURIComponent(sessionId)}`);
  },
  rawUrl(sessionId) {
    return `/api/car-logs/sessions/${encodeURIComponent(sessionId)}/raw`;
  },
};
