/* ── Trailer Modal ─────────────────────────────────────────── */
const modal   = document.getElementById('trailer-modal');
const iframe  = document.getElementById('trailer-iframe');
const closeBtn  = document.getElementById('modal-close');
const backdrop  = document.getElementById('modal-backdrop');

function openTrailer(key) {
  iframe.src = `https://www.youtube.com/embed/${key}?autoplay=1&cc_load_policy=1&cc_lang_pref=pt&rel=0`;
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

/* ── Async poster loading (watchlist + assistidos cards) ─── */
document.addEventListener('DOMContentLoaded', () => {
  const BATCH = 4; // concurrent requests at a time
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
          tmp.onload = () => {
            img.src = data.poster;
            img.classList.add('loaded');
          };
          tmp.src = data.poster;
        }

        if (year && data.ano) year.textContent = data.ano;
      })
      .catch(() => {/* keep placeholder */})
      .finally(loadNext);
  }

  // Start BATCH parallel pipelines
  for (let i = 0; i < Math.min(BATCH, cards.length); i++) loadNext();
});
