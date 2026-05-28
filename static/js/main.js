/* ── Trailer — abre YouTube em nova aba ────────────────────── */
document.querySelectorAll('.trailer-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const q = encodeURIComponent(
      `${btn.dataset.title} ${btn.dataset.year} trailer legendado português`
    );
    window.open(`https://www.youtube.com/results?search_query=${q}`, '_blank', 'noopener');
  });
});

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
