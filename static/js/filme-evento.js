/* ── Criar evento na página de detalhes do filme (role Cinéfilo) ── */

const filmeEventoForm = document.getElementById('filme-evento-form');
if (filmeEventoForm && document.body?.dataset?.podeSorteio === '1') {
  const eventoData = document.getElementById('filme-evento-data');
  const dateSelect = document.getElementById('filme-date-select');
  const dateTrigger = document.getElementById('filme-date-trigger');
  const dateValue = document.getElementById('filme-date-value');
  const dateList = document.getElementById('filme-date-list');
  const eventoHora = document.getElementById('filme-evento-hora');
  const timeSelect = document.getElementById('filme-time-select');
  const timeTrigger = document.getElementById('filme-time-trigger');
  const timeValue = document.getElementById('filme-time-value');
  const timeList = document.getElementById('filme-time-list');
  const eventoSubmit = document.getElementById('filme-evento-submit');
  const eventoSuccess = document.getElementById('filme-evento-success');
  const eventoError = document.getElementById('filme-evento-error');
  const eventoTz = document.getElementById('filme-evento-tz');

  let pickerLimites = null;
  let opcoesDatas = [];
  let opcoesHoras = [];
  let listaDatasPronta = false;
  let listaHorariosPronta = false;

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

  function dataHoraEventoValida() {
    if (!eventoData?.value || !eventoHora?.value) return false;
    return instanteBRT(eventoData.value, eventoHora.value) > new Date();
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

  function atualizarBotaoEvento() {
    if (!eventoSubmit) return;
    eventoSubmit.disabled = !dataHoraEventoValida();
  }

  async function configurarPickersEvento() {
    if (!pickerLimites) {
      const r = await fetch('/api/evento/opcoes');
      if (r.status === 401) {
        window.location = `/auth/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }
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
    atualizarBotaoEvento();
  }

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

  filmeEventoForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!dataHoraEventoValida()) return;

    eventoSubmit.disabled = true;
    eventoSubmit.textContent = 'Criando…';
    eventoError.hidden = true;
    eventoSuccess.hidden = true;

    try {
      const r = await fetch('/api/evento/criar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filme_id: filmeEventoForm.dataset.imdb,
          titulo: filmeEventoForm.dataset.titulo,
          poster: filmeEventoForm.dataset.poster,
          ano: filmeEventoForm.dataset.ano,
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

      filmeEventoForm.hidden = true;
      const link = data.event_url
        ? `<a href="${data.event_url}" target="_blank" rel="noopener">Abrir evento no Discord</a>`
        : '';
      const aviso = data.warning ? `<br><small>${data.warning}</small>` : '';
      eventoSuccess.innerHTML = `Sessão criada! ${link}${aviso}`;
      eventoSuccess.hidden = false;
    } catch (err) {
      eventoError.textContent = err.message || 'Erro ao criar evento.';
      eventoError.hidden = false;
      eventoSubmit.disabled = false;
      eventoSubmit.textContent = 'Criar sessão';
    }
  });

  configurarPickersEvento().catch((err) => {
    eventoError.textContent = err.message;
    eventoError.hidden = false;
  });
}
