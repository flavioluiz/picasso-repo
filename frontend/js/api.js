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
