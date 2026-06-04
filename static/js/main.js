/* ── Trailer Modal ─────────────────────────────────────────── */
const modal    = document.getElementById('trailer-modal');
const iframe   = document.getElementById('trailer-iframe');
const closeBtn = document.getElementById('modal-close');
const backdrop = document.getElementById('modal-backdrop');

function openTrailer(videoId) {
  iframe.src = `https://www.youtube.com/embed/${videoId}?autoplay=1&rel=0`;
  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
  iframe.src = '';
  document.body.style.overflow = '';
}

document.querySelectorAll('.trailer-btn').forEach(btn => {
  btn.addEventListener('click', () => openTrailer(btn.dataset.trailer));
});

closeBtn  && closeBtn.addEventListener('click', closeModal);
backdrop  && backdrop.addEventListener('click', closeModal);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

/* ── Assistido Por ────────────────────────────────────────── */
const assistidosList = document.getElementById('assistidos-list');
const watchToggle    = document.getElementById('watch-toggle');

function loadAssistidos() {
  const imdbId = (watchToggle || document.querySelector('[data-imdb]'))?.dataset?.imdb
              || document.querySelector('[data-trailer]')?.closest('[data-imdb]')?.dataset?.imdb;
  // get imdb_id from the page URL
  const pathParts = window.location.pathname.split('/');
  const id = pathParts[pathParts.length - 1];
  if (!assistidosList || !id) return;

  fetch(`/api/assistidos/${id}`)
    .then(r => r.ok ? r.json() : [])
    .then(rows => {
      if (!rows.length) {
        assistidosList.innerHTML = '<span class="assistidos-empty">Nenhum registro ainda.</span>';
        return;
      }
      const fallbackAvatar = (uid) =>
        `https://cdn.discordapp.com/embed/avatars/${(BigInt(uid) >> 22n) % 6n}.png`;
      assistidosList.innerHTML = rows.map(u => {
        const av = u.avatar_url || fallbackAvatar(u.user_id);
        return `
        <div class="assistido-item" title="${u.display_name || u.username}">
          <img src="${av}" alt="${u.username}" loading="lazy"
               onerror="this.onerror=null;this.src='${fallbackAvatar(u.user_id)}'" />
          <span>${u.display_name || u.username}</span>
          <span class="assistido-source assistido-source--${u.source}">${u.source === 'evento' ? '📅' : '✓'}</span>
        </div>`;
      }).join('');
    })
    .catch(() => { assistidosList.innerHTML = ''; });
}

if (assistidosList) loadAssistidos();

/* ── Adicionado à Lista Por ───────────────────────────────── */
const adicionadoList = document.getElementById('adicionado-list');

function loadAdicionadoPor() {
  const pathParts = window.location.pathname.split('/');
  const id = pathParts[pathParts.length - 1];
  if (!adicionadoList || !id) return;

  fetch(`/api/fila/adicionado-por/${id}`)
    .then(r => r.ok ? r.json() : null)
    .then(row => {
      if (!row) {
        adicionadoList.innerHTML =
          '<span class="assistidos-empty">Este filme ainda não está na lista do grupo.</span>';
        return;
      }
      const nome = row.display_name || row.username || 'Usuário';
      adicionadoList.innerHTML = `
        <div class="assistido-item" title="${nome}">
          <img src="${row.avatar_url}" alt="${nome}" />
          <span>${nome}</span>
          ${row.na_fila ? '<span class="assistido-source assistido-source--fila">📋</span>' : ''}
        </div>
      `;
    })
    .catch(() => { adicionadoList.innerHTML = ''; });
}

if (adicionadoList) loadAdicionadoPor();

if (watchToggle) {
  watchToggle.addEventListener('click', async () => {
    const imdbId  = watchToggle.dataset.imdb;
    const watched = watchToggle.dataset.watched === 'true';
    try {
      const r = await fetch('/api/assistido/toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ imdb_id: imdbId, titulo: watchToggle.dataset.titulo }),
      });
      if (r.status === 401) {
        window.location = `/auth/login?next=/filme/${imdbId}`;
        return;
      }
      const data = await r.json();
      watchToggle.dataset.watched = data.watched ? 'true' : 'false';
      watchToggle.textContent     = data.watched ? '✓ Já Vi' : '+ Marcar como Visto';
      watchToggle.classList.toggle('watch-toggle-btn--on', data.watched);
      loadAssistidos();
    } catch {}
  });
}

/* ── Fila de Filmes (adicionar / remover) ────────────────── */
const filaBtn = document.getElementById('fila-btn');

if (filaBtn) {
  filaBtn.addEventListener('click', async () => {
    const imdbId = filaBtn.dataset.imdb;
    const inFila = filaBtn.dataset.inFila === 'true';
    filaBtn.disabled = true;

    try {
      const endpoint = inFila ? '/api/fila/remover' : '/api/fila/adicionar';
      const r = await fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ imdb_id: imdbId, titulo: filaBtn.dataset.titulo }),
      });

      if (r.status === 401) {
        window.location = `/auth/login?next=/filme/${imdbId}`;
        return;
      }

      if (r.status === 403) {
        filaBtn.textContent = 'Você já assistiu este filme';
        filaBtn.classList.add('fila-btn--disabled');
        return;
      }

      const data = await r.json();
      if (data.in_fila) {
        filaBtn.dataset.inFila = 'true';
        filaBtn.classList.add('fila-btn--on');
        filaBtn.innerHTML = '&#10003; Na Fila &mdash; <span class="fila-btn__remove">Remover</span>';
        loadAdicionadoPor();
      } else {
        filaBtn.dataset.inFila = 'false';
        filaBtn.classList.remove('fila-btn--on');
        filaBtn.textContent = '+ Adicionar à Fila';
        if (adicionadoList) {
          adicionadoList.innerHTML =
            '<span class="assistidos-empty">Este filme ainda não está na lista do grupo.</span>';
        }
      }
    } catch { /* noop */ } finally {
      filaBtn.disabled = false;
    }
  });
}

/* ── Async poster loading (watchlist + assistidos cards) ─── */
document.addEventListener('DOMContentLoaded', () => {
  const BATCH = 4;
  const cards = Array.from(document.querySelectorAll('[data-imdb-id]'));
  if (!cards.length) return;

  let idx = 0;

  function loadNext() {
    if (idx >= cards.length) return;
    const card = cards[idx++];
    const id   = card.dataset.imdbId;

    fetch(`/api/filme/${id}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return;
        const img  = card.querySelector('.poster-img');
        const year = card.querySelector('.card-year');
        if (img && data.poster) {
          const tmp = new Image();
          tmp.onload = () => { img.src = data.poster; img.classList.add('loaded'); };
          tmp.src = data.poster;
        }
        if (year && data.ano) year.textContent = data.ano;
      })
      .catch(() => {})
      .finally(loadNext);
  }

  for (let i = 0; i < Math.min(BATCH, cards.length); i++) loadNext();
});

/* ── Busca na biblioteca (frontend) ─────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  const searchRoot = document.querySelector('[data-library-search]');
  const input      = document.getElementById('library-search-input');
  if (!searchRoot || !input) return;

  const goToSearchPage = () => {
    const query = input.value.trim();
    if (!query || query.length < 2) return;
    window.location.href = `/buscar?q=${encodeURIComponent(query)}`;
  };

  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    goToSearchPage();
  });
});
