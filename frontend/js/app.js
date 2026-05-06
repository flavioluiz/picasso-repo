(function() {
  'use strict';

  const contentEl = document.getElementById('content');
  const sidebarEl = document.getElementById('sidebar');
  const overlayEl = document.getElementById('overlay');
  const hamburgerEl = document.getElementById('hamburger');
  const themeToggleEl = document.getElementById('themeToggle');
  const themeIconEl = document.getElementById('themeIcon');

  function initTheme() {
    const stored = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark = stored === 'dark' || (!stored && prefersDark);
    document.documentElement.classList.toggle('dark', isDark);
    updateThemeIcon(isDark);
  }

  function toggleTheme() {
    const isDark = document.documentElement.classList.toggle('dark');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    updateThemeIcon(isDark);
  }

  function updateThemeIcon(isDark) {
    themeIconEl.textContent = isDark ? '\u2600' : '\u263E';
  }

  function setActiveLink(hash) {
    document.querySelectorAll('.nav-link').forEach(link => {
      link.classList.toggle('active', link.getAttribute('href') === hash);
    });
  }

  function openSidebar() {
    sidebarEl.classList.add('open');
    overlayEl.classList.add('show');
  }

  function closeSidebar() {
    sidebarEl.classList.remove('open');
    overlayEl.classList.remove('show');
  }

  function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B','KB','MB','GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  async function loadDashboard() {
    contentEl.innerHTML = '<p class="placeholder">Carregando estatísticas...</p>';
    try {
      const [tracks, playlists] = await Promise.all([
        api.get('/api/tracks'),
        api.get('/api/playlists'),
      ]);
      const totalSize = Array.isArray(tracks) ? tracks.reduce((sum, t) => sum + (t.size || 0), 0) : 0;
      const trackCount = Array.isArray(tracks) ? tracks.length : 0;
      const playlistCount = Array.isArray(playlists) ? playlists.length : 0;

      contentEl.innerHTML = `
        <h2 style="margin-top:0;margin-bottom:20px;font-weight:700;">Dashboard</h2>
        <div class="cards-grid">
          <div class="card">
            <p class="card-title">Total de MP3s</p>
            <p class="card-value">${trackCount}</p>
          </div>
          <div class="card">
            <p class="card-title">Total de Playlists</p>
            <p class="card-value">${playlistCount}</p>
          </div>
          <div class="card">
            <p class="card-title">Tamanho Total</p>
            <p class="card-value">${formatBytes(totalSize)}</p>
          </div>
        </div>
        <button class="btn btn-primary" id="syncBtn">&#128260; Sincronizar Repositório</button>
        <p id="syncMsg" style="margin-top:12px;color:var(--text-secondary);"></p>
      `;

      document.getElementById('syncBtn').addEventListener('click', async () => {
        const msgEl = document.getElementById('syncMsg');
        msgEl.textContent = 'Sincronizando...';
        try {
          const res = await api.post('/api/sync');
          msgEl.textContent = `Sincronizado! ${res.synced_tracks} faixas, ${res.synced_playlists} playlists.`;
          loadDashboard();
        } catch (e) {
          msgEl.textContent = 'Erro: ' + e.message;
        }
      });
    } catch (e) {
      contentEl.innerHTML = `<p class="placeholder">Erro ao carregar dashboard: ${e.message}</p>`;
    }
  }

  let _bibSearchTimer = null;
  let _bibQuery = '';
  let _bibMissingTitle = false;
  let _bibMissingArtist = false;

  function formatDuration(seconds) {
    if (!seconds) return '--:--';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  }

  function coverThumb(track) {
    if (track.has_cover) {
      const encoded = encodeURIComponent(track.path);
      return `<img src="/api/tracks/${encoded}/cover" alt="" style="width:40px;height:40px;object-fit:cover;border-radius:6px;background:var(--border);">`;
    }
    return `<span style="display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;border-radius:6px;background:var(--border);font-size:1.1rem;color:var(--text-secondary);">&#9835;</span>`;
  }

  function trackLabel(track) {
    return track.title || track.path || 'Faixa';
  }

  // ── Player ──────────────────────────────────────────────────────────
  const _player = {
    audio: null,
    queue: [],
    index: -1,
    shuffle: false,
    playing: false,
    history: [],
    barCreated: false,
  };

  function _initPlayer() {
    if (_player.audio) return;
    _player.audio = new Audio();
    _player.audio.addEventListener('ended', _onTrackEnded);
    _player.audio.addEventListener('play', () => { _player.playing = true; _updatePlayerUI(); });
    _player.audio.addEventListener('pause', () => { _player.playing = false; _updatePlayerUI(); });
    _player.audio.addEventListener('timeupdate', _updatePlayerProgress);
  }

  function _ensurePlayerBar() {
    const oldBar = document.getElementById('audioBar');
    if (oldBar) oldBar.remove();
    if (_player.barCreated) {
      document.getElementById('playerBar').style.display = '';
    } else {
      document.body.insertAdjacentHTML('beforeend', `
        <div class="player-bar" id="playerBar">
          <div class="player-progress" id="playerProgress">
            <div class="player-progress-fill" id="playerProgressFill"></div>
          </div>
          <div class="player-content">
            <div class="player-info">
              <div class="player-cover" id="playerCover">&#9835;</div>
              <div class="player-text">
                <div class="player-title" id="playerTitle">-</div>
                <div class="player-artist" id="playerArtist"></div>
              </div>
            </div>
            <div class="player-controls">
              <button class="player-btn" id="playerPrev" title="Anterior">&#x23EE;</button>
              <button class="player-btn player-btn-main" id="playerPlay" title="Play">&#9654;</button>
              <button class="player-btn" id="playerNext" title="Pr&#243;xima">&#x23ED;</button>
              <button class="player-btn" id="playerShuffle" title="Aleat&#243;rio">&#x1F500;</button>
            </div>
          </div>
        </div>
      `);
      _player.barCreated = true;
      document.getElementById('playerProgress').addEventListener('click', _seekTo);
      document.getElementById('playerPlay').addEventListener('click', _togglePlay);
      document.getElementById('playerPrev').addEventListener('click', _playPrev);
      document.getElementById('playerNext').addEventListener('click', _playNext);
      document.getElementById('playerShuffle').addEventListener('click', _toggleShuffle);
    }
    document.body.classList.add('player-active');
  }

  function _updatePlayerUI() {
    const playBtn = document.getElementById('playerPlay');
    if (!playBtn) return;
    playBtn.innerHTML = _player.playing ? '&#x23F8;' : '&#9654;';
    playBtn.title = _player.playing ? 'Pausar' : 'Play';
    if (_player.index >= 0 && _player.queue[_player.index]) {
      const track = _player.queue[_player.index];
      const title = document.getElementById('playerTitle');
      const artist = document.getElementById('playerArtist');
      const cover = document.getElementById('playerCover');
      if (title) title.textContent = track.title || '-';
      if (artist) artist.textContent = track.artist || '';
      if (cover) {
        if (track.has_cover) {
          const enc = track.path.split('/').map(encodeURIComponent).join('/');
          cover.innerHTML = `<img src="/api/tracks/${enc}/cover" alt="">`;
        } else {
          cover.innerHTML = '&#9835;';
        }
      }
    }
    const shuffleBtn = document.getElementById('playerShuffle');
    if (shuffleBtn) shuffleBtn.classList.toggle('active', _player.shuffle);
  }

  function _updatePlayerProgress() {
    const fill = document.getElementById('playerProgressFill');
    if (!fill || !_player.audio) return;
    const pct = _player.audio.duration ? (_player.audio.currentTime / _player.audio.duration) * 100 : 0;
    fill.style.width = pct + '%';
  }

  function _seekTo(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    if (_player.audio && _player.audio.duration) {
      _player.audio.currentTime = pct * _player.audio.duration;
    }
  }

  function _togglePlay() {
    if (!_player.audio) return;
    if (_player.playing) {
      _player.audio.pause();
    } else {
      _player.audio.play().catch(() => {});
    }
  }

  function _playNext() {
    if (!_player.queue.length) return;
    _player.history.push(_player.index);
    let next;
    if (_player.shuffle) {
      if (_player.queue.length === 1) { next = 0; }
      else {
        next = Math.floor(Math.random() * _player.queue.length);
        while (next === _player.index) next = Math.floor(Math.random() * _player.queue.length);
      }
    } else {
      next = _player.index + 1;
      if (next >= _player.queue.length) next = 0;
    }
    _playQueueItem(next);
  }

  function _playPrev() {
    if (!_player.queue.length) return;
    if (_player.audio && _player.audio.currentTime > 3) {
      _player.audio.currentTime = 0;
      return;
    }
    if (_player.history.length > 0) {
      _playQueueItem(_player.history.pop());
    } else if (_player.index > 0) {
      _playQueueItem(_player.index - 1);
    }
  }

  function _toggleShuffle() {
    _player.shuffle = !_player.shuffle;
    _updatePlayerUI();
  }

  function _onTrackEnded() {
    _playNext();
  }

  function _playQueueItem(index) {
    const track = _player.queue[index];
    if (!track) return;
    _player.index = index;
    _player.audio.src = `/repo/${track.path.split('/').map(encodeURIComponent).join('/')}`;
    _player.audio.play().catch(() => {});
    _ensurePlayerBar();
    _updatePlayerUI();
  }

  function playTrack(path, label) {
    _initPlayer();
    _player.queue = [{ path, title: label || path, artist: '', has_cover: false }];
    _player.history = [];
    _playQueueItem(0);
  }

  function playQueue(queue, startIndex) {
    _initPlayer();
    _player.queue = queue;
    _player.history = [];
    _playQueueItem(startIndex || 0);
  }

  function bibliotecaToolbarHtml() {
    return `
      <div class="toolbar" style="align-items:center;">
        <input type="text" class="search-input" placeholder="Buscar músicas..." id="bibSearch" value="${esc(_bibQuery)}">
        <label style="display:flex;align-items:center;gap:6px;font-size:0.85rem;color:var(--text-secondary);white-space:nowrap;">
          <input type="checkbox" id="bibMissingTitle" ${_bibMissingTitle ? 'checked' : ''} style="width:16px;height:16px;accent-color:var(--accent);">
          Sem título
        </label>
        <label style="display:flex;align-items:center;gap:6px;font-size:0.85rem;color:var(--text-secondary);white-space:nowrap;">
          <input type="checkbox" id="bibMissingArtist" ${_bibMissingArtist ? 'checked' : ''} style="width:16px;height:16px;accent-color:var(--accent);">
          Sem artista
        </label>
      </div>
    `;
  }

  function renderDownloadedTracks(tracks) {
    if (!Array.isArray(tracks) || !tracks.length) return '';
    return `
      <div style="display:flex;flex-direction:column;gap:8px;margin-top:10px;">
        ${tracks.map(t => `
          <div style="display:grid;grid-template-columns:40px minmax(0,1fr) auto;gap:10px;align-items:center;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--surface);">
            ${coverThumb(t)}
            <div style="min-width:0;">
              <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(t.title || t.path)}</div>
              <div style="font-size:0.82rem;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                ${esc(t.artist || 'Artista não definido')}${t.album ? ' · ' + esc(t.album) : ''}
              </div>
              <div style="font-size:0.76rem;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(t.path)}</div>
            </div>
            <div class="actions">
              <button class="btn-icon yt-play-track" title="Tocar" data-path="${esc(t.path)}" data-label="${esc(trackLabel(t))}">&#9654;</button>
              <button class="btn btn-primary yt-edit-track" title="Editar metadados" data-path="${esc(t.path)}" style="padding:8px 10px;font-size:0.85rem;">&#9998; Editar</button>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  function renderBibliotecaTable(tracks) {
    const items = tracks.map((t, i) => `
      <div class="card" data-path="${esc(t.path)}" style="padding:14px 16px;">
        <div style="display:grid;grid-template-columns:40px minmax(0,1fr) auto;gap:12px;align-items:center;">
          ${coverThumb(t)}
          <div style="min-width:0;">
            <div style="font-weight:700;font-size:0.98rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(t.title) || '<em style="color:var(--text-secondary)">Sem título</em>'}</div>
            <div style="font-size:0.85rem;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
              ${esc(t.artist) || 'Artista não definido'}${t.album ? ' · ' + esc(t.album) : ''}${t.genre ? ' · ' + esc(t.genre) : ''}
            </div>
            <div style="font-size:0.78rem;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px;">
              ${esc(t.path)}
            </div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:6px;">${formatDuration(t.duration)}</div>
            <div class="actions" style="justify-content:flex-end;">
              <button class="btn-icon bib-play" title="Tocar" data-idx="${i}">&#9654;</button>
              <button class="btn-icon save edit-track" title="Editar" data-path="${esc(t.path)}">&#9998;</button>
              <button class="btn-icon delete delete-track" title="Excluir" data-path="${esc(t.path)}">&#128465;</button>
            </div>
          </div>
        </div>
      </div>
    `).join('');

    contentEl.innerHTML = `
      <h2 style="margin-top:0;margin-bottom:20px;font-weight:700;">Biblioteca</h2>
      ${bibliotecaToolbarHtml()}
      ${tracks.length ? `<div style="display:flex;flex-direction:column;gap:10px;">${items}</div>` : `<p class="placeholder" style="text-align:center;padding:48px 0;">&#127925; Nenhuma música encontrada.</p>`}
    `;

    setupBibSearch();
    contentEl.querySelectorAll('.edit-track').forEach(btn => {
      btn.addEventListener('click', () => openEditModal(btn.dataset.path));
    });
    const bibQueue = tracks.map(t => ({ path: t.path, title: t.title || t.path, artist: t.artist || '', has_cover: t.has_cover }));
    contentEl.querySelectorAll('.bib-play').forEach(btn => {
      btn.addEventListener('click', () => playQueue(bibQueue, parseInt(btn.dataset.idx)));
    });
    contentEl.querySelectorAll('.delete-track').forEach(btn => {
      btn.addEventListener('click', () => deleteTrack(btn.dataset.path));
    });
    contentEl.querySelectorAll('.card[data-path]').forEach(card => {
      card.style.cursor = 'pointer';
      card.addEventListener('click', (e) => {
        if (e.target.closest('.btn-icon') || e.target.closest('.btn')) return;
        openEditModal(card.dataset.path);
      });
    });
  }

  function setupBibSearch() {
    const input = document.getElementById('bibSearch');
    const missingTitle = document.getElementById('bibMissingTitle');
    const missingArtist = document.getElementById('bibMissingArtist');
    if (input) {
      input.addEventListener('input', () => {
        clearTimeout(_bibSearchTimer);
        _bibSearchTimer = setTimeout(() => fetchBibliotecaTracks(input.value), 300);
      });
    }
    if (missingTitle) {
      missingTitle.addEventListener('change', () => {
        _bibMissingTitle = missingTitle.checked;
        fetchBibliotecaTracks(input?.value || '');
      });
    }
    if (missingArtist) {
      missingArtist.addEventListener('change', () => {
        _bibMissingArtist = missingArtist.checked;
        fetchBibliotecaTracks(input?.value || '');
      });
    }
  }

  async function fetchBibliotecaTracks(query) {
    try {
      _bibQuery = query || '';
      const params = new URLSearchParams({ limit: '100' });
      if (_bibQuery) params.set('q', _bibQuery);
      if (_bibMissingTitle) params.set('missing_title', 'true');
      if (_bibMissingArtist) params.set('missing_artist', 'true');
      const url = `/api/tracks?${params.toString()}`;
      const tracks = await api.get(url);
      renderBibliotecaTable(Array.isArray(tracks) ? tracks : []);
    } catch (e) {
      contentEl.innerHTML = `<p class="placeholder">Erro ao carregar biblioteca: ${e.message}</p>`;
    }
  }

  async function loadBiblioteca() {
    contentEl.innerHTML = `
      <h2 style="margin-top:0;margin-bottom:20px;font-weight:700;">Biblioteca</h2>
      ${bibliotecaToolbarHtml()}
      <p class="placeholder">Carregando músicas...</p>
    `;
    await fetchBibliotecaTracks('');
  }

  async function openEditModal(rawPath, onSaved) {
    try {
      const track = await api.get(`/api/tracks/${encodeURIComponent(rawPath)}`);
      const encoded = encodeURIComponent(rawPath);
      const coverHtml = track.has_cover
        ? `<img src="/api/tracks/${encoded}/cover" alt="Capa" style="width:120px;height:120px;object-fit:cover;border-radius:8px;margin-bottom:12px;">`
        : `<div style="width:120px;height:120px;border-radius:8px;background:var(--border);display:flex;align-items:center;justify-content:center;font-size:2.5rem;color:var(--text-secondary);margin-bottom:12px;">&#9835;</div>`;

      const modalHtml = `
        <div class="modal-overlay show" id="editModal">
          <div class="modal-box" style="min-width:340px;max-width:420px;">
            <button class="modal-close" id="editModalClose">&#10005;</button>
            ${coverHtml}
            <h3 style="margin:0 0 16px;font-weight:700;">Editar Faixa</h3>
            <div style="display:flex;flex-direction:column;gap:10px;">
              <label style="font-size:0.8rem;font-weight:600;color:var(--text-secondary);">Título
                <input class="inline-input" id="editTitle" value="${esc(track.title || '')}" style="margin-top:4px;">
              </label>
              <label style="font-size:0.8rem;font-weight:600;color:var(--text-secondary);">Artista
                <input class="inline-input" id="editArtist" value="${esc(track.artist || '')}" style="margin-top:4px;">
              </label>
              <label style="font-size:0.8rem;font-weight:600;color:var(--text-secondary);">Álbum
                <input class="inline-input" id="editAlbum" value="${esc(track.album || '')}" style="margin-top:4px;">
              </label>
              <label style="font-size:0.8rem;font-weight:600;color:var(--text-secondary);">Gênero
                <input class="inline-input" id="editGenre" value="${esc(track.genre || '')}" style="margin-top:4px;">
              </label>
              <label style="font-size:0.8rem;font-weight:600;color:var(--text-secondary);">Ano
                <input class="inline-input" id="editYear" type="number" value="${track.year || ''}" style="margin-top:4px;">
              </label>
            </div>
            <div style="display:flex;gap:8px;margin-top:18px;justify-content:flex-end;">
              <button class="btn" style="background:var(--danger);color:#fff;" id="editDelete">&#128465; Excluir</button>
              <button class="btn btn-primary" id="editSave">&#10003; Salvar</button>
            </div>
          </div>
        </div>
      `;

      document.body.insertAdjacentHTML('beforeend', modalHtml);

      document.getElementById('editModalClose').addEventListener('click', () => closeModal());
      document.getElementById('editModal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeModal();
      });

      document.getElementById('editSave').addEventListener('click', async () => {
        const body = {};
        const titleVal = document.getElementById('editTitle').value;
        const artistVal = document.getElementById('editArtist').value;
        const albumVal = document.getElementById('editAlbum').value;
        const genreVal = document.getElementById('editGenre').value;
        const yearVal = document.getElementById('editYear').value;
        body.title = titleVal;
        body.artist = artistVal;
        body.album = albumVal;
        body.genre = genreVal;
        if (yearVal) body.year = parseInt(yearVal, 10);
        try {
          await api.put(`/api/tracks/${encodeURIComponent(rawPath)}`, body);
          closeModal();
          if (typeof onSaved === 'function') {
            onSaved();
          } else if (document.getElementById('bibSearch')) {
            fetchBibliotecaTracks(document.getElementById('bibSearch')?.value || '');
          }
        } catch (e) {
          alert('Erro ao salvar: ' + e.message);
        }
      });

      document.getElementById('editDelete').addEventListener('click', async () => {
        if (confirm('Tem certeza que deseja excluir esta faixa?')) {
          try {
            await api.del(`/api/tracks/${encodeURIComponent(rawPath)}`);
            closeModal();
            fetchBibliotecaTracks(document.getElementById('bibSearch')?.value || '');
          } catch (e) {
            alert('Erro ao excluir: ' + e.message);
          }
        }
      });
    } catch (e) {
      alert('Erro ao carregar faixa: ' + e.message);
    }
  }

  function closeModal() {
    const modal = document.getElementById('editModal');
    if (modal) modal.remove();
  }

  async function deleteTrack(rawPath) {
    if (!confirm('Tem certeza que deseja excluir esta faixa?')) return;
    try {
      await api.del(`/api/tracks/${encodeURIComponent(rawPath)}`);
      fetchBibliotecaTracks(document.getElementById('bibSearch')?.value || '');
    } catch (e) {
      alert('Erro ao excluir: ' + e.message);
    }
  }

  let _plSearchTimer = null;
  let _currentPlaylistPath = null;
  let _youtubePollTimers = {};

  function formatPlaylistDate(mtime) {
    if (!mtime) return '--';
    const d = new Date(mtime * 1000);
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' });
  }

  async function fetchPlaylists() {
    const data = await api.get('/api/playlists');
    console.log('[DEBUG] fetchPlaylists response:', data);
    return Array.isArray(data) ? data : [];
  }

  async function fetchPlaylistDetail(path) {
    return api.get(`/api/playlists/${encodeURIComponent(path)}`);
  }

  async function renderPlaylistList() {
    contentEl.innerHTML = `
      <h2 style="margin-top:0;margin-bottom:20px;font-weight:700;">Playlists</h2>
      <p class="placeholder">Carregando...</p>
    `;
    try {
      const playlists = await fetchPlaylists();
      _currentPlaylistPath = null;

      if (!playlists.length) {
        contentEl.innerHTML = `
          <h2 style="margin-top:0;margin-bottom:20px;font-weight:700;">Playlists</h2>
          <p class="placeholder" style="text-align:center;padding:48px 0;">&#128191; Nenhuma playlist criada ainda.</p>
          <div style="text-align:center;"><button class="btn btn-primary" id="plCreateBtn">&#43; Nova Playlist</button></div>
        `;
        document.getElementById('plCreateBtn').addEventListener('click', createPlaylist);
        return;
      }

      const cards = playlists.map(pl => {
        const enc = encodeURIComponent(pl.path);
        return `<div class="card" style="cursor:pointer;padding:16px 20px;" data-plpath="${enc}">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <p style="margin:0 0 4px;font-weight:700;font-size:1.05rem;">${esc(pl.name)}</p>
              <p style="margin:0;font-size:0.85rem;color:var(--text-secondary);">${pl.track_count || 0} faixas &middot; ${formatPlaylistDate(pl.mtime)}</p>
            </div>
            <span style="font-size:1.3rem;color:var(--accent);">&#128193;</span>
          </div>
        </div>`;
      }).join('');

      contentEl.innerHTML = `
        <h2 style="margin-top:0;margin-bottom:20px;font-weight:700;">Playlists</h2>
        <div style="margin-bottom:20px;"><button class="btn btn-primary" id="plCreateBtn">&#43; Nova Playlist</button></div>
        <div class="cards-grid">${cards}</div>
      `;
      document.getElementById('plCreateBtn').addEventListener('click', createPlaylist);
      contentEl.querySelectorAll('[data-plpath]').forEach(card => {
        card.addEventListener('click', () => openPlaylistDetail(card.dataset.plpath));
      });
    } catch (e) {
      console.error('[DEBUG] renderPlaylistList error:', e);
      contentEl.innerHTML = `<p class="placeholder">Erro ao carregar playlists: ${esc(e.message)}</p>`;
    }
  }

  async function createPlaylist() {
    const name = prompt('Nome da nova playlist:');
    if (!name || !name.trim()) return;
    try {
      await api.post('/api/playlists', { name: name.trim() });
      renderPlaylistList();
    } catch (e) {
      alert('Erro ao criar playlist: ' + e.message);
    }
  }

  async function openPlaylistDetail(pathEnc) {
    _currentPlaylistPath = pathEnc;
    await renderPlaylistDetail(pathEnc);
  }

  async function renderPlaylistDetail(pathEnc) {
    contentEl.innerHTML = `
      <h2 style="margin-top:0;margin-bottom:20px;font-weight:700;">Carregando playlist...</h2>
    `;
    try {
      const data = await fetchPlaylistDetail(pathEnc);
      const pl = data.playlist;
      const tracks = data.tracks || [];

      const enc = encodeURIComponent(pl.path);

      contentEl.innerHTML = `
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;">
          <button class="btn" id="plBackBtn" style="background:var(--surface);border:1px solid var(--border);">&#8592; Voltar</button>
          <h2 style="margin:0;font-weight:700;flex:1;" id="plNameDisplay">${esc(pl.name)}</h2>
          <button class="btn" id="plRenameBtn" style="background:var(--surface);border:1px solid var(--border);">&#9998; Renomear</button>
        </div>

        <div style="margin-bottom:24px;">
          <h3 style="margin:0 0 10px;font-weight:600;font-size:1rem;">Adicionar Faixa</h3>
          <div class="toolbar" style="margin-bottom:0;">
            <input type="text" class="search-input" id="plTrackSearch" placeholder="Buscar na biblioteca...">
          </div>
          <div id="plTrackResults" style="margin-top:8px;"></div>
        </div>

        ${tracks.length ? `
        <div style="display:flex;align-items:center;gap:12px;margin:0 0 10px;">
          <h3 style="margin:0;font-weight:600;font-size:1rem;">Faixas (${tracks.length})</h3>
          <button class="btn btn-primary" id="plPlayAll" style="padding:4px 14px;font-size:0.85rem;">&#9654; Tocar todas</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th style="width:50px;">#</th>
                <th>Título</th>
                <th>Artista</th>
                <th>Duração</th>
                <th style="width:140px;">Ações</th>
              </tr>
            </thead>
            <tbody>
              ${tracks.map((t, i) => `<tr>
                <td>${i + 1}</td>
                <td>${esc(t.title) || '<em style="color:var(--text-secondary)">' + esc(t.path) + '</em>'}</td>
                <td>${esc(t.artist) || '--'}</td>
                <td>${formatDuration(t.duration)}</td>
                <td>
                  <div class="actions">
<button class="btn-icon pl-play" title="Tocar" data-idx="${i}">&#9654;</button>
                    <button class="btn-icon" title="Mover para cima" data-action="up" data-pos="${i}" ${i === 0 ? 'disabled style="opacity:0.3;pointer-events:none;"' : ''}>&#8593;</button>
                    <button class="btn-icon" title="Mover para baixo" data-action="down" data-pos="${i}" ${i === tracks.length - 1 ? 'disabled style="opacity:0.3;pointer-events:none;"' : ''}>&#8595;</button>
                    <button class="btn-icon delete" title="Remover" data-action="remove" data-pos="${i}">&#10005;</button>
                  </div>
                </td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>
        ` : `<p class="placeholder" style="text-align:center;padding:24px 0;">&#127925; Esta playlist está vazia. Adicione músicas acima.</p>`}

        <div style="margin-top:28px;padding-top:16px;border-top:1px solid var(--border);">
          <button class="btn" id="plDeleteBtn" style="background:var(--danger);color:#fff;">&#128465; Excluir Playlist</button>
        </div>
      `;

      document.getElementById('plBackBtn').addEventListener('click', () => renderPlaylistList());
      document.getElementById('plRenameBtn').addEventListener('click', () => renamePlaylist(pl.path));
      document.getElementById('plDeleteBtn').addEventListener('click', () => deletePlaylist(pl.path));

      const queue = tracks.map(t => ({ path: t.path, title: t.title || t.path, artist: t.artist || '', has_cover: t.has_cover }));
      document.getElementById('plPlayAll').addEventListener('click', () => playQueue(queue, 0));
      contentEl.querySelectorAll('.pl-play').forEach(btn => {
        btn.addEventListener('click', () => playQueue(queue, parseInt(btn.dataset.idx)));
      });
      contentEl.querySelectorAll('[data-action="up"]').forEach(btn => btn.addEventListener('click', () => moveTrack(pl.path, parseInt(btn.dataset.pos), -1)));
      contentEl.querySelectorAll('[data-action="down"]').forEach(btn => btn.addEventListener('click', () => moveTrack(pl.path, parseInt(btn.dataset.pos), 1)));
      contentEl.querySelectorAll('[data-action="remove"]').forEach(btn => btn.addEventListener('click', () => removeTrackFromPlaylist(pl.path, parseInt(btn.dataset.pos))));

      const searchInput = document.getElementById('plTrackSearch');
      searchInput.addEventListener('input', () => {
        clearTimeout(_plSearchTimer);
        _plSearchTimer = setTimeout(() => searchTracksForPlaylist(searchInput.value, pl.path), 300);
      });
    } catch (e) {
      contentEl.innerHTML = `<p class="placeholder">Erro ao carregar playlist: ${e.message}</p>`;
    }
  }

  async function renamePlaylist(plPath) {
    const newName = prompt('Novo nome para a playlist:', plPath.replace(/\.(m3u8|m3u)$/i, ''));
    if (!newName || !newName.trim()) return;
    try {
      await api.put(`/api/playlists/${encodeURIComponent(plPath)}`, { name: newName.trim() });
      renderPlaylistDetail(_currentPlaylistPath);
    } catch (e) {
      alert('Erro ao renomear: ' + e.message);
    }
  }

  async function deletePlaylist(plPath) {
    if (!confirm('Tem certeza que deseja excluir esta playlist?')) return;
    try {
      await api.del(`/api/playlists/${encodeURIComponent(plPath)}`);
      _currentPlaylistPath = null;
      renderPlaylistList();
    } catch (e) {
      alert('Erro ao excluir playlist: ' + e.message);
    }
  }

  async function moveTrack(plPath, pos, direction) {
    try {
      const data = await fetchPlaylistDetail(_currentPlaylistPath);
      const tracks = data.tracks || [];
      const trackPaths = tracks.map(t => t.path);
      const newPos = pos + direction;
      if (newPos < 0 || newPos >= trackPaths.length) return;
      const moved = trackPaths.splice(pos, 1)[0];
      trackPaths.splice(newPos, 0, moved);
      await api.put(`/api/playlists/${encodeURIComponent(plPath)}`, { track_order: trackPaths });
      renderPlaylistDetail(_currentPlaylistPath);
    } catch (e) {
      alert('Erro ao reordenar: ' + e.message);
    }
  }

  async function removeTrackFromPlaylist(plPath, pos) {
    try {
      await api.del(`/api/playlists/${encodeURIComponent(plPath)}/tracks/${pos}`);
      renderPlaylistDetail(_currentPlaylistPath);
    } catch (e) {
      alert('Erro ao remover faixa: ' + e.message);
    }
  }

  async function searchTracksForPlaylist(query, plPath) {
    const resultsDiv = document.getElementById('plTrackResults');
    if (!resultsDiv) return;
    if (!query.trim()) { resultsDiv.innerHTML = ''; return; }
    resultsDiv.innerHTML = '<p style="font-size:0.85rem;color:var(--text-secondary);">Buscando...</p>';
    try {
      const tracks = await api.get(`/api/tracks?q=${encodeURIComponent(query)}&limit=50`);
      const trackList = Array.isArray(tracks) ? tracks : [];
      if (!trackList.length) {
        resultsDiv.innerHTML = '<p style="font-size:0.85rem;color:var(--text-secondary);">Nenhuma faixa encontrada.</p>';
        return;
      }
      resultsDiv.innerHTML = trackList.slice(0, 10).map(t =>
        `<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:6px 10px;border:1px solid var(--border);border-radius:8px;margin-bottom:4px;font-size:0.9rem;">
          <div style="min-width:0;cursor:pointer;" data-addpath="${esc(t.path)}">
            <strong>${esc(t.title) || esc(t.path)}</strong> ${t.artist ? '&mdash; ' + esc(t.artist) : ''}
          </div>
          <button class="btn-icon play-track" title="Tocar" data-path="${esc(t.path)}" data-label="${esc(trackLabel(t))}">&#9654;</button>
        </div>`
      ).join('');
      resultsDiv.querySelectorAll('.play-track').forEach(btn => {
        btn.addEventListener('click', () => playTrack(btn.dataset.path, btn.dataset.label));
      });
      resultsDiv.querySelectorAll('[data-addpath]').forEach(div => {
        div.addEventListener('click', () => addTrackToPlaylist(plPath, div.dataset.addpath));
      });
    } catch (e) {
      resultsDiv.innerHTML = '<p style="font-size:0.85rem;color:var(--danger);">Erro na busca.</p>';
    }
  }

  async function addTrackToPlaylist(plPath, trackPath) {
    try {
      await api.post(`/api/playlists/${encodeURIComponent(plPath)}/tracks`, { track_path: trackPath });
      renderPlaylistDetail(_currentPlaylistPath);
    } catch (e) {
      alert('Erro ao adicionar faixa: ' + e.message);
    }
  }

  async function loadPlaylists() {
    console.log('[DEBUG] loadPlaylists called');
    await renderPlaylistList();
  }

  function loadAdicionar() {
    // Clear any active youtube polls when re-entering
    Object.values(_youtubePollTimers).forEach(clearInterval);
    _youtubePollTimers = {};

    contentEl.innerHTML = `
      <style>
        @keyframes spin { to { transform: rotate(360deg); } }
        .tab-btn { border-radius: 10px 10px 0 0; }
        .tab-btn.inactive { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
        .drop-zone { border: 2px dashed var(--border); border-radius: var(--radius); padding: 40px 20px; text-align: center; color: var(--text-secondary); cursor: pointer; transition: background 0.2s, border-color 0.2s; }
        .drop-zone.dragover { background: rgba(99,102,241,0.08); border-color: var(--accent); }
        .spinner { display: inline-block; width: 18px; height: 18px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: middle; margin-left: 8px; }
        .job-item { padding: 10px 14px; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; background: var(--surface); }
        .job-status { font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.4px; }
        .job-status.completed { color: var(--success); }
        .job-status.failed { color: var(--danger); }
        .job-status.running { color: var(--accent); }
        .job-status.queued { color: var(--text-secondary); }
      </style>
      <h2 style="margin-top:0;margin-bottom:20px;font-weight:700;">Adicionar Músicas</h2>
      <div style="display:flex;gap:8px;margin-bottom:20px;border-bottom:1px solid var(--border);">
        <button class="btn btn-primary tab-btn" id="tabUpload">Upload de Arquivos</button>
        <button class="btn tab-btn inactive" id="tabYouTube">YouTube</button>
      </div>
      <div id="tabContent"></div>
    `;

    const tabUploadBtn = document.getElementById('tabUpload');
    const tabYouTubeBtn = document.getElementById('tabYouTube');

    function switchTab(tab) {
      if (tab === 'upload') {
        tabUploadBtn.classList.add('btn-primary');
        tabUploadBtn.classList.remove('inactive');
        tabYouTubeBtn.classList.remove('btn-primary');
        tabYouTubeBtn.classList.add('inactive');
        renderUploadTab();
      } else {
        tabYouTubeBtn.classList.add('btn-primary');
        tabYouTubeBtn.classList.remove('inactive');
        tabUploadBtn.classList.remove('btn-primary');
        tabUploadBtn.classList.add('inactive');
        renderYouTubeTab();
      }
    }

    tabUploadBtn.addEventListener('click', () => switchTab('upload'));
    tabYouTubeBtn.addEventListener('click', () => switchTab('youtube'));

    function renderUploadTab() {
      const tabContentEl = document.getElementById('tabContent');
      tabContentEl.innerHTML = `
        <div class="drop-zone" id="dropZone">
          <p style="font-size:1.5rem;margin:0 0 8px;">&#128194;</p>
          <p style="margin:0;font-weight:500;">Arraste e solte arquivos MP3 aqui</p>
          <p style="margin:6px 0 0;font-size:0.85rem;">ou clique para selecionar</p>
          <input type="file" id="fileInput" multiple accept=".mp3,audio/mpeg" style="display:none;">
        </div>
        <div id="fileList" style="margin:16px 0;"></div>
        <label style="display:block;font-size:0.85rem;font-weight:600;color:var(--text-secondary);max-width:600px;margin-bottom:12px;">
          Subpasta em Musics/ (opcional)
          <input type="text" class="search-input" id="uploadTargetDir" placeholder="ex: Rock/Shows" style="margin-top:6px;width:100%;">
        </label>
        <button class="btn btn-primary" id="uploadBtn" disabled>Enviar Arquivos</button>
        <div id="uploadStatus" style="margin-top:16px;display:none;">
          <p style="color:var(--text-secondary);">Enviando...<span class="spinner"></span></p>
        </div>
        <div id="uploadResults" style="margin-top:20px;"></div>
      `;

      const dropZone = document.getElementById('dropZone');
      const fileInput = document.getElementById('fileInput');
      const fileListEl = document.getElementById('fileList');
      const uploadTargetDir = document.getElementById('uploadTargetDir');
      const uploadBtn = document.getElementById('uploadBtn');
      const uploadStatus = document.getElementById('uploadStatus');
      const uploadResults = document.getElementById('uploadResults');

      let selectedFiles = [];

      function updateFileList() {
        if (!selectedFiles.length) {
          fileListEl.innerHTML = '';
          uploadBtn.disabled = true;
          return;
        }
        fileListEl.innerHTML = `<ul style="margin:0;padding-left:18px;color:var(--text);">
          ${selectedFiles.map(f => `<li>${esc(f.name)}</li>`).join('')}
        </ul>`;
        uploadBtn.disabled = false;
      }

      dropZone.addEventListener('click', () => fileInput.click());

      dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
      });
      dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
      });
      dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        const files = Array.from(e.dataTransfer.files).filter(f => f.name.toLowerCase().endsWith('.mp3'));
        if (files.length) {
          selectedFiles = files;
          updateFileList();
        }
      });

      fileInput.addEventListener('change', () => {
        selectedFiles = Array.from(fileInput.files);
        updateFileList();
      });

      uploadBtn.addEventListener('click', async () => {
        if (!selectedFiles.length) return;
        uploadStatus.style.display = 'block';
        uploadResults.innerHTML = '';
        uploadBtn.disabled = true;

        const formData = new FormData();
        selectedFiles.forEach(file => formData.append('files', file));
        const targetDir = uploadTargetDir.value.trim();
        if (targetDir) formData.append('target_dir', targetDir);

        try {
          const res = await fetch('/api/upload', {
            method: 'POST',
            body: formData,
          });
          if (!res.ok) {
            const text = await res.text().catch(() => '');
            throw new Error(`HTTP ${res.status}: ${text}`);
          }
          const tracks = await res.json();
          uploadStatus.style.display = 'none';
          if (Array.isArray(tracks) && tracks.length) {
            uploadResults.innerHTML = `
              <div class="card" style="padding:16px;">
                <p style="margin:0 0 10px;font-weight:600;color:var(--success);">&#10003; Upload concluído (${tracks.length} arquivo(s))</p>
                <ul style="margin:0;padding-left:18px;">
                  ${tracks.map(t => `<li>${esc(t.title || t.path)} ${t.artist ? '&mdash; ' + esc(t.artist) : ''}<br><span style="color:var(--text-secondary);font-size:0.8rem;">${esc(t.path)}</span></li>`).join('')}
                </ul>
              </div>
            `;
          } else {
            uploadResults.innerHTML = `<p style="color:var(--success);">Upload concluído.</p>`;
          }
          selectedFiles = [];
          fileInput.value = '';
          updateFileList();
        } catch (e) {
          uploadStatus.style.display = 'none';
          uploadResults.innerHTML = `<p style="color:var(--danger);">Erro no upload: ${esc(e.message)}</p>`;
          uploadBtn.disabled = false;
        }
      });
    }

    function renderYouTubeTab() {
      const tabContentEl = document.getElementById('tabContent');
      tabContentEl.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:14px;max-width:600px;">
          <label style="font-size:0.85rem;font-weight:600;color:var(--text-secondary);">
            URL do YouTube
            <input type="text" class="search-input" id="ytUrl" placeholder="https://www.youtube.com/watch?v=..." style="margin-top:6px;">
          </label>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.95rem;">
            <input type="checkbox" id="ytPlaylist" style="width:18px;height:18px;accent-color:var(--accent);">
            Criar playlist local
          </label>
          <label style="font-size:0.85rem;font-weight:600;color:var(--text-secondary);">
            Subpasta em Musics/ (opcional)
            <input type="text" class="search-input" id="ytTargetDir" placeholder="ex: Rock/Shows" style="margin-top:6px;">
          </label>
          <button class="btn btn-primary" id="ytDownloadBtn" style="align-self:flex-start;">Baixar</button>
        </div>
        <div id="ytStatus" style="margin-top:20px;"></div>
        <h3 style="margin:28px 0 12px;font-weight:600;font-size:1rem;">Downloads Recentes</h3>
        <div id="ytRecentJobs"></div>
      `;

      const ytUrl = document.getElementById('ytUrl');
      const ytPlaylist = document.getElementById('ytPlaylist');
      const ytTargetDir = document.getElementById('ytTargetDir');
      const ytDownloadBtn = document.getElementById('ytDownloadBtn');
      const ytStatus = document.getElementById('ytStatus');
      const ytRecentJobs = document.getElementById('ytRecentJobs');

      async function fetchRecentJobs() {
        try {
          const jobs = await api.get('/api/youtube/jobs');
          renderJobs(Array.isArray(jobs) ? jobs : []);
        } catch (e) {
          ytRecentJobs.innerHTML = `<p style="color:var(--text-secondary);font-size:0.9rem;">Não foi possível carregar jobs recentes.</p>`;
        }
      }

      function renderJobs(jobs) {
        if (!jobs.length) {
          ytRecentJobs.innerHTML = `<p style="color:var(--text-secondary);font-size:0.9rem;">Nenhum download recente.</p>`;
          return;
        }
        ytRecentJobs.innerHTML = jobs.slice(0, 10).map(renderJobCard).join('');
        bindYouTubeJobActions(ytRecentJobs);
      }

      function renderJobCard(job) {
        return `
          <div class="job-item">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
              <span class="job-status ${job.status}">${job.status}</span>
              <span style="font-size:0.8rem;color:var(--text-secondary);">${job.progress || 0}%</span>
            </div>
            <p style="margin:0;font-size:0.9rem;word-break:break-word;">${esc(job.message || '')}</p>
            ${renderDownloadedTracks(job.tracks)}
          </div>
        `;
      }

      function bindYouTubeJobActions(root) {
        root.querySelectorAll('.yt-play-track').forEach(btn => {
          btn.addEventListener('click', () => playTrack(btn.dataset.path, btn.dataset.label));
        });
        root.querySelectorAll('.yt-edit-track').forEach(btn => {
          btn.addEventListener('click', () => openEditModal(btn.dataset.path, fetchRecentJobs));
        });
      }

      function pollJob(jobId) {
        if (_youtubePollTimers[jobId]) return;
        _youtubePollTimers[jobId] = setInterval(async () => {
          try {
            const job = await api.get(`/api/youtube/jobs/${jobId}`);
            const statusEl = document.getElementById(`job-status-${jobId}`);
            if (statusEl) {
              statusEl.innerHTML = renderJobCard(job);
              bindYouTubeJobActions(statusEl);
            }
            if (job.status === 'completed' || job.status === 'failed') {
              clearInterval(_youtubePollTimers[jobId]);
              delete _youtubePollTimers[jobId];
              ytDownloadBtn.disabled = false;
              fetchRecentJobs();
            }
          } catch (e) {
            // ignore poll errors
          }
        }, 3000);
      }

      ytDownloadBtn.addEventListener('click', async () => {
        const url = ytUrl.value.trim();
        if (!url) {
          alert('Informe a URL do YouTube.');
          return;
        }
        ytDownloadBtn.disabled = true;
        ytStatus.innerHTML = '<p style="color:var(--text-secondary);">Enviando...<span class="spinner"></span></p>';

        try {
          const job = await api.post('/api/youtube/download', {
            url,
            as_playlist: ytPlaylist.checked,
            target_dir: ytTargetDir.value.trim() || undefined,
          });
          ytUrl.value = '';
          ytStatus.innerHTML = `<div id="job-status-${job.id}"></div>`;
          pollJob(job.id);
          fetchRecentJobs();
        } catch (e) {
          ytStatus.innerHTML = `<p style="color:var(--danger);">Erro: ${esc(e.message)}</p>`;
          ytDownloadBtn.disabled = false;
        }
      });

      fetchRecentJobs();
    }

    switchTab('upload');
  }

  const routes = {
    '#dashboard': loadDashboard,
    '#biblioteca': loadBiblioteca,
    '#playlists': loadPlaylists,
    '#adicionar': loadAdicionar,
  };

  function navigate() {
    const hash = window.location.hash || '#dashboard';
    setActiveLink(hash);
    if (hash !== '#adicionar') {
      Object.values(_youtubePollTimers).forEach(clearInterval);
      _youtubePollTimers = {};
    }
    const view = routes[hash] || loadDashboard;
    view();
    if (window.innerWidth <= 768) closeSidebar();
  }

  function init() {
    initTheme();
    navigate();

    window.addEventListener('hashchange', navigate);
    hamburgerEl.addEventListener('click', openSidebar);
    overlayEl.addEventListener('click', closeSidebar);
    themeToggleEl.addEventListener('click', toggleTheme);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
