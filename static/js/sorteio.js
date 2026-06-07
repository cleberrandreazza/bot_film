/* ── Sorteio da fila + criar evento (role Cinéfilo) ───────── */

const sorteioModal = document.getElementById('sorteio-modal');
const podeSorteio = document.body?.dataset?.podeSorteio === '1';

if (sorteioModal && podeSorteio) {
  const backdropEl = document.getElementById('sorteio-modal-backdrop');
  const closeBtn = document.getElementById('sorteio-modal-close');
  const againBtn = document.getElementById('sorteio-again-btn');
  const phaseEl = document.getElementById('sorteio-modal-phase');
  const titleEl = document.getElementById('sorteio-modal-title');
  const posterImg = document.getElementById('sorteio-poster');
  const posterFallback = document.getElementById('sorteio-poster-fallback');
  const filmTitleEl = document.getElementById('sorteio-film-title');
  const filmYearEl = document.getElementById('sorteio-film-year');
  const resultActions = document.getElementById('sorteio-result-actions');
  const posterLink = document.getElementById('sorteio-poster-link');
  const errorEl = document.getElementById('sorteio-error');
  const eventoForm = document.getElementById('sorteio-evento-form');
  const eventoData = document.getElementById('sorteio-evento-data');
  const dateSelect = document.getElementById('sorteio-date-select');
  const dateTrigger = document.getElementById('sorteio-date-trigger');
  const dateValue = document.getElementById('sorteio-date-value');
  const dateList = document.getElementById('sorteio-date-list');
  const eventoHora = document.getElementById('sorteio-evento-hora');
  const timeSelect = document.getElementById('sorteio-time-select');
  const timeTrigger = document.getElementById('sorteio-time-trigger');
  const timeValue = document.getElementById('sorteio-time-value');
  const timeList = document.getElementById('sorteio-time-list');
  const eventoSubmit = document.getElementById('sorteio-evento-submit');
  const eventoSuccess = document.getElementById('sorteio-evento-success');
  const eventoTz = document.getElementById('sorteio-evento-tz');

  let poolSorteio = [];
  const cartazRemovidos = new Set();
  let vencedorAtual = null;
  let animando = false;
  let sorteioCancelado = false;
  let pickerLimites = null;
  const posterCache = new Map();
  const posterOk = new Map();

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function preloadPoster(url) {
    const u = (url || '').trim();
    if (!u) return Promise.resolve(false);
    if (posterCache.has(u)) return posterCache.get(u);

    const promessa = new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        posterOk.set(u, true);
        resolve(true);
      };
      img.onerror = () => {
        posterOk.set(u, false);
        resolve(false);
      };
      img.src = u;
    });
    posterCache.set(u, promessa);
    return promessa;
  }

  function esconderPoster() {
    posterImg.hidden = true;
    posterImg.removeAttribute('src');
    delete posterImg.dataset.loadedSrc;
    delete posterImg.dataset.loadingSrc;
    posterImg.classList.remove('is-flicker', 'is-loaded');
    posterFallback.hidden = true;
  }

  function mostrarPosterFallback(titulo) {
    esconderPoster();
    posterFallback.hidden = false;
    posterFallback.textContent = titulo;
  }

  function mostrarEstadoCarregando() {
    filmTitleEl.textContent = '';
    filmYearEl.textContent = '';
    posterFallback.hidden = false;
    posterImg.hidden = true;
    posterImg.removeAttribute('src');
    posterFallback.textContent = 'Preparando sorteio…';
  }

  function mostrarFilme(filme, flicker) {
    const titulo = filme.titulo || 'Sem título';
    filmTitleEl.textContent = titulo;
    filmYearEl.textContent = filme.ano ? String(filme.ano) : '';
    posterImg.classList.toggle('is-flicker', !!flicker);

    const url = (filme.poster || '').trim();
    if (!url) {
      mostrarPosterFallback(titulo);
      return;
    }

    posterImg.alt = titulo;

    if (posterImg.dataset.loadedSrc === url || posterOk.get(url) === true) {
      posterFallback.hidden = true;
      posterImg.src = url;
      posterImg.dataset.loadedSrc = url;
      posterImg.hidden = false;
      posterImg.classList.add('is-loaded');
      return;
    }

    if (posterOk.get(url) === false) {
      mostrarPosterFallback(titulo);
      return;
    }

    posterFallback.hidden = true;
    posterImg.hidden = true;
    posterImg.removeAttribute('src');
    posterImg.dataset.loadingSrc = url;

    preloadPoster(url).then((ok) => {
      if (sorteioCancelado || posterImg.dataset.loadingSrc !== url) return;
      if (!ok) {
        mostrarPosterFallback(titulo);
        return;
      }
      posterImg.src = url;
      posterImg.dataset.loadedSrc = url;
      delete posterImg.dataset.loadingSrc;
      posterImg.hidden = false;
      posterImg.classList.add('is-loaded');
    });
  }

  const SORTEIO_SPIN_MS = 140;
  const SORTEIO_EXTRA_APOS_JW_MS = 5000;

  function mostrarPassoAnimacao(pool, passo) {
    const ativos = poolParaAnimacao(pool);
    const lista = ativos.length ? ativos : pool;
    if (!lista.length) return;
    mostrarFilme(lista[passo % lista.length], true);
  }

  let listaHorariosPronta = false;
  let listaDatasPronta = false;
  let opcoesDatas = [];
  let opcoesHoras = [];

  function partesDataValor(dataStr) {
    const s = (dataStr || '').trim();
    if (s.includes('/')) {
      const [d, m, y] = s.split('/').map(Number);
      return { y, m: m - 1, d };
    }
    const [y, m, d] = s.split('-').map(Number);
    return { y, m: m - 1, d };
  }

  function fecharDropdown(elSelect, elList, elTrigger) {
    if (!elSelect || !elList || !elTrigger) return;
    elSelect.classList.remove('sorteio-dd-select--open');
    elList.hidden = true;
    elTrigger.setAttribute('aria-expanded', 'false');
  }

  function abrirDropdown(elSelect, elList, elTrigger) {
    if (!elSelect || !elList || !elTrigger) return;
    elSelect.classList.add('sorteio-dd-select--open');
    elList.hidden = false;
    elTrigger.setAttribute('aria-expanded', 'true');
    const selected = elList.querySelector('.sorteio-dd-select__option--selected');
    if (selected) selected.scrollIntoView({ block: 'nearest' });
  }

  function fecharTodosDropdowns() {
    fecharDropdown(dateSelect, dateList, dateTrigger);
    fecharDropdown(timeSelect, timeList, timeTrigger);
  }

  function atualizarRotuloDropdown(elValue, valor, placeholder) {
    if (!elValue) return;
    if (valor) {
      elValue.textContent = valor;
      elValue.classList.remove('sorteio-dd-select__value--placeholder');
    } else {
      elValue.textContent = placeholder;
      elValue.classList.add('sorteio-dd-select__value--placeholder');
    }
  }

  function marcarOpcaoDropdown(elList, valorIso) {
    if (!elList) return;
    elList.querySelectorAll('.sorteio-dd-select__option').forEach((el) => {
      const sel = el.dataset.value === valorIso;
      el.classList.toggle('sorteio-dd-select__option--selected', sel);
      el.setAttribute('aria-selected', sel ? 'true' : 'false');
    });
  }

  function htmlOpcaoDropdown(value, label) {
    return `
      <li
        class="sorteio-dd-select__option"
        role="option"
        data-value="${value}"
        tabindex="-1"
        aria-selected="false"
      >
        <span>${label}</span>
        <span class="sorteio-dd-select__option-check" aria-hidden="true"></span>
      </li>
    `;
  }

  function horaPara24h(timeStr) {
    const parts = (timeStr || '').trim().split(':');
    return { hh: Number(parts[0]), mm: Number(parts[1] || 0) };
  }

  function instanteBRT(dataStr, timeStr) {
    const { y, m, d } = partesDataValor(dataStr);
    const { hh, mm } = horaPara24h(timeStr);
    return new Date(Date.UTC(y, m, d, hh + 3, mm));
  }

  function horaParaApi(timeStr) {
    const { hh, mm } = horaPara24h(timeStr);
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  }

  function instanteEventoBRT(dataStr, timeStr) {
    const instante = instanteBRT(dataStr, timeStr);
    const { hh, mm } = horaPara24h(timeStr);
    if (hh === 0 && mm === 0 && instante <= new Date()) {
      return new Date(instante.getTime() + 24 * 60 * 60 * 1000);
    }
    return instante;
  }

  function dataHoraEventoValida() {
    if (!eventoData?.value || !eventoHora?.value) return false;
    return instanteEventoBRT(eventoData.value, eventoHora.value) > new Date();
  }

  function rotuloDataSelecionada(iso) {
    const item = opcoesDatas.find((d) => d.value === iso);
    return item ? item.label : iso;
  }

  function onCliqueOpcaoDropdown(e, selecionar) {
    e.preventDefault();
    e.stopPropagation();
    const opt = e.target.closest('.sorteio-dd-select__option');
    if (!opt?.dataset.value) return;
    selecionar(opt.dataset.value);
  }

  function selecionarData(iso) {
    if (!eventoData) return;
    eventoData.value = iso;
    atualizarRotuloDropdown(dateValue, rotuloDataSelecionada(iso), 'Escolha a data');
    marcarOpcaoDropdown(dateList, iso);
    fecharDropdown(dateSelect, dateList, dateTrigger);
    atualizarBotaoEvento();
  }

  function selecionarHorario(valor) {
    if (!eventoHora) return;
    eventoHora.value = valor;
    atualizarRotuloDropdown(timeValue, valor, 'Escolha o horário');
    marcarOpcaoDropdown(timeList, valor);
    fecharDropdown(timeSelect, timeList, timeTrigger);
    atualizarBotaoEvento();
  }

  function montarListaDatas() {
    if (!dateList || !opcoesDatas.length) return;
    dateList.innerHTML = opcoesDatas
      .map((d) => htmlOpcaoDropdown(d.value, d.label))
      .join('');
    if (listaDatasPronta) return;
    dateList.addEventListener('mousedown', (e) => e.preventDefault());
    dateList.addEventListener('click', (e) => onCliqueOpcaoDropdown(e, selecionarData));
    listaDatasPronta = true;
  }

  function montarListaHorarios() {
    if (!timeList || !opcoesHoras.length) return;
    timeList.innerHTML = opcoesHoras.map((h) => htmlOpcaoDropdown(h, h)).join('');
    if (listaHorariosPronta) return;
    timeList.addEventListener('mousedown', (e) => e.preventDefault());
    timeList.addEventListener('click', (e) => onCliqueOpcaoDropdown(e, selecionarHorario));
    listaHorariosPronta = true;
  }

  function resetSeletorData() {
    if (eventoData) eventoData.value = '';
    atualizarRotuloDropdown(dateValue, '', 'Escolha a data');
    marcarOpcaoDropdown(dateList, '');
    fecharDropdown(dateSelect, dateList, dateTrigger);
  }

  function resetSeletorHorario() {
    if (eventoHora) eventoHora.value = '';
    atualizarRotuloDropdown(timeValue, '', 'Escolha o horário');
    marcarOpcaoDropdown(timeList, '');
    fecharDropdown(timeSelect, timeList, timeTrigger);
  }

  function atualizarBotaoEvento() {
    if (!eventoSubmit || !eventoData || !eventoHora) return;
    eventoSubmit.disabled = !dataHoraEventoValida();
  }

  function resetCamposEvento() {
    resetSeletorData();
    resetSeletorHorario();
    atualizarBotaoEvento();
  }

  function resetEventoUi() {
    eventoForm.hidden = true;
    eventoSuccess.hidden = true;
    eventoSuccess.textContent = '';
    eventoSubmit.textContent = 'Criar sessão';
    resetCamposEvento();
  }

  function desativarLinkPoster() {
    if (!posterLink) return;
    posterLink.href = '#';
    posterLink.removeAttribute('target');
    posterLink.removeAttribute('rel');
    posterLink.setAttribute('aria-disabled', 'true');
    posterLink.setAttribute('tabindex', '-1');
    posterLink.classList.remove('sorteio-reel__link--active');
    posterLink.removeAttribute('aria-label');
  }

  function ativarLinkPoster(filmeId, titulo) {
    if (!posterLink) return;
    posterLink.href = `/filme/${encodeURIComponent(filmeId)}`;
    posterLink.target = '_blank';
    posterLink.rel = 'noopener noreferrer';
    posterLink.setAttribute('aria-disabled', 'false');
    posterLink.setAttribute('tabindex', '0');
    posterLink.classList.add('sorteio-reel__link--active');
    posterLink.setAttribute('aria-label', `Abrir ${titulo} em nova aba`);
  }

  function resetUi() {
    sorteioModal.classList.remove('sorteio-modal--spinning', 'sorteio-modal--winner');
    phaseEl.textContent = 'Sorteando…';
    titleEl.textContent = 'Na fila';
    resultActions.hidden = true;
    errorEl.hidden = true;
    errorEl.textContent = '';
    filmTitleEl.textContent = '';
    filmYearEl.textContent = '';
    esconderPoster();
    vencedorAtual = null;
    desativarLinkPoster();
    resetEventoUi();
  }

  function abrirModal() {
    sorteioModal.classList.add('open');
    sorteioModal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }

  function liberarBotoesSorteio() {
    document.querySelectorAll('[data-sorteio-open]').forEach((btn) => {
      btn.disabled = false;
    });
  }

  function fecharModal() {
    sorteioCancelado = true;
    animando = false;
    fecharTodosDropdowns();
    sorteioModal.classList.remove('open');
    sorteioModal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    resetUi();
    liberarBotoesSorteio();
  }

  async function sortearNoServidor() {
    const r = await fetch('/api/fila/sorteio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await r.json().catch(() => ({}));
    if (r.status === 401) {
      window.location = `/auth/login?next=${encodeURIComponent(window.location.pathname)}`;
      throw new Error('login');
    }
    if (r.status === 403) {
      throw new Error('Apenas membros com o cargo Cinéfilo podem sortear.');
    }
    if (!r.ok) {
      if (data.error === 'fila_vazia') throw new Error('A fila está vazia.');
      if (data.error === 'sem_elegiveis_evento') {
        throw new Error(
          data.message
            || 'Nenhum filme elegível (todos com sessão agendada/ativa no Discord).',
        );
      }
      throw new Error(data.message || 'Erro ao sortear.');
    }
    const pool = Array.isArray(data.pool) ? data.pool : [];
    if (!pool.length) throw new Error('A fila está vazia.');
    poolSorteio = pool;
    return pool;
  }

  function poolParaAnimacao(pool) {
    const ativos = pool.filter((f) => !cartazRemovidos.has(f.filme_id));
    return ativos.length ? ativos : pool;
  }

  function iniciarVerificacaoCartaz(pool) {
    cartazRemovidos.clear();
    return pool.map((filme) =>
      fetch('/api/fila/em-cartaz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filme_id: filme.filme_id,
          titulo: filme.titulo || '',
          ano: filme.ano != null ? String(filme.ano) : '',
        }),
      })
        .then((res) => res.json().catch(() => ({})))
        .then((data) => {
          if (data.em_cartaz) cartazRemovidos.add(filme.filme_id);
        })
        .catch(() => {}),
    );
  }

  function escolherVencedor(pool) {
    const elegiveis = pool.filter((f) => !cartazRemovidos.has(f.filme_id));
    if (!elegiveis.length) {
      throw new Error(
        'Nenhum candidato elegível (em cartaz ou ainda não lançado). Tente de novo em instantes.',
      );
    }
    return elegiveis[Math.floor(Math.random() * elegiveis.length)];
  }

  async function configurarPickersEvento() {
    if (!pickerLimites) {
      const r = await fetch('/api/evento/opcoes');
      if (!r.ok) throw new Error('Não foi possível carregar o calendário.');
      pickerLimites = await r.json();
    }
    if (eventoTz && pickerLimites.timezone_label) {
      eventoTz.textContent = pickerLimites.timezone_label;
    }
    opcoesDatas = Array.isArray(pickerLimites.datas) ? pickerLimites.datas : [];
    opcoesHoras = Array.isArray(pickerLimites.horas) ? pickerLimites.horas : [];
    montarListaDatas();
    montarListaHorarios();
    resetCamposEvento();
  }

  function mostrarResultado(vencedor) {
    vencedorAtual = vencedor;
    sorteioModal.classList.remove('sorteio-modal--spinning');
    resetEventoUi();
    sorteioModal.classList.add('sorteio-modal--winner');
    phaseEl.textContent = 'Escolhido';
    titleEl.textContent = 'Sorteado!';
    mostrarFilme(vencedor, false);
    posterImg.classList.remove('is-flicker');
    ativarLinkPoster(vencedor.filme_id, vencedor.titulo || 'filme');
    resultActions.hidden = false;
    eventoForm.hidden = false;
    configurarPickersEvento().catch((err) => {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    });
  }

  posterLink?.addEventListener('click', (e) => {
    if (posterLink.getAttribute('aria-disabled') === 'true') {
      e.preventDefault();
    }
  });

  async function rodarAnimacao() {
    sorteioCancelado = false;
    animando = true;
    resetUi();
    sorteioModal.classList.add('sorteio-modal--spinning');
    abrirModal();
    mostrarEstadoCarregando();

    document.querySelectorAll('[data-sorteio-open]').forEach((btn) => {
      btn.disabled = true;
    });

    try {
      const pool = await sortearNoServidor();
      if (sorteioCancelado) return;

      const verificacoesCartaz = iniciarVerificacaoCartaz(pool);
      const preloadProm = Promise.all(pool.map((f) => preloadPoster(f.poster)));
      const cartazPronto = Promise.all(verificacoesCartaz);

      let passo = 0;
      while (!sorteioCancelado) {
        const terminou = await Promise.race([
          cartazPronto.then(() => true),
          sleep(SORTEIO_SPIN_MS).then(() => false),
        ]);
        mostrarPassoAnimacao(pool, passo);
        passo += 1;
        if (terminou) break;
      }

      if (sorteioCancelado || !sorteioModal.classList.contains('open')) return;

      const fimExtra = Date.now() + SORTEIO_EXTRA_APOS_JW_MS;
      while (Date.now() < fimExtra && !sorteioCancelado) {
        mostrarPassoAnimacao(pool, passo);
        passo += 1;
        await sleep(SORTEIO_SPIN_MS);
      }

      if (sorteioCancelado || !sorteioModal.classList.contains('open')) return;

      await Promise.all([cartazPronto, preloadProm]);
      if (sorteioCancelado || !sorteioModal.classList.contains('open')) return;

      const vencedor = escolherVencedor(pool);
      mostrarFilme(vencedor, false);
      mostrarResultado(vencedor);
    } catch (err) {
      if (err.message === 'login') return;
      sorteioModal.classList.remove('sorteio-modal--spinning');
      phaseEl.textContent = 'Ops';
      titleEl.textContent = 'Sorteio indisponível';
      errorEl.textContent = err.message || 'Tente de novo.';
      errorEl.hidden = false;
    } finally {
      animando = false;
      liberarBotoesSorteio();
    }
  }

  resetSeletorData();
  resetSeletorHorario();

  dateTrigger?.addEventListener('click', (e) => {
    e.stopPropagation();
    if (dateSelect?.classList.contains('sorteio-dd-select--open')) {
      fecharDropdown(dateSelect, dateList, dateTrigger);
    } else {
      fecharDropdown(timeSelect, timeList, timeTrigger);
      abrirDropdown(dateSelect, dateList, dateTrigger);
    }
  });

  timeTrigger?.addEventListener('click', (e) => {
    e.stopPropagation();
    if (timeSelect?.classList.contains('sorteio-dd-select--open')) {
      fecharDropdown(timeSelect, timeList, timeTrigger);
    } else {
      fecharDropdown(dateSelect, dateList, dateTrigger);
      abrirDropdown(timeSelect, timeList, timeTrigger);
    }
  });

  document.addEventListener('click', (e) => {
    if (dateSelect?.contains(e.target) || timeSelect?.contains(e.target)) return;
    fecharTodosDropdowns();
  });

  eventoForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!vencedorAtual || animando) return;

    eventoSubmit.disabled = true;
    eventoSubmit.textContent = 'Criando…';
    errorEl.hidden = true;

    try {
      const r = await fetch('/api/evento/criar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filme_id: vencedorAtual.filme_id,
          titulo: vencedorAtual.titulo,
          poster: vencedorAtual.poster,
          ano: vencedorAtual.ano,
          data: eventoData.value,
          hora: horaParaApi(eventoHora.value),
        }),
      });
      const data = await r.json().catch(() => ({}));

      if (r.status === 401) {
        window.location = `/auth/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }
      if (!r.ok) {
        throw new Error(data.message || 'Não foi possível criar o evento.');
      }

      eventoForm.hidden = true;
      const link = data.event_url
        ? `<a href="${data.event_url}" target="_blank" rel="noopener">Abrir evento no Discord</a>`
        : '';
      const aviso = data.warning ? `<br><small>${data.warning}</small>` : '';
      eventoSuccess.innerHTML = `Sessão criada! ${link}${aviso}`;
      eventoSuccess.hidden = false;
      phaseEl.textContent = 'Agendado';
      titleEl.textContent = 'Evento no Discord';
    } catch (err) {
      errorEl.textContent = err.message || 'Erro ao criar evento.';
      errorEl.hidden = false;
      atualizarBotaoEvento();
      eventoSubmit.textContent = 'Criar sessão';
    }
  });

  document.querySelectorAll('[data-sorteio-open]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (animando) return;
      rodarAnimacao();
    });
  });

  againBtn?.addEventListener('click', () => {
    if (animando) return;
    rodarAnimacao();
  });

  closeBtn?.addEventListener('click', fecharModal);
  backdropEl?.addEventListener('click', fecharModal);

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (dateSelect?.classList.contains('sorteio-dd-select--open')
        || timeSelect?.classList.contains('sorteio-dd-select--open')) {
      fecharTodosDropdowns();
      return;
    }
    if (!sorteioModal.classList.contains('open')) return;
    fecharModal();
  });
}
