"""Criação de eventos agendados no Discord (REST API) — compartilhado com o site."""

import base64
import os
import re
from datetime import datetime, timedelta, timezone

import requests

import convex_db
from event_cover_utils import genero_para_evento, preparar_capa_evento
from synopsis_utils import sinopse_para_filme

BRT = timezone(timedelta(hours=-3))
_DISCORD_API = "https://discord.com/api/v10"
_HTTP_HEADERS = {"User-Agent": "DiscordBot (https://github.com/cleberrandreazza/bot_film, 1.0)"}

_DIAS_SEMANA_PT = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
_EVENTO_HORA_INICIO_MIN = 12 * 60  # 12:00
_EVENTO_HORA_FIM_MIN = 24 * 60  # 00:00 (meia-noite do fim do dia escolhido)
_EVENTO_HORA_INTERVALO_MIN = 15


def _build_horas_evento() -> tuple[str, ...]:
    horas: list[str] = []
    t = _EVENTO_HORA_INICIO_MIN
    while t <= _EVENTO_HORA_FIM_MIN:
        h = (t // 60) % 24
        m = t % 60
        horas.append(f"{h:02d}:{m:02d}")
        t += _EVENTO_HORA_INTERVALO_MIN
    return tuple(horas)


_HORAS_EVENTO = _build_horas_evento()
_EVENTO_DURACAO_PADRAO_MIN = 120
_EVENTO_DURACAO_MIN_MIN = 30
_EVENTO_DURACAO_MAX_MIN = 480

OMDB_KEY = os.environ.get("OMDB_API_KEY", "").strip()


def _bot_token() -> str:
    return os.environ.get("DISCORD_TOKEN", "").strip()


def _guild_id() -> str:
    return os.environ.get("DISCORD_GUILD_ID", "").strip()


def _voice_channel_id() -> str:
    return os.environ.get("EVENTO_VOICE_CHANNEL_ID", "").strip()


def _announce_channel_id() -> str:
    return os.environ.get("EVENTO_ANNOUNCE_CHANNEL_ID", "").strip()


def _notify_role_id() -> str:
    return os.environ.get(
        "EVENTO_CINEFILO_ROLE_ID",
        os.environ.get("EVENTO_NOTIFY_ROLE_ID", "1508308918353526814"),
    ).strip()


def opcoes_data() -> list[dict]:
    now = datetime.now(BRT)
    out = []
    for offset in range(90):
        day = now.date() + timedelta(days=offset)
        valor = day.strftime("%d/%m/%Y")
        abrev = day.strftime("%d/%m")
        wd = _DIAS_SEMANA_PT[day.weekday()]
        if offset == 0:
            rotulo = f"Hoje · {abrev} ({wd})"
        elif offset == 1:
            rotulo = f"Amanhã · {abrev} ({wd})"
        else:
            rotulo = f"{wd} · {valor}"
        out.append({"value": valor, "label": rotulo})
    return out


def opcoes_hora() -> list[str]:
    return list(_HORAS_EVENTO)


def horas_validas_para_data(data: str) -> list[str]:
    """Horários de 15 em 15 min ainda disponíveis na data informada (BRT)."""
    out: list[str] = []
    for hora in _HORAS_EVENTO:
        dt, erro = parse_data_hora(data, hora)
        if dt is not None and erro is None:
            out.append(hora)
    return out


def limites_picker_evento() -> dict:
    """Metadados do picker do site (mesmo fuso e opções do /evento no Discord)."""
    now = datetime.now(BRT)
    max_day = now.date() + timedelta(days=90)
    return {
        "timezone_label": "Horário de Brasília (BRT)",
        "min_date": now.date().isoformat(),
        "max_date": max_day.isoformat(),
    }


def opcoes_picker_evento() -> dict:
    """Opções de data/hora idênticas aos selects do comando /evento."""
    return {
        **limites_picker_evento(),
        "datas": opcoes_data(),
        "horas": opcoes_hora(),
    }


def _parse_runtime_minutes(runtime: str) -> int | None:
    if not runtime:
        return None
    s = runtime.strip().lower()
    total = 0
    h = re.search(r"(\d+)\s*h", s)
    m = re.search(r"(\d+)\s*min", s)
    if h:
        total += int(h.group(1)) * 60
    if m:
        total += int(m.group(1))
    if total > 0:
        return total
    only_digits = re.fullmatch(r"\d+", s.replace(" ", ""))
    if only_digits:
        return int(only_digits.group(0))
    return None


def _fetch_omdb(imdb_id: str) -> dict | None:
    if not OMDB_KEY or not imdb_id:
        return None
    try:
        r = requests.get(
            "https://www.omdbapi.com/",
            params={"apikey": OMDB_KEY, "i": imdb_id, "plot": "full"},
            headers=_HTTP_HEADERS,
            timeout=8,
        )
        if r.ok:
            data = r.json()
            if data.get("Response") == "True":
                return data
    except Exception as e:
        print(f"[Evento] OMDB: {e}")
    return None


def _omdb_valor(val) -> str:
    if not val or str(val).upper() == "N/A":
        return ""
    return str(val).strip()


def _discord_image_data_uri(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    """Discord exige Data URI (não só base64 cru) no campo image."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _parse_data_evento(data: str, now: datetime) -> datetime | None:
    data = data.strip()
    alias = data.lower().replace("ã", "a")
    if alias == "hoje":
        return datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    if alias == "amanha":
        d = now.date() + timedelta(days=1)
        return datetime(d.year, d.month, d.day, tzinfo=now.tzinfo)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d/%m"):
        try:
            dt = datetime.strptime(data, fmt)
            if fmt == "%d/%m":
                dt = dt.replace(year=now.year)
                if dt.date() < now.date():
                    dt = dt.replace(year=now.year + 1)
            return dt.replace(tzinfo=now.tzinfo)
        except ValueError:
            continue
    return None


def parse_data_hora(data: str, hora: str) -> tuple[datetime | None, str | None]:
    data = (data or "").strip()
    hora = (hora or "").strip().replace("h", ":").rstrip(":")
    if ":" not in hora:
        hora = hora + ":00"

    now = datetime.now(BRT)
    dt = _parse_data_evento(data, now)
    if not dt:
        return None, "Data inválida. Use dd/mm/aaaa ou escolha na lista."

    try:
        t = datetime.strptime(hora, "%H:%M").time()
        if t.minute % 15 != 0:
            return None, (
                "O Discord só aceita horários de 15 em 15 minutos "
                "(ex.: 20:00, 20:15, 20:30)."
            )
        dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0, tzinfo=BRT)
        if t.hour == 0 and t.minute == 0:
            dt += timedelta(days=1)
    except ValueError:
        return None, "Hora inválida. Use HH:MM (ex: 20:00)."

    if dt < datetime.now(BRT):
        return None, "A data/hora do evento já passou."
    return dt, None


def _duracao_evento(imdb_id: str, omdb_data: dict | None = None) -> timedelta:
    data = omdb_data or _fetch_omdb(imdb_id)
    mins = _parse_runtime_minutes(data.get("Runtime", "")) if data else None
    if mins:
        mins = max(_EVENTO_DURACAO_MIN_MIN, min(mins, _EVENTO_DURACAO_MAX_MIN))
        return timedelta(minutes=mins)
    return timedelta(minutes=_EVENTO_DURACAO_PADRAO_MIN)


def _formatar_duracao(minutos: int) -> str:
    if minutos >= 60:
        h, m = divmod(minutos, 60)
        return f"{h}h {m:02d}min" if m else f"{h}h"
    return f"{minutos} min"


def _descricao_evento(
    canal_nome: str,
    duracao_min: int,
    ano: str,
    genero: str,
    sinopse: str,
) -> str:
    partes = []
    meta = []
    if ano:
        meta.append(f"**Ano:** {ano}")
    if genero:
        meta.append(f"**Gênero:** {genero}")
    if meta:
        partes.append(" · ".join(meta))
    if sinopse:
        texto = sinopse if len(sinopse) <= 600 else sinopse[:597] + "..."
        partes.append(f"\n{texto}")
    partes.append(
        f"\nDuração prevista: **{_formatar_duracao(duracao_min)}**.\n\n"
        f"Marque como **Interessado** e entre no canal **{canal_nome}** "
        f"durante o evento para registrar sua presença."
    )
    return "\n".join(partes)[:1000]


def _discord_headers() -> dict:
    token = _bot_token()
    return {
        **_HTTP_HEADERS,
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }


def listar_usuarios_evento_discord(guild_id: str, event_id: str) -> list[dict]:
    """Usuários que marcaram Interessado no evento (API do Discord)."""
    from discord_profiles import perfil_from_api

    if not _bot_token() or not guild_id or not event_id:
        return []
    url = f"{_DISCORD_API}/guilds/{guild_id}/scheduled-events/{event_id}/users"
    out: list[dict] = []
    before: str | None = None
    try:
        while True:
            params: dict = {"limit": 100, "with_member": "true"}
            if before:
                params["before"] = before
            r = requests.get(
                url, headers=_discord_headers(), params=params, timeout=15,
            )
            if not r.ok:
                print(f"[Evento] Lista de inscritos HTTP {r.status_code}: {r.text[:200]}")
                break
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            for entry in batch:
                user = entry.get("user") or {}
                uid = str(user.get("id", "")).strip()
                if not uid:
                    continue
                out.append(perfil_from_api(user, entry.get("member")))
            if len(batch) < 100:
                break
            last = batch[-1].get("user") or {}
            before = str(last.get("id", "")) or None
            if not before:
                break
    except Exception as e:
        print(f"[Evento] Erro ao listar inscritos: {e}")
    return out


def _nome_canal_voz() -> tuple[str | None, str | None]:
    """Retorna (channel_id, nome) ou (None, mensagem_erro)."""
    cid = _voice_channel_id()
    if not cid:
        return None, (
            "Canal de voz do evento não configurado "
            "(EVENTO_VOICE_CHANNEL_ID)."
        )
    try:
        r = requests.get(
            f"{_DISCORD_API}/channels/{cid}",
            headers=_discord_headers(),
            timeout=8,
        )
        if r.ok:
            return cid, r.json().get("name") or "voz"
    except Exception as e:
        print(f"[Evento] Canal voz: {e}")
    return cid, "voz"


def _canais_aviso(canal_extra: str | None = None) -> list[str]:
    """Ordem igual ao bot: EVENTO_ANNOUNCE_CHANNEL_ID, depois canal extra (/evento)."""
    ids: list[str] = []
    principal = _announce_channel_id()
    if principal:
        ids.append(principal)
    extra = (canal_extra or "").strip()
    if extra and extra not in ids:
        ids.append(extra)
    return ids


def _publicar_aviso(event_url: str, canal_extra: str | None = None) -> str | None:
    """Retorna aviso se falhou em todos os canais; None se publicou."""
    candidatos = _canais_aviso(canal_extra)
    if not candidatos:
        return "Evento criado, mas o aviso não foi publicado (canal não configurado)."
    role_id = _notify_role_id()
    content = f"Novo evento marcado <@&{role_id}>\n{event_url}" if role_id else (
        f"Novo evento marcado\n{event_url}"
    )
    payload = {
        "content": content,
        "allowed_mentions": {"roles": [role_id]} if role_id else {},
    }
    for canal_id in candidatos:
        try:
            r = requests.post(
                f"{_DISCORD_API}/channels/{canal_id}/messages",
                headers=_discord_headers(),
                json=payload,
                timeout=10,
            )
            if r.ok:
                return None
            print(f"[Evento] Aviso HTTP {r.status_code} em {canal_id}: {r.text[:200]}")
        except Exception as e:
            print(f"[Evento] Aviso em {canal_id}: {e}")
    return "Evento criado, mas o aviso não foi publicado no Discord."


def criar_evento_agendado(
    filme_id: str,
    titulo: str,
    capa_url: str,
    data: str,
    hora: str,
    ano_imdb: str = "",
    *,
    announce_channel_id: str | None = None,
) -> tuple[dict | None, str | None]:
    """
    Cria scheduled event no Discord e registro no Convex.
    Retorna ({"event_id", "event_url", "warning"?}, erro).
    """
    gid = _guild_id()
    if not gid or not _bot_token():
        return None, "Bot Discord não configurado no servidor (DISCORD_TOKEN / DISCORD_GUILD_ID)."

    dt, erro = parse_data_hora(data, hora)
    if erro:
        return None, erro

    channel_id, canal_erro = _nome_canal_voz()
    if not channel_id:
        return None, canal_erro

    omdb_data = _fetch_omdb(filme_id)
    if omdb_data:
        meta = {
            "ano": _omdb_valor(omdb_data.get("Year", ""))[:4],
            "genero": _omdb_valor(omdb_data.get("Genre", "")),
            "sinopse": _omdb_valor(omdb_data.get("Plot", "")),
        }
    else:
        meta = {"ano": "", "genero": "", "sinopse": ""}

    ano_evt = meta["ano"] or (ano_imdb or "")[:4]
    genero_evt = genero_para_evento(filme_id, meta["genero"])
    titulo_omdb = _omdb_valor(omdb_data.get("Title", "")) if omdb_data else ""
    sinopse_evt = sinopse_para_filme(
        titulo, ano_evt, titulo_omdb, meta["sinopse"], filme_id
    )

    duracao = _duracao_evento(filme_id, omdb_data)
    duracao_min = int(duracao.total_seconds() // 60)
    fim = dt + duracao

    _, canal_nome = _nome_canal_voz()
    descricao = _descricao_evento(canal_nome or "voz", duracao_min, ano_evt, genero_evt, sinopse_evt)

    payload = {
        "name": f"🎬 {titulo}",
        "description": descricao,
        "scheduled_start_time": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scheduled_end_time": fim.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "privacy_level": 2,
        "entity_type": 2,
        "channel_id": int(channel_id),
    }

    poster_url = (capa_url or "").strip()
    if not poster_url and omdb_data:
        poster_url = _omdb_valor(omdb_data.get("Poster", ""))

    capa_bytes = preparar_capa_evento(filme_id, poster_url)
    if capa_bytes:
        payload["image"] = _discord_image_data_uri(capa_bytes)

    try:
        r = requests.post(
            f"{_DISCORD_API}/guilds/{gid}/scheduled-events",
            headers=_discord_headers(),
            json=payload,
            timeout=20,
        )
        if not r.ok and "image" in payload:
            print(f"[Evento] Capa rejeitada ({r.status_code}): {r.text[:400]}")
            payload.pop("image", None)
            r = requests.post(
                f"{_DISCORD_API}/guilds/{gid}/scheduled-events",
                headers=_discord_headers(),
                json=payload,
                timeout=20,
            )
        if not r.ok:
            msg = "Erro ao criar o evento no Discord."
            try:
                detail = r.json()
                if isinstance(detail, dict) and detail.get("message"):
                    msg = detail["message"]
            except Exception:
                pass
            return None, msg
        ev = r.json()
    except Exception as e:
        return None, f"Erro ao criar o evento: {e}"

    event_id = str(ev.get("id", ""))
    event_url = f"https://discord.com/events/{gid}/{event_id}"

    try:
        convex_db.criar_evento(
            event_id,
            filme_id,
            titulo,
            dt.isoformat(),
            channel_id,
            gid,
        )
        convex_db.cancelar_eventos_pendentes_filme(filme_id, exceto_discord_event_id=event_id)
    except Exception as e:
        print(f"[Evento] Convex: {e}")

    warning = _publicar_aviso(event_url, announce_channel_id)
    result = {"event_id": event_id, "event_url": event_url}
    if warning:
        result["warning"] = warning
    return result, None
