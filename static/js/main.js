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
      assistidosList.innerHTML = rows.map(u => `
        <div class="assistido-item" title="${u.display_name || u.username}">
          <img src="${u.avatar_url}" alt="${u.username}" />
          <span>${u.display_name || u.username}</span>
          <span class="assistido-source assistido-source--${u.source}">${u.source === 'evento' ? '📅' : '✓'}</span>
        </div>
      `).join('');
    })
    .catch(() => { assistidosList.innerHTML = ''; });
}

if (assistidosList) loadAssistidos();

if (watchToggle) {
  watchToggle.addEventListener('click', async () => {
    const imdbId  = watchToggle.dataset.imdb;
    const watched = watchToggle.dataset.watched === 'true';
    try {
      const r = await fetch('/api/assistido/toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ imdb_id: imdbId }),
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
